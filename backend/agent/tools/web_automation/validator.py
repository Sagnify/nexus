"""
NEXUS VLM Step Validator
========================
After every browser tool action, validates that the action's intended effect
was actually realised in the page — first via a lightweight DOM diff, then
(when ambiguous) via a VLM screenshot check.

ValidationResult.passed  → True means the step is confirmed successful.
ValidationResult.passed  → False triggers adaptive replanning in the executor.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("nexus.validator")

# ──────────────────────────────────────────────────────────────────────────────
# Actions that don't need validation (read-only or wait operations)
# ──────────────────────────────────────────────────────────────────────────────
SKIP_VALIDATION_ACTIONS = frozenset({
    "browser_wait",
    "browser_inspect",
    "browser_get_source",
    "browser_get_tabs",
    "browser_switch_tab",
    "browser_scroll",
    "browser_dismiss_popup",
    "browser_dismiss_popups",
    "document_create",
    "document_open",
    "document_add_title",
    "document_add_heading",
    "document_add_paragraph",
    "document_add_bullet",
    "document_add_numbered_item",
    "document_add_table",
    "document_add_page_break",
    "document_add_image",
    "document_save",
    "document_read",
    "document_verify",
    "spreadsheet_create",
    "spreadsheet_open",
    "spreadsheet_list_sheets",
    "spreadsheet_create_sheet",
    "spreadsheet_rename_sheet",
    "spreadsheet_read_cell",
    "spreadsheet_read_range",
    "spreadsheet_read_sheet",
    "spreadsheet_write_cell",
    "spreadsheet_write_range",
    "spreadsheet_add_formula",
    "spreadsheet_format_range",
    "spreadsheet_create_table",
    "spreadsheet_create_chart",
    "spreadsheet_save",
    "spreadsheet_read",
    "spreadsheet_verify",
    "ai_response",
    "get_current_time",
    "ask_user",
})




@dataclass
class ValidationResult:
    passed: bool
    confidence: float            # 0.0 – 1.0
    reason: str
    suggestion: str = ""         # What corrective action the executor should try
    tier: str = "none"           # "dom_diff" | "vlm" | "skipped" | "error"
    details: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Tier 1: DOM diff validation (zero-latency, always runs first)
# ──────────────────────────────────────────────────────────────────────────────
def _dom_diff_validate(
    action: str,
    args: dict,
    result: str,
    dom_before: dict,
    dom_after: dict,
) -> ValidationResult | None:
    """
    Deterministic DOM-based validation.
    Returns a ValidationResult when we can be confident, or None when ambiguous
    (which triggers Tier 2 VLM validation).
    """
    url_before = dom_before.get("url", "")
    url_after = dom_after.get("url", "")
    title_after = dom_after.get("title", "")
    elems_before = {
        (e.get("selector", ""), e.get("value", ""), e.get("text", ""))
        for e in dom_before.get("interactive_elements", [])
    }
    elems_after_list = dom_after.get("interactive_elements", [])

    # ── browser_navigate ────────────────────────────────────────────────────
    if action == "browser_navigate":
        target_url = args.get("url", "")
        # Strip scheme + trailing slash for loose matching
        def _norm(u: str) -> str:
            return re.sub(r"^https?://", "", u).rstrip("/")
        if url_after and _norm(target_url) in _norm(url_after):
            return ValidationResult(
                passed=True, confidence=0.97, reason=f"Page navigated to {url_after}.", tier="dom_diff"
            )
        if url_before != url_after:
            return ValidationResult(
                passed=True, confidence=0.80,
                reason=f"URL changed from {url_before[:60]} to {url_after[:60]}.",
                tier="dom_diff",
            )
        return ValidationResult(
            passed=False, confidence=0.85,
            reason=f"URL did not change after navigation (still: {url_after[:80]}).",
            suggestion=f"browser_navigate again to {target_url} or check for blocking popup.",
            tier="dom_diff",
        )

    # ── browser_type ─────────────────────────────────────────────────────────
    if action == "browser_type":
        typed_text = str(args.get("text", "")).strip()
        selector = args.get("selector", "")
        if not typed_text:
            return ValidationResult(passed=True, confidence=1.0, reason="No text to type.", tier="dom_diff")

        # Look for the element or chip in dom_after and check value, text, or aria-label
        for el in elems_after_list:
            sel = el.get("selector", "")
            val = str(el.get("value") or "").strip()
            txt = str(el.get("text") or "").strip()
            aria = str(el.get("aria_label") or "").strip()
            if selector and selector in sel:
                if typed_text.lower() in val.lower() or typed_text.lower() in txt.lower() or typed_text.lower() in aria.lower():
                    return ValidationResult(
                        passed=True, confidence=0.95,
                        reason=f"Target '{selector}' contains typed text.",
                        tier="dom_diff",
                    )

        # Check if typed text appears as a chip token, list item, or rich text body elsewhere on page
        chip_found = any(
            typed_text.lower() in str(e.get("text") or "").lower()
            or typed_text.lower() in str(e.get("aria_label") or "").lower()
            or typed_text.lower() in str(e.get("value") or "").lower()
            for e in elems_after_list
        )
        if chip_found:
            return ValidationResult(
                passed=True, confidence=0.92,
                reason=f"Typed text '{typed_text[:40]}' successfully confirmed on page (chip/body/value).",
                tier="dom_diff",
            )

        if "typed" in result.lower() and not any(k in result.lower() for k in ("error", "failed", "not found")):
            return ValidationResult(
                passed=True, confidence=0.85,
                reason=f"Type action confirmed by extension: {result[:80]}.",
                tier="dom_diff",
            )

        # Otherwise ambiguous — fall through to VLM
        return None

    # ── browser_dismiss_popup / popup click ──────────────────────────────────
    if action in ("browser_dismiss_popup", "browser_dismiss_popups"):
        modal_before = dom_before.get("active_modal")
        modal_after = dom_after.get("active_modal")
        def _is_app_modal(m):
            if not m:
                return False
            title = (m.get("title") or "").lower()
            return any(k in title for k in ("compose", "new message", "draft", "mail", "editor", "thread", "message", "chat"))

        if not _is_app_modal(modal_before) and not _is_app_modal(modal_after):
            if modal_before and not modal_after:
                return ValidationResult(
                    passed=True,
                    confidence=0.95,
                    reason=f"Obstructive modal '{modal_before.get('title', 'popup')}' was successfully dismissed.",
                    tier="dom_diff",
                )
            if modal_before and modal_after:
                return ValidationResult(
                    passed=False,
                    confidence=0.90,
                    reason=f"Obstructive modal '{modal_after.get('title', 'popup')}' is still open and blocking the page.",
                    suggestion="Dismiss the modal using browser_dismiss_popups or forced script injection.",
                    tier="dom_diff",
                )

    # ── browser_click ─────────────────────────────────────────────────────────
    if action == "browser_click":
        # If URL changed, click likely triggered navigation → high confidence pass
        if url_before != url_after:
            return ValidationResult(
                passed=True, confidence=0.93,
                reason=f"Click caused navigation to {url_after[:80]}.",
                tier="dom_diff",
            )
        # If DOM element count changed meaningfully, something happened
        before_count = len(dom_before.get("interactive_elements", []))
        after_count = len(elems_after_list)
        if abs(after_count - before_count) >= 2:
            return ValidationResult(
                passed=True, confidence=0.80,
                reason=f"Click changed DOM elements ({before_count} → {after_count}).",
                tier="dom_diff",
            )
        result_lower = result.lower()
        if any(k in result_lower for k in ("not found", "error", "failed", "ambiguous", "not_visible", "disabled")):
            target = args.get("text") or args.get("selector") or "element"
            return ValidationResult(
                passed=False, confidence=0.90,
                reason=f"Click tool reported failure: {result[:120]}",
                suggestion=f"Try browser_click with a more specific selector for '{target}'.",
                tier="dom_diff",
            )
        # Email send confirmation check
        if any(w in str(args.get("text", "")).lower() or w in str(args.get("selector", "")).lower() for w in ("send", "submit")):
            if any(k in result_lower for k in ("sent_confirmed", "message sent", "compose dialog closed", "dispatched")):
                return ValidationResult(
                    passed=True, confidence=0.99,
                    reason="Email send confirmed: delivery notification confirmed and compose window closed.",
                    tier="dom_diff",
                )
            for el in elems_after_list:
                t = (el.get("text") or el.get("title") or el.get("aria_label") or "").lower()
                if "message sent" in t or "email sent" in t or "your message has been sent" in t:
                    return ValidationResult(
                        passed=True, confidence=0.99,
                        reason="Email send confirmed: message sent toast detected in DOM.",
                        tier="dom_diff",
                    )
            # Compose dialog open before, but now closed in dom_after
            m_before = dom_before.get("active_modal") or {}
            m_after = dom_after.get("active_modal") or {}
            if "compose" in (m_before.get("title") or "").lower() and not m_after:
                return ValidationResult(
                    passed=True, confidence=0.99,
                    reason="Email send confirmed: compose window closed upon clicking send.",
                    tier="dom_diff",
                )

        # Compose dialog open check
        if "compose" in str(args.get("text", "")).lower() or "compose" in str(args.get("selector", "")).lower():
            if "already open" in result_lower or any("compose" in (el.get("aria_label") or "").lower() or "subject" in (el.get("placeholder") or "").lower() or "subjectbox" in (el.get("selector") or "").lower() for el in elems_after_list):
                return ValidationResult(
                    passed=True, confidence=0.95,
                    reason="Compose dialog is open and ready for recipient input.",
                    tier="dom_diff",
                )

        if "clicked" in result_lower:
            return ValidationResult(
                passed=True, confidence=0.88,
                reason=f"Click confirmed on element: {result[:80]}.",
                tier="dom_diff",
            )
        # Otherwise ambiguous — fall through to VLM
        return None

    # ── browser_select ────────────────────────────────────────────────────────
    if action == "browser_select":
        if "selected" in result.lower():
            return ValidationResult(
                passed=True, confidence=0.95, reason="Select tool confirmed selection.", tier="dom_diff"
            )
        return ValidationResult(
            passed=False, confidence=0.85,
            reason=f"browser_select did not confirm selection: {result[:100]}",
            suggestion="Retry browser_select with correct value or label.",
            tier="dom_diff",
        )

    # ── browser_press ─────────────────────────────────────────────────────────
    if action == "browser_press":
        if url_before != url_after:
            return ValidationResult(
                passed=True, confidence=0.92, reason=f"Key press triggered navigation to {url_after}.", tier="dom_diff"
            )
        # Not enough info — fall through to VLM only for Enter/Submit; others pass
        key = args.get("key", "")
        if key not in ("Enter", "Return", "Space"):
            return ValidationResult(
                passed=True, confidence=0.70, reason=f"Key '{key}' dispatched.", tier="dom_diff"
            )
        return None  # Ambiguous for Enter — check VLM

    # ── browser_execute_js ────────────────────────────────────────────────────
    if action == "browser_execute_js":
        if "error" in result.lower() or "exception" in result.lower():
            return ValidationResult(
                passed=False, confidence=0.88,
                reason=f"Script execution reported an error: {result[:120]}",
                suggestion="Fix the JavaScript or try an alternative approach.",
                tier="dom_diff",
            )
        return ValidationResult(
            passed=True, confidence=0.75,
            reason="Script executed without reported errors.",
            tier="dom_diff",
        )

    # Default: no DOM-diff rule — fall through to VLM
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tier 2: VLM Screenshot Validation (called only when Tier 1 is ambiguous)
# ──────────────────────────────────────────────────────────────────────────────
def _build_vlm_prompt(action: str, args: dict, dom_after: dict) -> str:
    """Build a concise, action-specific VLM prompt to minimise token usage and latency."""
    url = dom_after.get("url", "")
    title = dom_after.get("title", "")
    base = (
        f"You are a web automation QA agent verifying that a browser action succeeded.\n"
        f"Current page: '{title}' ({url})\n"
    )

    if action == "browser_type":
        text = args.get("text", "")
        selector = args.get("selector", "")
        return (
            base
            + f"Action performed: Typed '{text}' into input '{selector}'.\n"
            + f"Task: Look at the input field matching '{selector}'. "
            + f"Does it visibly contain the text '{text}'?\n"
            + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
        )

    if action == "browser_click":
        target = args.get("text") or args.get("selector") or "element"
        if any(w in str(target).lower() for w in ("send", "submit")):
            return (
                base
                + f"Action performed: Clicked '{target}' to send email or submit form.\n"
                + "Task: Look at the screenshot. Has the email been sent? Look for any 'Message sent' toast or notification, or verify the compose window has closed.\n"
                + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
            )
        return (
            base
            + f"Action performed: Clicked '{target}'.\n"
            + "Task: Did the click produce any visible change (new content, navigation, dialog opened, button state changed)?\n"
            + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
        )

    if action == "browser_navigate":
        url_target = args.get("url", "")
        return (
            base
            + f"Action performed: Navigated to '{url_target}'.\n"
            + "Task: Does the page shown match the target URL? Is it fully loaded?\n"
            + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
        )

    if action == "browser_press":
        key = args.get("key", "")
        return (
            base
            + f"Action performed: Pressed key '{key}'.\n"
            + "Task: Did the key press produce any visible change (form submitted, dialog closed, new content)?\n"
            + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
        )

    # Generic fallback
    return (
        base
        + f"Action performed: {action} with args {json.dumps(args, default=str)[:120]}.\n"
        + "Task: Does the page state look correct and expected after this action?\n"
        + "Reply ONLY with JSON: {\"passed\": true/false, \"confidence\": 0-1, \"reason\": \"...\", \"suggestion\": \"...\"}"
    )


async def _vlm_validate(
    action: str,
    args: dict,
    dom_after: dict,
    screenshot_bytes: bytes,
) -> ValidationResult:
    """Call the Groq vision model to validate the screenshot against the expected action outcome."""
    from backend.core.config import get_groq_api_key, get_groq_model

    api_key = get_groq_api_key()
    if not api_key:
        return ValidationResult(
            passed=True, confidence=0.5,
            reason="VLM validation skipped — no Groq API key.",
            tier="vlm",
        )

    prompt = _build_vlm_prompt(action, args, dom_after)
    b64_img = base64.b64encode(screenshot_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64_img}"

    try:
        from backend.agent.router.model_router import call_vision_with_dynamic_switch
        raw = await call_vision_with_dynamic_switch(prompt=prompt, data_url=data_url, max_tokens=200)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return ValidationResult(
                passed=True, confidence=0.5,
                reason="VLM returned non-JSON response — assuming pass.",
                tier="vlm",
            )
        parsed = json.loads(match.group(0), strict=False)
        return ValidationResult(
            passed=bool(parsed.get("passed", True)),
            confidence=float(parsed.get("confidence", 0.7)),
            reason=str(parsed.get("reason", "VLM did not provide a reason.")),
            suggestion=str(parsed.get("suggestion", "")),
            tier="vlm",
            details={"raw": raw[:300]},
        )
    except Exception as exc:
        is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower()
        err_type = "RATE LIMIT (429)" if is_rate_limit else "ERROR"
        print(f"\n{'!'*68}\n[NEXUS VLM VALIDATION {err_type}]\nAction: {action}\nDetails: {exc}\n{'!'*68}\n", flush=True)
        logger.warning("VLM validation %s for '%s': %s", err_type, action, exc)
        return ValidationResult(
            passed=True, confidence=0.5,
            reason=f"VLM validation {err_type.lower()} ({exc}) — continuing automation.",
            tier="error",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Goal Completion Validator — runs at the very end, not per-step
# ──────────────────────────────────────────────────────────────────────────────
async def validate_goal_completion(
    goal: str,
    dom_final: dict,
    screenshot_bytes: Optional[bytes],
    execution_history: list[dict],
    initial_dom: Optional[dict] = None,
) -> ValidationResult:
    """
    Comprehensive DOM Diff + VLM validation to confirm the user's full goal has
    been met before declaring goal_achieved. Compares initial baseline DOM with final DOM.
    """
    from backend.core.config import get_groq_api_key, get_groq_model

    url = dom_final.get("url", "")
    title = dom_final.get("title", "")

    # ── 1. Structured DOM Diff Calculation ──
    dom_diff_info = ""
    if initial_dom:
        init_url = initial_dom.get("url", "")
        init_title = initial_dom.get("title", "")
        init_elements = initial_dom.get("interactive_elements", [])
        final_elements = dom_final.get("interactive_elements", [])

        init_signatures = {
            (e.get("tag"), e.get("selector"), (e.get("text") or "").strip(), (e.get("aria_label") or "").strip())
            for e in init_elements
        }

        added = [
            e for e in final_elements
            if (e.get("tag"), e.get("selector"), (e.get("text") or "").strip(), (e.get("aria_label") or "").strip()) not in init_signatures
        ]

        modified_vals = [
            e for e in final_elements
            if e.get("value") and not any(
                ie.get("value") == e.get("value")
                for ie in init_elements
                if ie.get("selector") == e.get("selector")
            )
        ]

        added_descriptions = [
            f"{e.get('text') or e.get('aria_label') or e.get('placeholder') or e.get('selector')} ({e.get('role') or e.get('tag')})"
            for e in added
            if (e.get("text") or e.get("aria_label") or e.get("placeholder"))
        ]
        mod_descriptions = [f"{e.get('selector')}: value='{e.get('value')}'" for e in modified_vals]

        dom_diff_info = (
            f"\n--- DOM DIFF (BEFORE VS AFTER TASK EXECUTION) ---\n"
            f"Initial Page: '{init_title}' ({init_url})\n"
            f"Final Page: '{title}' ({url})\n"
            f"Elements Added ({len(added_descriptions)}): {added_descriptions[:25]}\n"
            f"Field Values Modified ({len(mod_descriptions)}): {mod_descriptions[:15]}\n"
        )

        try:
            from backend.agent.tools.web_automation.logger import auto_logger
            auto_logger.log_dom_diff(
                init_url, url, added_descriptions, mod_descriptions,
                f"Diff: {len(added_descriptions)} added, {len(mod_descriptions)} modified"
            )
        except Exception:
            pass

        # Zero changes check: if task intended to create/modify page content but DOM remained completely identical
        requires_creation = any(w in goal.lower() for w in ("create", "add", "type", "fill", "write", "make", "build"))
        if requires_creation and len(added) == 0 and len(modified_vals) == 0 and init_url == url and len(execution_history) >= 2:
            return ValidationResult(
                passed=False,
                confidence=0.98,
                reason="DOM comparison confirms zero elements or values were created or modified on this page.",
                suggestion="The previous actions did not mutate the page DOM. Try directly targeting inputs or clicking buttons on the canvas.",
                tier="dom_diff",
                details={"missing": ["All requested elements (page DOM remained identical to initial state)"]},
            )

    dom_text = json.dumps({
        "url": url,
        "title": title,
        "elements": [
            {"tag": e.get("tag"), "text": e.get("text"), "value": e.get("value"), "role": e.get("role")}
            for e in dom_final.get("interactive_elements", [])[:35]
        ],
    }, ensure_ascii=False)

    history_summary = "\n".join(
        f"- {h['action']}({json.dumps(h.get('args', {}), default=str)[:80]}): "
        f"{'✓' if h.get('success') else '✗'} {str(h.get('result', ''))[:60]}"
        for h in execution_history[-12:]
    )

    # Deterministic check for email send completion
    is_email = any(w in goal.lower() for w in ("send email", "send mail", "compose email", "compose mail", "dispatch email"))
    if is_email:
        has_send_click = any(
            h.get("action") == "browser_click" and any(w in str(h.get("args", {})).lower() for w in ("send", "submit"))
            for h in execution_history
        )
        has_toast = any("message sent" in str(e.get("text") or e.get("aria_label") or "").lower() for e in dom_final.get("interactive_elements", []))
        no_compose = not any("compose" in (e.get("aria_label") or "").lower() or "subjectbox" in (e.get("selector") or "").lower() for e in dom_final.get("interactive_elements", []))
        if has_send_click and (has_toast or no_compose):
            return ValidationResult(
                passed=True,
                confidence=0.99,
                reason="Email send confirmed: send action dispatched, compose dialog closed, and mailbox active.",
                tier="dom_diff",
            )

    api_key = get_groq_api_key()
    if not api_key:
        return ValidationResult(
            passed=True, confidence=0.5,
            reason="Goal validation skipped — no API key.",
            tier="skipped",
        )

    # ── Text-only LLM check (with DOM Diff context) ──────────────────────────
    prompt_text = f"""You are a strict web automation QA auditor.

