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
    validated_steps: Optional[List[Dict[str, Any]]] = None
    optimizations_applied: List[str] = Field(default_factory=list)
    confidence_score: float = 1.0  # 0.0 to 1.0
    validation_notes: str = ""


STEP_VALIDATION_SYSTEM_PROMPT = """You are NEXUS Step Validator & Workflow Optimizer.
Analyze a demonstrated workflow's steps for logical causality, execution feasibility, and optimal order.

You will receive the recorded sequence of steps including:
- step_index: original 0-based index
- title: step title
- action_type: browser_navigate | browser_click | browser_type | browser_select | etc.
- url: target URL
- selector_bundle: recorded selectors & attributes
- vlm_features: rich visual features extracted from interaction snapshots (visual_role, semantic_label, visual_landmark, visual_context, expected_effect)
- value: parameters or text entered

Validation & Optimization Tasks:
1. ORDERING & CAUSALITY:
   - Ensure browser_navigate to the destination site/app is strictly at step 0.
   - For form/survey creation: establishing form title / metadata MUST precede creating questions.
   - For interactive elements: clicking to focus an input or button MUST precede typing into it.
   - Selecting dropdown options must follow clicking/opening the dropdown.
   - Save / Submit / Send actions must happen AFTER all fields are populated.
2. NOISE & JITTER REDUCTION:
   - Identify rapid accidental double clicks on the same element and consolidate them.
   - Flag clicks on blank background canvas or decorative non-functional elements that do not change state.
3. PARAMETER & SELECTOR ROBUSTNESS:
   - Verify each interactive step has reliable selectors and/or VLM semantic landmarks.
   - Ensure parameter templates ({{param}}) match the intended data flow.

Repair Instructions:
- If recorded steps are out of order, return "corrected_order" as a permutation of the supplied step_index values (e.g. [0, 1, 3, 2, 4]).
- List all optimizations performed in "optimizations_applied".
- For any remaining warnings, detail them in "issues".

Respond ONLY with valid JSON:
{
  "is_valid": true/false,
  "corrected_order": [0, 1, 2, ...],
  "optimizations_applied": [
    "Reordered navigation to step 0",
    "Ordered form title before question generation"
  ],
  "issues": [
    {
      "step_index": 0,
      "severity": "info" | "warning" | "error",
      "issue_type": "order" | "dependency" | "logic" | "performance",
      "title": "Short title",
      "description": "Explanation",
      "suggestion": "Recommendation"
    }
  ],
  "confidence_score": 0.98,
  "validation_notes": "Summary of workflow validation state"
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
                    validated_steps=steps,
                    confidence_score=1.0,
                    validation_notes="Single valid step",
                )
            
            # If heuristic found critical issues or workflow has multiple steps, use AI for deep analysis & reordering
            if heuristic_issues or len(steps) >= 2:
                ai_result = await self._ai_validate_steps(steps, prompt_intent)
                
                # Merge heuristic and AI results
                corrected = None
                corrected_order = ai_result.corrected_order
                optimizations = list(ai_result.optimizations_applied or [])

                if auto_fix:
                    if (
                        isinstance(corrected_order, list)
                        and len(corrected_order) == len(steps)
                        and sorted(corrected_order) == list(range(len(steps)))
                    ):
                        reordered_by_ai = [steps[index] for index in corrected_order]
                        if reordered_by_ai != steps and not any("reorder" in str(opt).lower() for opt in optimizations):
                            optimizations.append(f"AI reordered {len(steps)} steps into logical causal sequence")
                        corrected = self._heuristic_auto_fix(reordered_by_ai) or reordered_by_ai
                    else:
                        corrected = self._heuristic_auto_fix(steps)
                        if corrected:
                            optimizations.append("Auto-repaired step order (normalized route to step 0)")

                    if not corrected:
                        corrected = self._heuristic_auto_fix(steps)

                final_steps = corrected or steps

                remaining_heuristic_issues = self._heuristic_validate(final_steps)
                ai_issues = [
                    issue for issue in ai_result.issues
                    if not (corrected and issue.issue_type == "order")
                ]
                unique_issues = self._deduplicate_issues(remaining_heuristic_issues + ai_issues)
                if corrected:
                    # Filter out any order issues that were successfully auto-fixed by reordering
                    unique_issues = [iss for iss in unique_issues if iss.issue_type != "order"]
                is_valid = not any(issue.severity == "error" for issue in unique_issues)
                
                return StepValidationResult(
                    is_valid=is_valid,
                    issues=unique_issues,
                    corrected_steps=corrected,
                    corrected_order=corrected_order,
                    validated_steps=final_steps,
                    optimizations_applied=optimizations,
                    confidence_score=ai_result.confidence_score,
                    validation_notes=ai_result.validation_notes or ("Steps validated and optimized" if is_valid else "Steps have potential issues"),
                )
            else:
                corrected = self._heuristic_auto_fix(steps) if auto_fix else None
                remaining_issues = self._heuristic_validate(corrected) if corrected else heuristic_issues
                if corrected:
                    remaining_issues = [iss for iss in remaining_issues if iss.issue_type != "order"]
                is_valid = not any(issue.severity == "error" for issue in remaining_issues)
                return StepValidationResult(
                    is_valid=is_valid,
                    issues=remaining_issues,
                    corrected_steps=corrected,
                    validated_steps=corrected or steps,
                    optimizations_applied=["Auto-repaired step order"] if corrected else [],
                    confidence_score=0.95,
                    validation_notes="Validated with automated order repair",
                )

        except Exception as e:
            logger.warning(f"Step validation failed: {e}")
            return StepValidationResult(
                is_valid=True,  # Assume valid if validation fails
                issues=[],
                confidence_score=0.0,
                validation_notes=f"Validation error: {str(e)}",
            )

    def _heuristic_auto_fix(self, steps: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Auto-repair obvious recorded order anomalies (e.g. navigation recorded after first interaction)."""
        if not steps:
            return None

        reordered = list(steps)
        changed = False

        # Case 1: Move navigation step to index 0 if it's anywhere else
        nav_idx = -1
        for idx, s in enumerate(reordered):
            if s.get("action_type") == "browser_navigate":
                nav_idx = idx
                break

        if nav_idx > 0:
            nav_step = reordered.pop(nav_idx)
            reordered.insert(0, nav_step)
            changed = True
            logger.info("[StepValidator] Heuristically auto-fixed order: moved navigation step %d to index 0", nav_idx)
        elif nav_idx == -1:
            # Case 2: No navigation step recorded -> synthesize navigation to target URL at index 0
            target_url = None
            for step in reordered:
                u = step.get("url") or (step.get("metadata") or {}).get("url")
                if u and (u.startswith("http://") or u.startswith("https://")):
                    target_url = u
                    break
            if target_url:
                from urllib.parse import urlparse
                import uuid
                domain = urlparse(target_url).netloc
                nav_step = {
                    "step_id": f"step-{uuid.uuid4().hex[:6]}",
                    "title": f"Open {domain or 'Target Site'}",
                    "action_type": "browser_navigate",
                    "execution_engine": "browser",
                    "url": target_url,
                    "preconditions": [],
                    "postconditions": [{"check_type": "url_contains", "target": domain}] if domain else [],
                }
                reordered.insert(0, nav_step)
                changed = True
                logger.info("[StepValidator] Auto-repaired missing route: prepended browser navigation to %s", target_url)

        # Case 3: Prune consecutive duplicate clicks (user click jitter)
        pruned = []
        for s in reordered:
            if pruned:
                prev = pruned[-1]
                if (
                    prev.get("action_type") == s.get("action_type") == "browser_click"
                    and (
                        (prev.get("selector_bundle") or {}).get("cssPath") == (s.get("selector_bundle") or {}).get("cssPath")
                        or prev.get("title") == s.get("title")
                    )
                ):
                    changed = True
                    continue
            pruned.append(s)
        reordered = pruned

        return reordered if changed else None

    def _heuristic_validate(self, steps: List[Dict[str, Any]]) -> List[StepValidationIssue]:
        """Fast heuristic validation without AI."""
        issues: List[StepValidationIssue] = []
        
        # Track state
        current_url: Optional[str] = None
        
        for idx, step in enumerate(steps):
            action_type = step.get("action_type", "").lower()
            url = step.get("url")
            selector = step.get("selector_bundle") or {}
            meta = step.get("metadata") or {}
            vlm = meta.get("vlm_features") or step.get("vlm_features") or selector.get("vlm_features") or {}
            has_vlm = bool(vlm.get("semantic_label") or vlm.get("visual_role") or vlm.get("visual_landmark"))

            # Reusable browser workflows must establish a route before interacting.
            if action_type in ("browser_click", "browser_type", "browser_select") and not current_url and idx == 0:
                issues.append(
                    StepValidationIssue(
                        step_index=idx,
                        severity="warning",
                        issue_type="order",
                        title="Interaction before page navigation",
                        description=f"Workflow starts with {action_type} before a recorded page navigation",
                        suggestion="Auto-repair will prepend a navigation step to establish the starting page route",
                        affected_steps=[idx],
                    )
                )

            selector_fields = ("testId", "ariaLabel", "role", "name", "id", "cssPath", "xpath", "textAnchor", "placeholder", "tag")
            has_valid_selector = has_vlm or any(selector.get(field) for field in selector_fields) or bool(step.get("selector")) or bool(step.get("target_element"))
            if action_type in ("browser_click", "browser_type", "browser_select") and not has_valid_selector:
                issues.append(
                    StepValidationIssue(
                        step_index=idx,
                        severity="warning",
                        issue_type="precondition",
                        title="Missing recorded selector",
                        description=f"Step {idx + 1} ({action_type}) has minimal selector data from recording",
                        suggestion="Verify this element exists or re-record this interaction if needed",
                        affected_steps=[idx],
                    )
                )
            
            # Navigate away then interact with previous page
            if action_type == "browser_navigate" and current_url and url and current_url != url:
                for future_idx in range(idx + 1, len(steps)):
                    future_step = steps[future_idx]
                    future_action = future_step.get("action_type", "").lower()
                    if future_action in ("browser_click", "browser_type"):
                        issues.append(
                            StepValidationIssue(
                                step_index=future_idx,
                                severity="warning",
                                issue_type="logic",
                                title="Interaction after navigation",
                                description=f"Step {future_idx + 1} interacts with element after navigating away at step {idx + 1}",
                                suggestion="Verify element exists on new page or reorder steps",
                                affected_steps=[idx, future_idx],
                            )
                        )
                        break
            
            # Update state
            if action_type == "browser_navigate" and url:
                current_url = url
        
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
                meta = step.get("metadata") or {}
                vlm = meta.get("vlm_features") or step.get("vlm_features") or {}
                val = step.get("value_template") or step.get("value")
                step_context.append({
                    "step_index": idx,
                    "title": step.get("title"),
                    "action_type": step.get("action_type"),
                    "execution_engine": step.get("execution_engine"),
                    "url": step.get("url"),
                    "value": str(val)[:80] if val else None,
                    "selector_bundle": step.get("selector_bundle"),
                    "vlm_features": vlm,
                    "parameter_references": step.get("parameter_references", []),
                })
            user_prompt = (
                f"Workflow Intent: {prompt_intent or 'Automated Task'}\n\n"
                f"Recorded steps with visual & DOM context:\n{json.dumps(step_context, separators=(',', ':'))}\n\n"
                "Analyze the whole workflow sequence, causality, and step dependencies. Use URLs, selector bundles, and VLM visual features as evidence. "
                "Return corrected_order as an optimal permutation of step indexes to achieve the workflow intent without bugs. "
                "List all optimizations applied."
            )

            logger.info(
                "[StepValidator] 🔍 Starting AI validation for %d steps (intent: '%s')...",
                len(steps),
                prompt_intent or "Workflow",
            )

            # Generous budget for complete workflow step validation
            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [
                        SystemMessage(content=STEP_VALIDATION_SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ],
                    operation="fast",
                    temperature=0.1,
                    max_attempts=2,
                    per_attempt_timeout=5.5,
                    max_tokens=2000,
                ),
                timeout=12.0,
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
            optimizations = parsed.get("optimizations_applied", [])

            logger.info(
                "[StepValidator] ✅ AI validation complete: %d issues found, %d optimizations, confidence: %.2f",
                len(issues),
                len(optimizations),
                confidence,
            )

            return StepValidationResult(
                is_valid=is_valid,
                issues=issues,
                corrected_order=parsed.get("corrected_order"),
                optimizations_applied=optimizations,
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
