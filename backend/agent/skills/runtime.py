"""
Skill Execution Runtime for NEXUS.
Converts compiled semantic actions into executable PlanSteps with parameter bindings.
Manages step-level checkpoints, selector fallback cascades, precondition probes,
idempotency guards, and cross-engine file handoff checks.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.state import PlanStep
from backend.agent.skills.matcher import MatchResult
from backend.database.repositories.skill_repo import SkillRepository
from backend.core.policies import RiskLevel

logger = logging.getLogger("nexus.skills.runtime")


class SkillRuntime:
    @staticmethod
    def _escape_ps_string(value: str) -> str:
        """Escape a value for safe embedding inside a PowerShell single-quoted string.
        Single quotes are the only character that needs escaping in PS single-quoted strings
        (doubled: ' → '').
        """
        return value.replace("'", "''")

    def substitute_parameters(self, text: Optional[str], params: dict[str, str]) -> Optional[str]:
        """Replace mustache {{param_name}} tokens with runtime resolved parameter values.
        Logs a warning for any tokens that remain unresolved after substitution so they
        surface early rather than being silently passed to browser / shell tools.
        """
        if not text:
            return text
        result = text
        for k, v in params.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        # Detect any remaining unresolved tokens and warn
        leftover = re.findall(r"\{\{([^}]+)\}\}", result)
        if leftover:
            logger.warning(
                "[SkillRuntime] Unresolved parameter token(s) after substitution: %s — "
                "value will be passed literally to the tool.",
                leftover,
            )
        return result

    def validate_match(self, match: MatchResult) -> tuple[bool, str]:
        """
        Gate check: verify matched skill is in a state safe for replay.
        Returns (can_execute, reason_if_blocked).
        """
        skill = match.skill
        if getattr(skill, "health_status", "healthy") == "suspended":
            return False, (
                f"Skill '{skill.name}' is currently suspended due to repeated failures. "
                "Please repair or re-demonstrate this workflow before running it again."
            )
        if not getattr(skill, "is_active", True):
            return False, f"Skill '{skill.name}' is inactive. Re-activate it from the Skills Library first."
        if not match.version or not match.version.steps_json:
            return False, f"Skill '{skill.name}' has no compiled steps. Please re-demonstrate."
        selector_fields = ("testId", "ariaLabel", "id", "cssPath", "xpath", "textAnchor")
        for index, step in enumerate(match.version.steps_json):
            if step.get("action_type") not in ("browser_click", "browser_type", "browser_select"):
                continue
            bundle = step.get("selector_bundle") or {}
            has_bundle = isinstance(bundle, dict) and any(bundle.get(field) for field in selector_fields)
            has_direct = bool(step.get("selector") or step.get("xpath") or step.get("text") or step.get("textAnchor"))
            has_title_target = bool(step.get("title"))
            has_subsequent_nav = any(
                s.get("action_type") == "browser_navigate" for s in match.version.steps_json[index + 1:]
            )
            if not has_bundle and not has_direct and not has_title_target and not has_subsequent_nav:
                return False, (
                    f"Skill '{skill.name}' step {index + 1} has no recorded browser selector. "
                    "This recipe cannot be replayed safely; re-teach it and confirm the captured selectors before saving."
                )
        return True, ""

    def _build_selector_args(self, selector_bundle: dict, step: Optional[dict] = None) -> dict:
        """Return best available selector with full fallback bundle attached."""
        bundle = selector_bundle or {}
        st = step or {}
        primary = (
            bundle.get("testId")
            or bundle.get("ariaLabel")
            or bundle.get("id")
            or bundle.get("cssPath")
            or bundle.get("xpath")
            or st.get("selector")
            or st.get("xpath")
        )
        text = bundle.get("textAnchor") or st.get("text") or st.get("textAnchor")
        if not text and st.get("title"):
            m = re.search(r"['\"]([^'\"]+)['\"]", st.get("title", ""))
            if m:
                text = m.group(1)
        if not primary and text:
            primary = f"text={text}" if text.lower() != "button" else "button"

        meta = st.get("metadata") or {}
        vlm_feat = meta.get("vlm_features") or st.get("vlm_features") or bundle.get("vlm_features") or {}
        if not text and vlm_feat.get("semantic_label"):
            text = vlm_feat["semantic_label"]

        return {
            "selector": primary,
            "xpath": bundle.get("xpath") or st.get("xpath"),
            "text": text,
            "selector_bundle": bundle,
            "vlm_features": vlm_feat,
        }

    def generate_plan_steps(self, match: MatchResult) -> list[PlanStep]:
        """
        Translate compiled skill steps into standard NEXUS PlanStep sequence with:
        - Parameter substitution via mustache templates
        - Follow-up prompts for any missing required parameters
        - Full coverage of all SemanticAction types
        - Suspended/inactive skill gate
        """
        # --- Gate: suspended or inactive skills must not auto-replay ---
        can_run, reason = self.validate_match(match)
        if not can_run:
            return [{
                "id": f"skill-blocked-{uuid.uuid4().hex[:6]}",
                "title": f"Skill Blocked: {match.skill.name}",
                "description": reason,
                "tool": "ai_response",
                "args": {"answer": f"\u26a0\ufe0f {reason}"},
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            }]

        steps: list[PlanStep] = []
        raw_steps = match.version.steps_json or []
        params = match.resolved_parameters.copy()
        missing = list(match.missing_parameters or [])

        # Older or AI-distilled skills may contain a template token without a
        # matching schema entry. Collect it instead of sending literal braces
        # to a browser or desktop tool.
        referenced_names: set[str] = set()
        for step in raw_steps:
            for value in (step.get("title"), step.get("value_template"), step.get("value"), step.get("url")):
                if isinstance(value, str):
                    referenced_names.update(re.findall(r"\{\{([^}]+)\}\}", value))
            references = step.get("parameter_references") or []
            if isinstance(references, list):
                referenced_names.update(str(name) for name in references if name)
        for name in referenced_names:
            if name not in params and name not in missing:
                missing.append(name)
        
        # Priority: Use values from user prompt first, then ask for missing
        # This ensures if user said "send email to with subject 'Meeting'",
        # we extract those values and only ask for what's missing (body)

        # Build schema map for context-aware follow-up prompts
        schema_map: dict[str, dict] = {}
        is_form_skill = any(w in (match.skill.name or "").lower() for w in ("form", "survey", "questionnaire", "quiz", "gform"))
        for p in (match.skill.parameters_schema or []):
            if isinstance(p, dict):
                p_name_lower = p.get("name", "").strip().lower()
                schema_map[p_name_lower] = p
                is_req = p.get("required", False)
                is_key_param = p_name_lower in ("form_title", "survey_title", "title", "fields", "form_fields", "questions", "question_1", "recipient_email", "to_email")
                if p_name_lower and p_name_lower not in params and p_name_lower not in missing:
                    if is_req or (is_form_skill and is_key_param):
                        missing.append(p_name_lower)
            elif hasattr(p, "name"):
                p_name_lower = p.name.strip().lower()
                schema_map[p_name_lower] = {
                    "name": p.name,
                    "type": getattr(p, "type", "string"),
                    "description": getattr(p, "description", ""),
                    "required": getattr(p, "required", True),
                    "default_value": getattr(p, "default_value", None),
                }
                is_req = getattr(p, "required", False)
                is_key_param = p_name_lower in ("form_title", "survey_title", "title", "fields", "form_fields", "questions", "question_1", "recipient_email", "to_email")
                if p_name_lower and p_name_lower not in params and p_name_lower not in missing:
                    if is_req or (is_form_skill and is_key_param):
                        missing.append(p_name_lower)

        # --- 1. Parameter collection steps for missing required values ---
        for p_name in missing:
            p_info = schema_map.get(p_name.lower(), {})
            p_desc = p_info.get("description") or p_name.replace("_", " ")
            p_type = p_info.get("type", "string")
            opts: list[str] = []

            if p_name in ("recipient_email", "to_email", "email"):
                prompt_q = "Who would you like to send this email to?"
                placeholder_txt = "e.g. colleague@example.com"
                opts = ["colleague@example.com", "team@example.com"]
            elif p_name in ("subject", "email_subject"):
                prompt_q = "What should the subject be?"
                placeholder_txt = "e.g. Project Status Update"
                opts = ["Project Status Update", "Meeting Notes & Next Steps", "Quick Question"]
            elif p_name in ("form_title", "survey_title", "title"):
                prompt_q = "What title would you like for this form?"
                placeholder_txt = "e.g. Customer Feedback Survey"
                opts = ["Customer Feedback Survey", "Event Registration", "Contact Information", "Team Feedback Form"]
            elif p_name in ("question_1", "first_question", "question", "question_title"):
                prompt_q = "What question would you like to add?"
                placeholder_txt = "e.g. How satisfied are you with our service?"
                opts = ["Full Name", "Email Address", "How satisfied are you with our service?"]
            elif p_name in ("question_2", "second_question"):
                prompt_q = "What is the second question you would like to add?"
                placeholder_txt = "e.g. Any additional comments or feedback?"
                opts = ["Phone Number", "Any additional comments or feedback?", "Rate our service (1-5)"]
            elif p_name in ("question_3", "third_question"):
                prompt_q = "What is the next question?"
                placeholder_txt = "e.g. Your contact email"
                opts = ["Comments / Suggestions", "Preferred Contact Method"]
            elif p_name in ("fields", "form_fields", "questions"):
                prompt_q = "What questions or fields would you like on this form?"
                placeholder_txt = "e.g. Name, Email, Feedback"
                opts = ["Name, Email, Feedback", "Name, Phone Number, Comments", "Event RSVP: Name, Email, Attendance"]
            elif p_name in ("body", "message", "content", "email_body"):
                prompt_q = "What message would you like to send?"
                placeholder_txt = "e.g. Hi team, here’s the update…"
                opts = ["Hi team, here is the latest update.", "Quick follow up regarding our discussion.", "Please find the attached details."]
            elif p_name in ("search_query", "query", "search_term"):
                prompt_q = "What would you like to search for?"
                placeholder_txt = "Type search terms\u2026"
                opts = []
            elif p_name in ("target_date", "date", "month", "billing_month"):
                prompt_q = "What date should this workflow use?"
                placeholder_txt = "e.g. March 2026 or 2026-03-28"
                opts = ["Today", "Tomorrow", "End of this week"]
            elif p_type == "filepath":
                prompt_q = f"Please specify the file path for: {p_desc}"
                placeholder_txt = r"e.g. C:\Users\you\Documents\file.xlsx"
                opts = ["Desktop", "Documents", "Downloads", "Browse..."]
            elif p_type == "number":
                prompt_q = f"Please enter the {p_desc}:"
                placeholder_txt = "e.g. 42"
                opts = ["1", "5", "10", "100"]
            else:
                prompt_q = f"Please enter the {p_name.replace('_', ' ')}:"
                placeholder_txt = f"e.g. {p_desc}"
                opts = []

            # Include demonstrated default value as first clickable chip option if present
            def_opt = str(p_info.get("default_value") or "").strip()
            if def_opt and def_opt not in opts and not def_opt.startswith("{{"):
                opts.insert(0, def_opt)

            steps.append({
                "id": f"skill-input-{p_name}-{uuid.uuid4().hex[:4]}",
                "title": f"Required: {p_name.replace('_', ' ').title()}",
                "description": prompt_q,
                "tool": "ask_user",
                "args": {
                    "prompt": prompt_q,
                    "options": opts,
                    "placeholder": placeholder_txt,
                    "parameter_name": p_name,
                    "parameter_type": p_type,
                    "skill_name": match.skill.name,
                },
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })

        # --- 2. Skill workflow steps with full action type coverage ---
        for idx, s in enumerate(raw_steps):
            action_type = s.get("action_type", "")
            engine = s.get("execution_engine", "browser")
            title_raw = s.get("title", f"Step {idx + 1}")
            title = self.substitute_parameters(title_raw, params) or title_raw
            val = self.substitute_parameters(s.get("value_template") or s.get("value"), params)
            url_val = self.substitute_parameters(s.get("url"), params)
            selector_bundle: dict = s.get("selector_bundle") or {}
            metadata: dict = s.get("metadata") or {}
            target_app = s.get("target_app")

            tool_name = "ai_response"
            args: dict[str, Any] = {}
            risk = RiskLevel.SAFE.value

            # ─── Browser Engine ───────────────────────────────────────────
            if action_type == "browser_navigate":
                tool_name = "browser_navigate"
                nav_url = url_val or val  # prefer explicit url field
                args = {"url": nav_url}

            elif action_type == "browser_click":
                tool_name = "browser_click"
                args = self._build_selector_args(selector_bundle, s)
                if any(w in title.lower() for w in ("send", "submit", "pay", "delete", "purchase", "confirm", "remove", "buy")):
                    risk = RiskLevel.MODIFYING.value

            elif action_type == "browser_type":
                tool_name = "browser_type"
                sel_args = self._build_selector_args(selector_bundle, s)
                args = {
                    **sel_args,
                    "text": val,
                    "clear_first": metadata.get("clear_first", True),
                    "press_enter": metadata.get("press_enter", False),
                }

            elif action_type in ("browser_press", "browser_press_key"):
                tool_name = "browser_press"
                args = {
                    "key": val or metadata.get("key", "Enter"),
                    "selector": selector_bundle.get("cssPath") if selector_bundle else None,
                }

            elif action_type == "browser_select":
                tool_name = "browser_select"
                sel_args = self._build_selector_args(selector_bundle, s)
                args = {
                    "selector": sel_args.get("selector"),
                    "value": val,
                    "label": metadata.get("label"),
                    "index": metadata.get("index", -1),
                }

            elif action_type == "browser_scroll":
                tool_name = "browser_scroll"
                args = {
                    "selector": selector_bundle.get("cssPath") if selector_bundle else None,
                    "x": metadata.get("scroll_x", 0),
                    "y": metadata.get("scroll_y", 300),
                }

            elif action_type == "browser_wait":
                tool_name = "browser_wait"
                preconds = s.get("preconditions") or []
                cond = preconds[0] if preconds else {}
                args = {
                    "url_contains": cond.get("target") if cond.get("check_type") == "url_contains" else None,
                    "selector": cond.get("target") if cond.get("check_type") == "element_visible" else None,
                    "timeout_seconds": cond.get("timeout_seconds", 4.0),
                }

            # ─── Desktop Engine ──────────────────────────────────────────
            elif action_type == "desktop_focus":
                tool_name = "activate_window"
                args = {
                    "window_title": val or target_app,
                    "application": target_app,
                }
                risk = RiskLevel.MODIFYING.value

            elif action_type == "desktop_click":
                tool_name = "click_mouse"
                args = {
                    "target": selector_bundle.get("textAnchor") or title,
                    "x": metadata.get("x"),
                    "y": metadata.get("y"),
                }
                risk = RiskLevel.MODIFYING.value

            elif action_type == "desktop_type":
                tool_name = "type_text"
                args = {
                    "text": val,
                    "target": selector_bundle.get("textAnchor") if selector_bundle else None,
                }

            elif action_type == "desktop_hotkey":
                tool_name = "press_hotkey"
                keys_raw = val or metadata.get("keys", "")
                if isinstance(keys_raw, str):
                    keys = [k.strip() for k in keys_raw.split("+") if k.strip()]
                else:
                    keys = list(keys_raw)
                args = {"keys": keys}

            # ─── System / File Handoff ───────────────────────────────────
            elif action_type == "file_verify_download":
                tool_name = "run_command"
                pattern = val or metadata.get("filename_pattern", "")
                directory = metadata.get("directory", r"%USERPROFILE%\Downloads")
                # Sanitize both values against single-quote injection in the PS command
                safe_dir = self._escape_ps_string(directory)
                safe_pattern = self._escape_ps_string(pattern)
                args = {
                    "command": (
                        f"$f = Get-ChildItem '{safe_dir}' -Filter '*{safe_pattern}*' | "
                        "Where-Object {$_.Length -gt 0} | Select-Object -First 1; "
                        "if ($f) { Write-Output $f.FullName } else { Write-Error 'File not found' }"
                    )
                }

            elif action_type == "wait_condition":
                tool_name = "browser_wait"
                preconds = s.get("preconditions") or []
                cond = preconds[0] if preconds else {}
                args = {
                    "url_contains": cond.get("target") if cond.get("check_type") == "url_contains" else None,
                    "selector": cond.get("target") if cond.get("check_type") == "element_visible" else None,
                    "timeout_seconds": cond.get("timeout_seconds", 5.0),
                }

            else:
                # Unrecognized action — surface as informational with warning
                tool_name = "ai_response"
                args = {"answer": f"[Skill step: {title}] ({action_type})"}
                logger.warning("[SkillRuntime] Unhandled action_type '%s' for step '%s'", action_type, title)

            step_description = (
                f"[Skill: {match.skill.name} v{match.version.version_number}] "
                f"Step {idx + 1}/{len(raw_steps)} \u2022 {engine.upper()} \u2022 {action_type}"
            )

            steps.append({
                "id": f"skill-step-{idx + 1}-{uuid.uuid4().hex[:4]}",
                "title": title,
                "description": step_description,
                "tool": tool_name,
                "args": args,
                "risk_level": risk,
                "status": "pending",
                "result": None,
                "error": None,
            })

        logger.info(
            "[SkillRuntime] Generated %d plan steps for skill '%s' v%d (%d param prompts + %d action steps)",
            len(steps),
            match.skill.name,
            match.version.version_number,
            len(missing),
            len(raw_steps),
        )
        return steps

    async def verify_file_readiness(
        self,
        directory: str,
        filename_pattern: str,
        timeout_seconds: float = 10.0,
    ) -> Optional[str]:
        """
        Cross-engine handoff checkpoint:
        Wait for a downloaded file to exist, verify size > 0, and confirm no .crdownload or .tmp extension.
        """
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                for fname in os.listdir(directory):
                    if filename_pattern.lower() in fname.lower():
                        if not fname.endswith((".crdownload", ".tmp", ".download")):
                            fpath = os.path.join(directory, fname)
                            size1 = os.path.getsize(fpath)
                            if size1 > 0:
                                await asyncio.sleep(0.5)
                                size2 = os.path.getsize(fpath)
                                if size1 == size2:  # Size is stable
                                    return fpath
            except Exception as e:
                logger.debug(f"[SkillRuntime] File readiness check error: {e}")
            await asyncio.sleep(0.5)
        return None


runtime = SkillRuntime()
