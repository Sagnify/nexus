"""
Step Validator for NEXUS Skill Learning.
Validates compiled steps for logical order, dependencies, and execution feasibility.
Uses AI reasoning to detect issues like:
- Steps out of order (e.g., clicking before navigating)
- Missing preconditions (e.g., typing in a field that doesn't exist yet)
- Unreachable steps (e.g., clicking on element that's not visible)
- Logical inconsistencies (e.g., navigating away then trying to interact with previous page)
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("nexus.skills.step_validator")


class StepValidationIssue(BaseModel):
    step_index: int
    severity: str  # "error" | "warning" | "info"
    issue_type: str  # "order", "dependency", "precondition", "logic", "performance"
    title: str
    description: str
    suggestion: Optional[str] = None
    affected_steps: List[int] = Field(default_factory=list)


class StepValidationResult(BaseModel):
    is_valid: bool
    issues: List[StepValidationIssue] = Field(default_factory=list)
    corrected_steps: Optional[List[Dict[str, Any]]] = None
    corrected_order: Optional[List[int]] = None
    confidence_score: float = 1.0  # 0.0 to 1.0
    validation_notes: str = ""


STEP_VALIDATION_SYSTEM_PROMPT = """You are NEXUS Step Validator.
Analyze a workflow's steps for logical order, dependencies, and execution feasibility.

Check for:
1. ORDER ISSUES: Steps that should happen before others (e.g., navigate before click)
2. DEPENDENCY ISSUES: Steps that depend on previous steps' outcomes
3. PRECONDITION FAILURES: Steps that require elements/states that don't exist yet
4. LOGIC ERRORS: Contradictory actions (e.g., navigate away then interact with previous page)
5. PERFORMANCE: Unnecessary waits or redundant steps

For each issue found, provide:
- step_index: 0-based index of problematic step
- severity: "error" (breaks execution), "warning" (may fail), "info" (optimization)
- issue_type: category of issue
- title: short title
- description: detailed explanation
- suggestion: how to fix it
- affected_steps: indices of related steps

Repairs must be evidence-based:
- Use the complete sequence, workflow intent, observed URLs, and selectors together to infer the intended route.
- If recorded steps are clearly out of order, return corrected_order as a permutation of the supplied step_index values.
- Never invent a click, typed value, URL, selector, or completion action. Only reorder recorded steps.
- If a required interaction or selector is absent, report an error and leave corrected_order null.

