"""
Tests for:
- VLM Interaction Feature Extractor (enrich_events, extract_features_for_event)
- Step Validator (AI & Heuristic causality reordering, jitter pruning)
- SkillMatcher (Google Form domain matching and trigger phrase variations)
"""
import unittest
import uuid
from backend.agent.skills.session import DemonstrationEvent
from backend.agent.skills.vlm_extractor import VLMInteractionFeatureExtractor
from backend.agent.skills.step_validator import StepValidator
from backend.agent.skills.matcher import SkillMatcher
from backend.database.models import Skill, SkillVersion


class TestVLMAndStepValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.extractor = VLMInteractionFeatureExtractor()
        self.validator = StepValidator()
        self.matcher = SkillMatcher()

    async def test_vlm_feature_heuristic_fallback(self):
        """VLM extractor extracts resilient features when snapshot or coordinates are provided."""
        event = DemonstrationEvent(
            event_id="ev-1",
            session_id="sess-1",
            timestamp=100.0,
            event_type="click",
            target_element="DIV",
            selector_bundle={
                "ariaLabel": "Add question",
                "textAnchor": "+",
                "role": "button",
                "boundingRect": {"x": 500, "y": 250, "width": 40, "height": 40},
            },
            metadata={"clickCoords": {"x": 520, "y": 270}},
        )

        enriched = await self.extractor.enrich_events([event], prompt_intent="Create a google form")
        self.assertEqual(len(enriched), 1)
        feat = enriched[0].metadata.get("vlm_features")
        self.assertIsNotNone(feat)
        self.assertEqual(feat.get("visual_role"), "button")
        self.assertIn("Add question", feat.get("semantic_label"))
        self.assertEqual(feat.get("bounding_rect"), {"x": 500, "y": 250, "width": 40, "height": 40})

    async def test_step_validator_auto_reorders_navigation_to_start(self):
        """Step validator automatically places page navigation at step 0 and clears order warnings."""
        steps = [
            {
                "step_id": "step-click",
                "title": "Click Add question",
                "action_type": "browser_click",
                "selector_bundle": {"ariaLabel": "Add question"},
                "url": "https://docs.google.com/forms/d/123/edit",
            },
            {
                "step_id": "step-nav",
                "title": "Open Google Forms",
                "action_type": "browser_navigate",
                "url": "https://docs.google.com/forms/d/123/edit",
            },
            {
                "step_id": "step-type",
                "title": "Type question title",
                "action_type": "browser_type",
                "value_template": "{{question_1}}",
                "selector_bundle": {"placeholder": "Untitled question"},
                "url": "https://docs.google.com/forms/d/123/edit",
            },
        ]

        result = await self.validator.validate_steps(steps, auto_fix=True)
        self.assertTrue(result.is_valid)
        self.assertIsNotNone(result.validated_steps)
        # First step must be navigation
        self.assertEqual(result.validated_steps[0]["action_type"], "browser_navigate")
        # No remaining order issues
        order_issues = [iss for iss in result.issues if iss.issue_type == "order"]
        self.assertEqual(len(order_issues), 0)

    async def test_step_validator_prunes_duplicate_click_jitter(self):
        """Step validator prunes consecutive duplicate clicks on the exact same element."""
        steps = [
            {
                "step_id": "step-nav",
                "title": "Open Form",
                "action_type": "browser_navigate",
                "url": "https://docs.google.com/forms",
            },
            {
                "step_id": "step-c1",
                "title": "Click Option 1",
                "action_type": "browser_click",
                "selector_bundle": {"cssPath": "#opt1"},
            },
            {
                "step_id": "step-c2",
                "title": "Click Option 1",
                "action_type": "browser_click",
                "selector_bundle": {"cssPath": "#opt1"},
            },
        ]

        result = await self.validator.validate_steps(steps, auto_fix=True)
        self.assertIsNotNone(result.validated_steps)
        self.assertEqual(len(result.validated_steps), 2)

    def test_matcher_semantic_similarity_form_boost(self):
        """Form queries are boosted with high confidence for form automation skills."""
        skill = Skill(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Google Form Automation",
            category="web_automation",
            environment="browser",
            trigger_phrases=["create google form", "google form automation", "gform automate"],
        )
        version = SkillVersion(
            id=uuid.uuid4(),
            skill_id=skill.id,
            version_number=1,
            steps_json=[{"action_type": "browser_navigate", "url": "https://docs.google.com/forms"}],
        )
        skill.versions = [version]

        score = self.matcher._score_semantic_similarity("create a google form for feedback", skill)
        self.assertGreaterEqual(score, 0.85)

        score2 = self.matcher._score_semantic_similarity("make a survey form", skill)
        self.assertGreaterEqual(score2, 0.85)


if __name__ == "__main__":
    unittest.main()