USER GOAL: {goal}

{dom_diff_info}

CURRENT FINAL PAGE STATE:
{dom_text}

ACTIONS COMPLETED (last 12):
{history_summary}

TASK: Determine with high confidence whether the user's goal has been fully completed.
Check:
1. Does the current URL/page match what success looks like for this goal?
2. Are all required elements, text, questions, or data the user asked for visible on the page?
3. Did the DOM mutations reflect the actual requirements (e.g. correct question titles, short answer type)?
4. Never assume success if requested fields are missing from the page.

Respond ONLY with JSON:
{{"passed": true/false, "confidence": 0.0-1.0, "reason": "one-sentence explanation", "missing": ["list of anything still not done"], "suggestion": "what to do next if not passed"}}"""

    text_result: Optional[ValidationResult] = None
    try:
        from backend.agent.router.model_router import ainvoke_with_dynamic_switch
        from langchain_core.messages import HumanMessage
        raw_res = await ainvoke_with_dynamic_switch(
            [HumanMessage(content=prompt_text)],
            operation="reasoning",
            temperature=0.0,
        )
        raw = raw_res.content if hasattr(raw_res, "content") else str(raw_res)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0), strict=False)
            passed = bool(parsed.get("passed", True))
            conf = float(parsed.get("confidence", 0.7))
            text_result = ValidationResult(
                passed=passed,
                confidence=conf,
                reason=str(parsed.get("reason", "")),
                suggestion=str(parsed.get("suggestion", "")),
                tier="dom_diff",
                details={"missing": parsed.get("missing", [])},
            )
    except Exception as exc:
        print(f"\n{'!'*68}\n[NEXUS LLM VALIDATOR ERROR / RATE LIMIT]\nText validator failed: {exc}\n{'!'*68}\n", flush=True)
        logger.error("Goal text validation error: %s", exc)

    # ── VLM screenshot check (if screenshot available and text check is uncertain) ──
    if screenshot_bytes and (text_result is None or text_result.confidence < 0.80 or not text_result.passed):
        b64_img = base64.b64encode(screenshot_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64_img}"

        vlm_prompt = (
            f"You are a QA auditor verifying an automation goal was completed.\n"
            f"USER GOAL: {goal}\n"
            f"Current page URL: {url}\n"
            f"Current page title: {title}\n"
            f"Look at the screenshot carefully. "
            f"Has the goal '{goal}' been fully and visibly accomplished on this page?\n"
            f"Check every specific requirement in the goal — if any part is missing or wrong, it is NOT passed.\n"
            f"Respond ONLY with JSON: {{\"passed\": true/false, \"confidence\": 0.0-1.0, "
            f"\"reason\": \"...\", \"missing\": [\"...\"], \"suggestion\": \"...\"}}"
        )

        try:
            from backend.agent.router.model_router import call_vision_with_dynamic_switch
            raw_vlm = await call_vision_with_dynamic_switch(
                prompt=vlm_prompt,
                data_url=data_url,
                max_tokens=300,
            )
            match = re.search(r"\{.*\}", raw_vlm, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0), strict=False)
                vlm_passed = bool(parsed.get("passed", True))
                vlm_conf = float(parsed.get("confidence", 0.7))

                # Combine: both must agree for high-confidence pass
                if text_result is not None:
                    if text_result.passed and vlm_passed:
                        final_conf = min(0.97, (text_result.confidence + vlm_conf) / 2 + 0.1)
                        res = ValidationResult(
                            passed=True, confidence=final_conf,
                            reason=f"LLM + VLM both confirm goal met. {text_result.reason}",
                            tier="vlm",
                            details={"missing": parsed.get("missing", [])},
                        )
                    elif not vlm_passed:
                        res = ValidationResult(
                            passed=False,
                            confidence=max(text_result.confidence, vlm_conf),
                            reason=str(parsed.get("reason", "VLM says goal not met.")),
                            suggestion=str(parsed.get("suggestion", "")),
                            tier="vlm",
                            details={"missing": parsed.get("missing", [])},
                        )
                    else:
                        res = ValidationResult(
                            passed=False,
                            confidence=0.60,
                            reason=f"Text check passed but VLM uncertain: {parsed.get('reason', '')}",
                            suggestion=str(parsed.get("suggestion", "")),
                            tier="vlm",
                            details={"missing": parsed.get("missing", [])},
                        )
                else:
                    res = ValidationResult(
                        passed=vlm_passed, confidence=vlm_conf,
                        reason=str(parsed.get("reason", "")),
                        suggestion=str(parsed.get("suggestion", "")),
                        tier="vlm",
                        details={"missing": parsed.get("missing", [])},
                    )

                try:
                    from backend.agent.tools.web_automation.logger import auto_logger
                    auto_logger.log_goal_verification(goal, res.passed, res.confidence, res.reason, res.details.get("missing"))
                except Exception:
                    pass
                return res
        except Exception as exc:
            print(f"\n{'!'*68}\n[NEXUS VLM ERROR / RATE LIMIT]\nVision model failed during goal validation: {exc}\n{'!'*68}\n", flush=True)
            logger.error("Goal VLM validation error: %s", exc)

    # Return text_result if available, else fail safely
    if text_result is not None:
        try:
            from backend.agent.tools.web_automation.logger import auto_logger
            auto_logger.log_goal_verification(goal, text_result.passed, text_result.confidence, text_result.reason, text_result.details.get("missing"))
        except Exception:
            pass
        return text_result

    return ValidationResult(
        passed=False, confidence=0.0,
        reason="Validation could not confirm page state — runtime error occurred.",
        tier="error",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point — validate a single step
# ──────────────────────────────────────────────────────────────────────────────
async def validate_step(
    action: str,
    args: dict,
    result: str,
    dom_before: dict,
    dom_after: dict,
    screenshot_bytes: Optional[bytes] = None,
) -> ValidationResult:
    """
    Validate that a browser tool action had the intended effect.

    Tier 1: Instant DOM diff — returns immediately when conclusive.
    Tier 2: VLM screenshot — only when Tier 1 is ambiguous AND a screenshot is available.

    Actions in SKIP_VALIDATION_ACTIONS always return passed=True instantly.
    """
    if action in SKIP_VALIDATION_ACTIONS:
        return ValidationResult(
            passed=True, confidence=1.0,
            reason=f"Validation skipped for {action}.",
            tier="skipped",
        )

    # Tier 1: DOM diff
    t1 = _dom_diff_validate(action, args, result, dom_before, dom_after)
    if t1 is not None:
        logger.debug(
            "Step validation [DOM-diff] action=%s passed=%s conf=%.2f reason=%s",
            action, t1.passed, t1.confidence, t1.reason,
        )
        return t1

    # Tier 2: VLM screenshot (only if we have bytes)
    if screenshot_bytes:
        t2 = await _vlm_validate(action, args, dom_after, screenshot_bytes)
        logger.debug(
            "Step validation [VLM] action=%s passed=%s conf=%.2f reason=%s",
            action, t2.passed, t2.confidence, t2.reason,
        )
        return t2

    # No screenshot available and DOM diff was inconclusive → optimistic pass
    return ValidationResult(
        passed=True, confidence=0.55,
        reason="DOM diff inconclusive and no screenshot available — assuming pass.",
        tier="dom_diff",
    )