Respond ONLY with valid JSON:
{
  "is_valid": true/false,
  "issues": [
    {
      "step_index": 0,
      "severity": "error",
      "issue_type": "order",
      "title": "Click before navigate",
      "description": "Step 1 tries to click element but page hasn't loaded yet",
      "suggestion": "Add browser_navigate step before this click",
      "affected_steps": [0, 1]
    }
  ],
    "corrected_order": null or [1, 0, 2],
  "confidence_score": 0.95,
  "validation_notes": "Workflow is mostly valid but has 1 critical ordering issue"
}"""


class StepValidator:
    async def validate_steps(
        self,
        steps: List[Dict[str, Any]],
        prompt_intent: Optional[str] = None,
        auto_fix: bool = False,
    ) -> StepValidationResult:
        """
        Validate compiled steps for logical order and dependencies.
        
        Args:
            steps: List of compiled step dictionaries
            prompt_intent: Original user intent for context
            auto_fix: If True, attempt to reorder steps automatically
            
        Returns:
            StepValidationResult with issues and optional corrected steps
        """
        if not steps:
            return StepValidationResult(
                is_valid=True,
                issues=[],
                confidence_score=1.0,
                validation_notes="Empty workflow - no validation needed",
            )

        try:
            # First pass: heuristic validation (fast, no AI)
            heuristic_issues = self._heuristic_validate(steps)

            if len(steps) == 1 and not heuristic_issues:
                return StepValidationResult(
                    is_valid=True,
                    issues=[],
                    confidence_score=1.0,
                    validation_notes="Single valid step",
                )
            
            # If heuristic found critical issues, use AI for detailed analysis
            if heuristic_issues or len(steps) > 3:
                ai_result = await self._ai_validate_steps(steps, prompt_intent)
                
                # Merge heuristic and AI results
                corrected = None
                corrected_order = ai_result.corrected_order
                if (
                    auto_fix
                    and isinstance(corrected_order, list)
                    and len(corrected_order) == len(steps)
                    and sorted(corrected_order) == list(range(len(steps)))
                ):
                    corrected = [steps[index] for index in corrected_order]

                remaining_heuristic_issues = self._heuristic_validate(corrected) if corrected else heuristic_issues
                ai_issues = [
                    issue for issue in ai_result.issues
                    if not (corrected and issue.issue_type == "order")
                ]
                unique_issues = self._deduplicate_issues(remaining_heuristic_issues + ai_issues)
                is_valid = not any(issue.severity == "error" for issue in unique_issues)
                
                return StepValidationResult(
                    is_valid=is_valid,
                    issues=unique_issues,
                    corrected_steps=corrected,
                    corrected_order=corrected_order,
                    confidence_score=ai_result.confidence_score,
                    validation_notes=ai_result.validation_notes,
                )
            else:
                # For short workflows, heuristic validation is sufficient
                is_valid = not any(issue.severity == "error" for issue in heuristic_issues)
                return StepValidationResult(
                    is_valid=is_valid,
                    issues=heuristic_issues,
                    confidence_score=0.85,
                    validation_notes="Heuristic validation only (short workflow)",
                )

        except Exception as e:
            logger.warning(f"Step validation failed: {e}")
            return StepValidationResult(
                is_valid=True,  # Assume valid if validation fails
                issues=[],
                confidence_score=0.0,
                validation_notes=f"Validation error: {str(e)}",
            )

    def _heuristic_validate(self, steps: List[Dict[str, Any]]) -> List[StepValidationIssue]:
        """Fast heuristic validation without AI."""
        issues: List[StepValidationIssue] = []
        
        # Track state
        current_url: Optional[str] = None
        visible_elements: set[str] = set()
        
        for idx, step in enumerate(steps):
            action_type = step.get("action_type", "").lower()
            url = step.get("url")
            selector = step.get("selector_bundle") or {}
            
            # Reusable browser workflows must establish a route before interacting.
            if action_type in ("browser_click", "browser_type", "browser_select") and not current_url:
                issues.append(
                    StepValidationIssue(
                        step_index=idx,
                        severity="error",
                        issue_type="order",
                        title="Interaction before page navigation",
                        description=f"Step {idx + 1} tries to {action_type} before a recorded page navigation",
                        suggestion="Move a recorded navigation for the target site before this interaction, or re-record the starting route",
                        affected_steps=[idx],
                    )
                )

            selector_fields = ("testId", "ariaLabel", "role", "name", "id", "cssPath", "xpath", "textAnchor")
            if action_type in ("browser_click", "browser_type", "browser_select") and not any(selector.get(field) for field in selector_fields):
                issues.append(
                    StepValidationIssue(
                        step_index=idx,
                        severity="error",
                        issue_type="precondition",
                        title="Missing recorded selector",
                        description=f"Step {idx + 1} ({action_type}) has no selector from the recording",
                        suggestion="Re-record this interaction; the compiler cannot safely invent its target selector",
                        affected_steps=[idx],
                    )
                )
            
            # Issue 2: Click on element that was never visible
            if action_type == "browser_click":
                selector_id = selector.get("testId") or selector.get("id") or selector.get("ariaLabel")
                if selector_id and selector_id not in visible_elements:
                    issues.append(
                        StepValidationIssue(
                            step_index=idx,
                            severity="warning",
                            issue_type="precondition",
                            title="Element may not be visible",
                            description=f"Step {idx} clicks element '{selector_id}' but it hasn't been confirmed visible",
                            suggestion="Ensure element is loaded and visible before clicking",
                            affected_steps=[idx],
                        )
                    )
            
            # Issue 3: Type in field that doesn't exist
            if action_type == "browser_type":
                selector_id = selector.get("testId") or selector.get("id") or selector.get("ariaLabel")
                if selector_id and selector_id not in visible_elements:
                    issues.append(
                        StepValidationIssue(
                            step_index=idx,
                            severity="warning",
                            issue_type="precondition",
                            title="Input field may not exist",
                            description=f"Step {idx} types in field '{selector_id}' but field hasn't been confirmed visible",
                            suggestion="Ensure input field is loaded before typing",
                            affected_steps=[idx],
                        )
                    )
            
            # Issue 4: Navigate away then interact with previous page
            if action_type == "browser_navigate" and current_url and url and current_url != url:
                # Check if any following steps interact with previous page
                for future_idx in range(idx + 1, len(steps)):
                    future_step = steps[future_idx]
                    future_action = future_step.get("action_type", "").lower()
                    if future_action in ("browser_click", "browser_type"):
                        # This is a warning, not an error, as page might have similar elements
                        issues.append(
                            StepValidationIssue(
                                step_index=future_idx,
                                severity="warning",
                                issue_type="logic",
                                title="Interaction after navigation",
                                description=f"Step {future_idx} interacts with element after navigating away at step {idx}",
                                suggestion="Verify element exists on new page or reorder steps",
                                affected_steps=[idx, future_idx],
                            )
                        )
                        break
            
            # Update state
            if action_type == "browser_navigate" and url:
                current_url = url
                visible_elements.clear()
            
            if action_type == "browser_click":
                selector_id = selector.get("testId") or selector.get("id") or selector.get("ariaLabel")
                if selector_id:
                    visible_elements.add(selector_id)
        
        return issues

    async def _ai_validate_steps(
        self,
        steps: List[Dict[str, Any]],
        prompt_intent: Optional[str] = None,
    ) -> StepValidationResult:
        """Use AI to validate step order and dependencies."""
        try:
            import asyncio
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch
            from langchain_core.messages import SystemMessage, HumanMessage

            step_context = []
            for idx, step in enumerate(steps):
                step_context.append({
                    "step_index": idx,
                    "title": step.get("title"),
                    "action_type": step.get("action_type"),
                    "execution_engine": step.get("execution_engine"),
                    "url": step.get("url"),
                    "selector_bundle": step.get("selector_bundle"),
                    "parameter_references": step.get("parameter_references", []),
                })
            user_prompt = (
                f"Workflow Intent: {prompt_intent or 'Automated Task'}\n\n"
                f"Recorded steps in observed order:\n{json.dumps(step_context, separators=(',', ':'))}\n\n"
                "Analyze the whole route and step dependencies. Use URLs and selector bundles as evidence. "
                "Return corrected_order only when a permutation of these exact indexes repairs the route. "
                "Do not synthesize or alter steps, URLs, values, or selectors."
            )

            logger.info(
                "[StepValidator] 🔍 Starting AI validation for %d steps (intent: '%s')...",
                len(steps),
                prompt_intent or "Workflow",
            )

            # 4s timeout for AI validation
            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [
                        SystemMessage(content=STEP_VALIDATION_SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ],
                    operation="fast",
                    temperature=0.1,
                    max_attempts=1,
                    per_attempt_timeout=3.0,
                    max_tokens=800,
                ),
                timeout=4.5,
            )

            content = res.content if hasattr(res, "content") else str(res)
            cleaned_json = content.strip()
            if "```" in cleaned_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
                if match:
                    cleaned_json = match.group(1).strip()

            parsed = json.loads(cleaned_json)
            
            # Parse issues
            issues: List[StepValidationIssue] = []
            for issue_data in parsed.get("issues", []):
                try:
                    issue = StepValidationIssue(
                        step_index=issue_data.get("step_index", 0),
                        severity=issue_data.get("severity", "info"),
                        issue_type=issue_data.get("issue_type", "logic"),
                        title=issue_data.get("title", "Unknown issue"),
                        description=issue_data.get("description", ""),
                        suggestion=issue_data.get("suggestion"),
                        affected_steps=issue_data.get("affected_steps", []),
                    )
                    issues.append(issue)
                except Exception as e:
                    logger.warning(f"Failed to parse issue: {e}")

            is_valid = parsed.get("is_valid", True)
            confidence = parsed.get("confidence_score", 0.8)
            notes = parsed.get("validation_notes", "")

            logger.info(
                "[StepValidator] ✅ AI validation complete: %d issues found, confidence: %.2f",
                len(issues),
                confidence,
            )

            return StepValidationResult(
                is_valid=is_valid,
                issues=issues,
                corrected_order=parsed.get("corrected_order"),
                confidence_score=confidence,
                validation_notes=notes,
            )

        except asyncio.TimeoutError:
            logger.warning("[StepValidator] AI validation timed out, using heuristic only")
            return StepValidationResult(
                is_valid=True,
                issues=[],
                confidence_score=0.5,
                validation_notes="AI validation timed out",
            )
        except Exception as e:
            logger.warning(f"[StepValidator] AI validation failed: {e}")
            return StepValidationResult(
                is_valid=True,
                issues=[],
                confidence_score=0.0,
                validation_notes=f"Validation error: {str(e)}",
            )

    def _deduplicate_issues(self, issues: List[StepValidationIssue]) -> List[StepValidationIssue]:
        """Remove duplicate issues, keeping the most severe."""
        seen: Dict[Tuple[int, str], StepValidationIssue] = {}
        severity_rank = {"error": 3, "warning": 2, "info": 1}
        
        for issue in issues:
            key = (issue.step_index, issue.issue_type)
            if key not in seen:
                seen[key] = issue
            else:
                # Keep the more severe issue
                if severity_rank.get(issue.severity, 0) > severity_rank.get(seen[key].severity, 0):
                    seen[key] = issue
        
        return sorted(seen.values(), key=lambda x: x.step_index)


validator = StepValidator()
