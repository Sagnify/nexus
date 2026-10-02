"""
Tests for Skill Learning Pipeline:
- DemonstrationSessionManager
- ActionSemanticizer
- SkillCompiler
- SkillMatcher
- SkillRuntime
"""
import asyncio
import time
import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User
from backend.database.repositories.skill_repo import SkillRepository
from backend.agent.skills.session import DemonstrationSessionManager, DemonstrationEvent
from backend.agent.skills.semanticizer import ActionSemanticizer
from backend.agent.skills.compiler import SkillCompiler
from backend.agent.skills.matcher import SkillMatcher
from backend.agent.skills.runtime import SkillRuntime


class TestSkillsPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.session_factory() as session:
            self.user = User(firebase_uid="uid_pipe_test", email="pipe@test.com", display_name="Pipe User")
            session.add(self.user)
            await session.commit()
            self.user_id = self.user.id

        self.session_mgr = DemonstrationSessionManager()
        self.semanticizer = ActionSemanticizer()
        self.compiler = SkillCompiler()
        self.matcher = SkillMatcher()
        self.runtime = SkillRuntime()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_session_lifecycle_and_buffering(self):
        """DemonstrationSessionManager records, pauses, resumes, and purges sessions."""
        session = await self.session_mgr.start_session(
            user_id=str(self.user_id),
            target_environment="browser",
            prompt_intent="Download Monthly Report",
        )
        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.status, "recording")

        # Record events
        ok1 = await self.session_mgr.record_event(
            session.session_id,
            {
                "environment": "browser",
                "event_type": "click",
                "url": "https://example.com",
                "selector_bundle": {"testId": "btn-export", "cssPath": "#btn-export"},
            },
        )
        self.assertTrue(ok1)

        # Pause
        paused = await self.session_mgr.pause_session(session.session_id, str(self.user_id))
        self.assertTrue(paused)

        # Attempt to record while paused -> returns False
        ok_paused = await self.session_mgr.record_event(
            session.session_id,
            {"environment": "browser", "event_type": "click"},
        )
        self.assertFalse(ok_paused)

        # Resume
        resumed = await self.session_mgr.resume_session(session.session_id, str(self.user_id))
        self.assertTrue(resumed)

        # Complete
        completed = await self.session_mgr.complete_session(session.session_id, str(self.user_id))
        self.assertIsNotNone(completed)
        self.assertEqual(len(completed.events), 1)

        # Discard
        discarded = await self.session_mgr.discard_session(session.session_id, str(self.user_id))
        self.assertTrue(discarded)
        self.assertIsNone(await self.session_mgr.get_session(session.session_id))

    def test_semanticizer_noise_reduction_and_typing_coalescence(self):
        """Sequential typing events on the same element coalesce into a single type_text step."""
        now = time.time()
        selector = {"testId": "search-input", "cssPath": "input#search"}

        raw_events = [
            DemonstrationEvent(
                timestamp=now,
                environment="browser",
                event_type="click",
                url="https://app.test",
                selector_bundle=selector,
            ),
            DemonstrationEvent(
                timestamp=now + 0.1,
                environment="browser",
                event_type="input",
                url="https://app.test",
                selector_bundle=selector,
                value="N",
            ),
            DemonstrationEvent(
                timestamp=now + 0.2,
                environment="browser",
                event_type="input",
                url="https://app.test",
                selector_bundle=selector,
                value="NEX",
            ),
            DemonstrationEvent(
                timestamp=now + 0.3,
                environment="browser",
                event_type="input",
                url="https://app.test",
                selector_bundle=selector,
                value="NEXUS",
            ),
            DemonstrationEvent(
                timestamp=now + 0.4,
                environment="browser",
                event_type="keydown",
                url="https://app.test",
                selector_bundle=selector,
                key="Enter",
            ),
        ]

        actions = self.semanticizer.semanticize(raw_events)
        # Should have 1 click + 1 type (with final value "NEXUS" and press_enter=True)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].action_type, "browser_click")
        self.assertEqual(actions[1].action_type, "browser_type")
        self.assertEqual(actions[1].value, "NEXUS")
        self.assertTrue(actions[1].metadata.get("press_enter"))

    def test_compiler_parameter_generalization_and_validation(self):
        """Compiler identifies date entities and converts them into {{target_date}} parameters."""
        raw_actions = self.semanticizer.semanticize([
            DemonstrationEvent(
                timestamp=time.time(),
                environment="browser",
                event_type="navigate",
                value="https://billing.example.com",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 0.5,
                environment="browser",
                event_type="input",
                selector_bundle={"cssPath": "#billing-date"},
                value="March 2026",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 1.0,
                environment="browser",
                event_type="click",
                selector_bundle={"testId": "export-pdf-btn", "textAnchor": "Download PDF"},
            ),
        ])

        draft = self.compiler.compile(
            raw_actions=raw_actions,
            prompt_intent="Download invoices for March 2026",
            skill_name="Download Invoices",
        )

        self.assertEqual(draft.name, "Download Invoices")
        self.assertEqual(len(draft.parameters_schema), 1)
        self.assertEqual(draft.parameters_schema[0].name, "target_date")
        self.assertEqual(draft.parameters_schema[0].type, "date")
        # Step 2 value should be templated
        self.assertEqual(draft.steps[1].value_template, "{{target_date}}")
        self.assertIn("target_date", draft.steps[1].parameter_references)

    async def test_matcher_and_runtime_plan_generation(self):
        """Matcher retrieves the skill by trigger phrase and runtime resolves parameters."""
        # Seed skill in DB
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_id,
                name="Download Monthly Billing",
                trigger_phrases=["download monthly billing", "get billing report"],
                parameters_schema=[
                    {"name": "target_date", "type": "date", "required": True, "default_value": "current"}
                ],
                steps_json=[
                    {
                        "action_type": "browser_navigate",
                        "execution_engine": "browser",
                        "title": "Open Billing",
                        "value": "https://billing.example.com",
                    },
                    {
                        "action_type": "browser_type",
                        "execution_engine": "browser",
                        "title": "Enter Billing Date",
                        "value_template": "{{target_date}}",
                        "selector_bundle": {"testId": "date-input"},
                    },
                ],
            )

        # Match exact trigger with a date in user prompt
        async with self.session_factory() as session:
            match = await self.matcher.match_skill(
                user_prompt="download monthly billing for April 2026",
                user_id=self.user_id,
                session=session,
            )
            self.assertIsNotNone(match)
            self.assertEqual(match.match_type, "semantic_similarity")
            self.assertEqual(match.resolved_parameters.get("target_date"), "April 2026")

            # Runtime converts into PlanSteps
            plan_steps = self.runtime.generate_plan_steps(match)
            self.assertEqual(len(plan_steps), 2)
            self.assertEqual(plan_steps[0]["tool"], "browser_navigate")
            self.assertEqual(plan_steps[1]["tool"], "browser_type")
            self.assertEqual(plan_steps[1]["args"]["text"], "April 2026")

    async def test_compiler_email_automation_noise_purge_and_generalization(self):
        """Compiler purges background noise (Google Meet) and parameterizes email, subject, body."""
        raw_events = [
            # Noisy background events on Google Meet
            DemonstrationEvent(
                timestamp=time.time(),
                environment="browser",
                event_type="navigate",
                value="https://meet.google.com/xyz-abc-def",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 0.2,
                environment="browser",
                event_type="click",
                url="https://meet.google.com/xyz-abc-def",
                selector_bundle={"ariaLabel": "Turn off microphone", "cssPath": "button.mic"},
            ),
            # True target application: Gmail
            DemonstrationEvent(
                timestamp=time.time() + 1.0,
                environment="browser",
                event_type="navigate",
                value="https://mail.google.com/mail/u/0/#inbox",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 1.5,
                environment="browser",
                event_type="click",
                url="https://mail.google.com/mail/u/0/#inbox",
                selector_bundle={"ariaLabel": "Compose", "cssPath": "div.T-I.T-I-KE"},
            ),
            DemonstrationEvent(
                timestamp=time.time() + 2.0,
                environment="browser",
                event_type="input",
                url="https://mail.google.com/mail/u/0/#inbox",
                selector_bundle={"ariaLabel": "To", "name": "to", "cssPath": "input[aria-label='To']"},
                value="swagnik@example.com",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 2.5,
                environment="browser",
                event_type="input",
                url="https://mail.google.com/mail/u/0/#inbox",
                selector_bundle={"name": "subjectbox", "ariaLabel": "Subject", "cssPath": "input[name='subjectbox']"},
                value="Quarterly Review Notes",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 3.0,
                environment="browser",
                event_type="input",
                url="https://mail.google.com/mail/u/0/#inbox",
                selector_bundle={"ariaLabel": "Message Body", "role": "textbox", "cssPath": "div[aria-label='Message Body']"},
                value="Hi team, here are the quarterly highlights for your review.",
            ),
            DemonstrationEvent(
                timestamp=time.time() + 3.5,
                environment="browser",
                event_type="click",
                url="https://mail.google.com/mail/u/0/#inbox",
                selector_bundle={"ariaLabel": "Send", "cssPath": "div[aria-label='Send']"},
            ),
        ]

        actions = self.semanticizer.semanticize(raw_events)
        draft = await self.compiler.compile_with_ai(
            raw_actions=actions,
            prompt_intent="Gmail Mail Sending Automation",
            category="browser",
        )

        # Target sites must NOT contain meet.google.com
        self.assertNotIn("meet.google.com", draft.target_sites)
        self.assertIn("mail.google.com", draft.target_sites)

        # Trigger phrases must have no emojis and no "on meet"
        for trig in draft.trigger_phrases:
            self.assertNotIn("meet", trig.lower())
            self.assertTrue(all(ord(c) < 128 for c in trig), f"Emoji found in trigger: {trig}")

        # Parameters must include recipient_email
        param_names = [p.name for p in draft.parameters_schema]
        self.assertIn("recipient_email", param_names)

    async def test_matcher_conversational_follow_up_and_parameter_propagation(self):
        """Matcher recognizes skill without exact prompt, detects missing params, and builds follow-up steps."""
        from backend.agent.nodes.executor import _propagate_user_param_input

        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_id,
                name="Gmail Mail Sending Automation",
                trigger_phrases=["send email", "send email to {{recipient_email}}"],
                parameters_schema=[
                    {"name": "recipient_email", "type": "email", "required": True, "description": "Recipient address"},
                    {"name": "subject", "type": "string", "required": True, "description": "Email subject"},
                    {"name": "body", "type": "string", "required": True, "description": "Email body content"},
                ],
                steps_json=[
                    {
                        "action_type": "browser_navigate",
                        "execution_engine": "browser",
                        "title": "Open Gmail",
                        "value": "https://mail.google.com",
                    },
                    {
                        "action_type": "browser_type",
                        "execution_engine": "browser",
                        "title": "Enter To",
                        "value_template": "{{recipient_email}}",
                        "selector_bundle": {"ariaLabel": "To"},
                    },
                    {
                        "action_type": "browser_type",
                        "execution_engine": "browser",
                        "title": "Enter Subject",
                        "value_template": "{{subject}}",
                        "selector_bundle": {"ariaLabel": "Subject"},
                    },
                    {
                        "action_type": "browser_click",
                        "execution_engine": "browser",
                        "title": "Click Send",
                        "selector_bundle": {"ariaLabel": "Send"},
                    },
                ],
            )

        # 1. User asks without providing recipient, subject, or body
        async with self.session_factory() as session:
            match = await self.matcher.match_skill(
                user_prompt="please send an email",
                user_id=self.user_id,
                session=session,
            )
            self.assertIsNotNone(match, "Skill should be recognized from natural prompt")
            self.assertEqual(match.skill.name, "Gmail Mail Sending Automation")
            # Missing parameters should be detected
            self.assertIn("recipient_email", match.missing_parameters)
            self.assertIn("subject", match.missing_parameters)
            self.assertIn("body", match.missing_parameters)

            # 2. Runtime generates conversational follow-up questions
            plan_steps = self.runtime.generate_plan_steps(match)
            # 3 follow-ups + 4 original steps = 7 total steps
            self.assertEqual(len(plan_steps), 7)
            self.assertEqual(plan_steps[0]["tool"], "ask_user")
            self.assertIn("recipient_email", plan_steps[0]["args"]["parameter_name"])
            self.assertEqual(plan_steps[1]["tool"], "ask_user")
            self.assertIn("subject", plan_steps[1]["args"]["parameter_name"])
            self.assertEqual(plan_steps[2]["tool"], "ask_user")
            self.assertIn("body", plan_steps[2]["args"]["parameter_name"])

            # 3. Simulate user answering follow-up: dynamic parameter propagation
            mock_state = {"resolved_params": {}}
            _propagate_user_param_input("recipient_email", "swagnik@example.com", plan_steps, mock_state)
            _propagate_user_param_input("subject", "Weekly Report", plan_steps, mock_state)

            # Check that the email typing step was dynamically updated with the user's input
            to_step = next(s for s in plan_steps if s.get("title") == "Enter To")
            self.assertEqual(to_step["args"]["text"], "swagnik@example.com")
            subject_step = next(s for s in plan_steps if s.get("title") == "Enter Subject")
            self.assertEqual(subject_step["args"]["text"], "Weekly Report")


if __name__ == "__main__":
    unittest.main()


