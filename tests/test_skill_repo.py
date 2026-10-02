"""
Tests for SkillRepository:
- Skill and SkillVersion creation
- Tenant and user data isolation
- Version creation and optimistic concurrency locking
- Version rollback semantics
- Execution telemetry recording and health auto-suspension (healthy -> degraded -> suspended)
- Cascade deletion
"""
import asyncio
import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User, Skill, SkillVersion, SkillExecution
from backend.database.repositories.skill_repo import SkillRepository


class TestSkillRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        # Seed two distinct users
        async with self.session_factory() as session:
            self.user_a = User(firebase_uid="uid_alice", email="alice@test.com", display_name="Alice")
            self.user_b = User(firebase_uid="uid_bob", email="bob@test.com", display_name="Bob")
            session.add_all([self.user_a, self.user_b])
            await session.commit()
            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_create_skill_and_initial_version(self):
        """Creating a skill creates both the Skill record and initial SkillVersion (v1)."""
        steps = [
            {
                "step_id": "step-1",
                "title": "Navigate to Stripe",
                "action_type": "browser_navigate",
                "execution_engine": "browser",
                "value_template": "https://dashboard.stripe.com/invoices",
            },
            {
                "step_id": "step-2",
                "title": "Click Export",
                "action_type": "browser_click",
                "execution_engine": "browser",
                "selector_bundle": {"test_id": "export-btn", "css_path": "button.export"},
            },
        ]
        preconditions = [{"check_type": "url_contains", "target": "stripe.com"}]
        postconditions = [{"check_type": "file_created", "target": "invoices.csv"}]

        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_a_id,
                name="Download Stripe Invoices",
                description="Fetches monthly invoice CSV from Stripe",
                category="finance",
                environment="browser",
                trigger_phrases=["download stripe invoices", "get billing export"],
                parameters_schema=[{"name": "month", "type": "string", "required": True}],
                steps_json=steps,
                preconditions=preconditions,
                postconditions=postconditions,
            )

            self.assertIsNotNone(skill.id)
            self.assertEqual(skill.name, "Download Stripe Invoices")
            self.assertEqual(skill.current_version, 1)
            self.assertEqual(skill.health_status, "healthy")
            self.assertEqual(len(skill.versions), 1)
            self.assertEqual(skill.versions[0].version_number, 1)
            self.assertEqual(len(skill.versions[0].steps_json), 2)

    async def test_user_data_isolation(self):
        """User B cannot fetch, update, or delete User A's skill."""
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill_a = await repo.create_skill(
                user_id=self.user_a_id,
                name="Alice's Private Workflow",
                steps_json=[{"step_id": "s1", "title": "Step 1"}],
            )
            skill_a_id = skill_a.id

        # User B attempts to access Alice's skill
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            lookup = await repo.get_by_id(skill_a_id, user_id=self.user_b_id)
            self.assertIsNone(lookup, "User B must not be able to get Alice's skill by ID")

            b_skills = await repo.list_user_skills(user_id=self.user_b_id)
            self.assertEqual(len(b_skills), 0)

            # User B attempts to delete Alice's skill
            deleted = await repo.delete_skill(skill_a_id, user_id=self.user_b_id)
            self.assertFalse(deleted, "User B must not be able to delete Alice's skill")

    async def test_create_new_version_with_optimistic_locking(self):
        """Creating a new version increments version_number and enforces optimistic concurrency."""
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_a_id,
                name="Invoice Pipeline",
                steps_json=[{"step_id": "s1", "title": "Step 1"}],
            )
            skill_id = skill.id

        # Add Version 2 with correct expected_version=1
        new_steps = [
            {"step_id": "s1", "title": "Step 1"},
            {"step_id": "s2", "title": "Step 2 Added"},
        ]
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            updated_skill, v2 = await repo.create_new_version(
                skill_id=skill_id,
                user_id=self.user_a_id,
                steps_json=new_steps,
                change_summary="Added step 2",
                expected_version=1,
            )
            self.assertEqual(updated_skill.current_version, 2)
            self.assertEqual(v2.version_number, 2)

        # Attempt to add another version with stale expected_version=1 -> Must fail
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            with self.assertRaises(ValueError):
                await repo.create_new_version(
                    skill_id=skill_id,
                    user_id=self.user_a_id,
                    steps_json=new_steps,
                    expected_version=1,  # Stale, current is 2
                )

    async def test_rollback_version(self):
        """Rollback creates a new version containing the content of the target version."""
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_a_id,
                name="Rollback Test",
                steps_json=[{"step_id": "v1-step", "title": "Original"}],
            )
            skill_id = skill.id

            # Add v2
            await repo.create_new_version(
                skill_id=skill_id,
                user_id=self.user_a_id,
                steps_json=[{"step_id": "v2-step", "title": "Faulty Change"}],
                expected_version=1,
            )

        # Roll back to version 1 -> should create version 3 with v1-step
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            rolled_back = await repo.rollback_version(
                skill_id=skill_id,
                user_id=self.user_a_id,
                target_version_number=1,
            )
            self.assertEqual(rolled_back.current_version, 3)

            latest = await repo.get_by_id(skill_id, self.user_a_id)
            v3 = [v for v in latest.versions if v.version_number == 3][0]
            self.assertEqual(v3.steps_json[0]["step_id"], "v1-step")

    async def test_health_telemetry_and_auto_suspension(self):
        """Health status degrades after 2 consecutive failures and suspends after 3 consecutive failures."""
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_a_id,
                name="Health Test Skill",
                steps_json=[{"step_id": "s1"}],
            )
            skill_id = skill.id

        # 1st failure -> degraded = False, consecutive_failures = 1
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            await repo.record_execution(
                skill_id=skill_id,
                user_id=self.user_a_id,
                version_number=1,
                status="failed",
                error_message="Timeout finding button",
            )
            s = await repo.get_by_id(skill_id, self.user_a_id)
            self.assertEqual(s.consecutive_failures, 1)
            self.assertEqual(s.health_status, "healthy")

        # 2nd consecutive failure -> health_status = "degraded"
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            await repo.record_execution(
                skill_id=skill_id,
                user_id=self.user_a_id,
                version_number=1,
                status="failed",
                error_message="Timeout finding button",
            )
            s = await repo.get_by_id(skill_id, self.user_a_id)
            self.assertEqual(s.consecutive_failures, 2)
            self.assertEqual(s.health_status, "degraded")

        # 3rd consecutive failure -> health_status = "suspended" (auto-replay locked)
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            await repo.record_execution(
                skill_id=skill_id,
                user_id=self.user_a_id,
                version_number=1,
                status="failed",
                error_message="Fatal error",
            )
            s = await repo.get_by_id(skill_id, self.user_a_id)
            self.assertEqual(s.consecutive_failures, 3)
            self.assertEqual(s.health_status, "suspended")

            # Suspended skill should be excluded from get_active_skills_for_matching
            matching_skills = await repo.get_active_skills_for_matching(self.user_a_id)
            self.assertEqual(len(matching_skills), 0)

        # Successful execution restores health and clears consecutive failures
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            # Reactivate skill
            await repo.set_health_status(skill_id, self.user_a_id, "healthy")
            await repo.record_execution(
                skill_id=skill_id,
                user_id=self.user_a_id,
                version_number=1,
                status="completed",
            )
            s = await repo.get_by_id(skill_id, self.user_a_id)
            self.assertEqual(s.consecutive_failures, 0)
            self.assertEqual(s.success_count, 1)
            self.assertEqual(s.health_status, "healthy")

    async def test_delete_skill_cascades(self):
        """Deleting a skill cleanly cascades to delete versions and executions."""
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.create_skill(
                user_id=self.user_a_id,
                name="Cascade Skill",
                steps_json=[{"step_id": "s1"}],
            )
            skill_id = skill.id
            await repo.record_execution(
                skill_id=skill_id,
                user_id=self.user_a_id,
                version_number=1,
                status="completed",
            )

        # Delete
        async with self.session_factory() as session:
            repo = SkillRepository(session)
            deleted = await repo.delete_skill(skill_id, self.user_a_id)
            self.assertTrue(deleted)

            lookup = await repo.get_by_id(skill_id, self.user_a_id)
            self.assertIsNone(lookup)


if __name__ == "__main__":
    unittest.main()
