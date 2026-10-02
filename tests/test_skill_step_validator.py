import unittest
from unittest.mock import AsyncMock, patch

from backend.agent.skills.step_validator import (
    StepValidationIssue,
    StepValidationResult,
    validator,
)


class TestSkillStepValidator(unittest.IsolatedAsyncioTestCase):
    def test_flags_first_click_without_navigation_or_selector(self):
        issues = validator._heuristic_validate([
            {"action_type": "browser_click", "title": "Click Send", "selector_bundle": None},
            {"action_type": "browser_navigate", "title": "Open Gmail", "url": "https://mail.google.com/mail/u/0/#inbox"},
        ])

        self.assertIn("order", {issue.issue_type for issue in issues})
        self.assertIn("precondition", {issue.issue_type for issue in issues})
        self.assertTrue(any(issue.severity == "error" for issue in issues))

    async def test_ai_reorders_original_steps_and_preserves_selectors(self):
        steps = [
            {
                "step_id": "send-click",
                "action_type": "browser_click",
                "title": "Click Send",
                "selector_bundle": {"testId": "send-button"},
            },
            {
                "step_id": "gmail-navigation",
                "action_type": "browser_navigate",
                "title": "Open Gmail",
                "url": "https://mail.google.com/mail/u/0/#inbox",
            },
        ]
        ai_result = StepValidationResult(
            is_valid=False,
            issues=[StepValidationIssue(
                step_index=0,
                severity="error",
                issue_type="order",
                title="Click before route",
                description="Navigate before interacting",
            )],
            corrected_order=[1, 0],
        )

        with patch.object(validator, "_ai_validate_steps", new=AsyncMock(return_value=ai_result)):
            result = await validator.validate_steps(steps, prompt_intent="Send an email", auto_fix=True)

        self.assertEqual([step["step_id"] for step in result.corrected_steps], ["gmail-navigation", "send-click"])
        self.assertEqual(result.corrected_steps[1]["selector_bundle"], {"testId": "send-button"})
        self.assertTrue(result.is_valid)


if __name__ == "__main__":
    unittest.main()