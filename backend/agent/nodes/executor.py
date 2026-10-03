"""
NEXUS Adaptive ReAct Executor
================================
Every step: Observe live page → Think (LLM decides next action) → Act → Validate → Replan if needed.
The agent NEVER blindly follows the pre-planned steps.
It continuously reads the real DOM, decides the next best single action,
executes it, validates the result with DOM diff + optional VLM screenshot,
and adaptively replans if the action did not have the intended effect.
"""
from __future__ import annotations
import asyncio
import datetime
import json
import logging
import re
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from backend.agent.state import NexusState
from backend.agent.tools.registry import tool_registry
from backend.agent.router.model_router import get_llm
from backend.core.config import get_groq_api_key
from backend.core.speech import generate_spoken_message, generate_spoken_brief
from backend.agent.tools.web_automation.validator import (
    validate_step,
    validate_goal_completion,
    SKIP_VALIDATION_ACTIONS,
)

logger = logging.getLogger("nexus.executor")


# ─────────────────────────────────────────────────────────────────────────────
# Tool categories
# ─────────────────────────────────────────────────────────────────────────────
BROWSER_TOOLS = {
    "browser_click", "browser_type", "browser_select", "browser_press",
    "browser_navigate", "browser_inspect", "browser_get_source",
    "browser_get_tabs", "browser_switch_tab", "browser_wait",
    "browser_dismiss_popup", "browser_execute_js", "browser_scroll",
}

ALL_AVAILABLE_TOOLS = {
    # Browser
    "browser_navigate", "browser_inspect", "browser_click", "browser_type",
    "browser_select", "browser_press", "browser_wait", "browser_get_tabs",
    "browser_switch_tab", "browser_dismiss_popup", "browser_execute_js",
    "browser_get_source", "browser_scroll",
    # Document Automation
    "document_create", "document_open", "document_add_title",
    "document_add_heading", "document_add_paragraph", "document_add_bullet",
    "document_add_numbered_item", "document_add_table", "document_add_page_break",
    "document_add_image", "document_save", "document_read", "document_verify",
    # Spreadsheet Automation
    "spreadsheet_create", "spreadsheet_open", "spreadsheet_list_sheets",
    "spreadsheet_create_sheet", "spreadsheet_rename_sheet", "spreadsheet_read_cell",
    "spreadsheet_read_range", "spreadsheet_read_sheet", "spreadsheet_write_cell",
    "spreadsheet_write_range", "spreadsheet_add_formula", "spreadsheet_format_range",
    "spreadsheet_create_table", "spreadsheet_create_chart", "spreadsheet_save",
    "spreadsheet_read", "spreadsheet_verify",
    # System

    "run_command", "write_file", "read_file", "delete_file",
    "list_directory", "search_files", "web_search",
    # GUI
    "inspect_screen", "click_mouse", "type_text", "press_key",
    "press_hotkey", "activate_window",
    # Terminal & System
    "get_current_time",
    "media_control",
    "play_music",
    # Special & Interactive
    "ai_response",
    "ask_user",
}



# ─────────────────────────────────────────────────────────────────────────────
# The core ReAct decision prompt
# ─────────────────────────────────────────────────────────────────────────────
def build_react_prompt() -> str:
    now = datetime.datetime.now().strftime("%A %B %d %Y %I:%M %p")
    return f"""You are NEXUS Adaptive Execution Engine. Current time: {now}.

Your job: Look at the REAL current state of the world (page DOM, history of actions taken),
then decide the single best NEXT action to get closer to the goal.

RULES:
1. ALWAYS base your decision on the LIVE page state — not the original plan.
2. If you are on a different page than expected, adapt — navigate or wait first.
3. If an element is not found, try a different selector or scroll to find it.
4. If you already completed an action (in history), don't repeat it.
5. Output ONLY a raw JSON object — no markdown, no explanation outside JSON.

CRITICAL — goal_achieved:
- ONLY output goal_achieved if the CURRENT PAGE STATE (URL + visible elements) confirms the goal is done.
- Check the current URL. If the page is still the starting page or a dashboard, the goal is NOT done.
- Never declare goal_achieved based on history alone — verify with the LIVE current page.
- If the current URL/elements do NOT match the expected end state, take another action instead.

CRITICAL — modals, dialogs, and popups across ANY website:
- Universal across ANY website: if an unexpected modal, dialog, overlay, newsletter popup, promo, onboarding tour, or cookie banner appears on ANY website, dismiss it immediately before interacting with the page.
- NEVER click in-page AI assistant buttons ("Ask Gemini", "Help me create", "Copilot", "Help me write", or sparkle icons) unless the user's goal specifically asked for AI assistance! Always interact directly with the form/page canvas.

CRITICAL — human-like sequential tab management:
- You work sequentially on ONE tab at a time like a human.
- Before opening duplicate tabs, inspect open tabs (`browser_get_tabs`) and switch to an existing tab (`browser_switch_tab`) if that page or service is already open. You can switch tabs by tab ID, URL, or title!
- If the current page is a blank tab or unexpected tab, inspect open tabs or navigate directly to your target.
- NEVER close any tabs unnecessarily. Never run scripts or hotkeys that close browser tabs or windows.
- NEVER overwrite or replace the URL of a user's existing open tab. If a target site is already open, switch to it (`browser_switch_tab`).
- Only open a new tab if no relevant tab exists.

CRITICAL — navigation:
- After a browser_click that should navigate (e.g. clicking a link/template), ALWAYS check if the URL changed.
- If history shows you clicked something but the URL is the same, the click failed to navigate.
  → Try browser_navigate with the direct URL instead of clicking again.
- Prefer browser_navigate to a known direct URL over clicking UI elements for page transitions.
  → Google Forms new form: https://forms.new
  → Google Docs new: https://docs.new
  → Google Sheets new: https://sheets.new
- If stuck clicking something 2+ times with no URL change, switch to browser_navigate.

CRITICAL — Google Forms:
- In a new Google Form (forms.new), Question 1 ALREADY EXISTS by default ("Untitled question").
- NEVER click "Add question" (+) for Question 1! Type the question title directly into the existing first question field.
- QUESTION TYPES: New questions default to "Multiple choice" (showing "Option 1"). For text fields like "Name", "Phone Number", "Email", "Address", they MUST be changed to "Short answer"!
  → To set question type: click the question type dropdown on the active card (selector: "div[role='listitem'] div[role='listbox']" or text: "Multiple choice"), then click "Short answer" (or selector: "div[role='option'][data-value='0']", text: "Short answer").
  → If Google Forms offers a chip suggestion like "Change to short answer", click it!
- SEQUENTIAL QUESTION CREATION:
  1. Set Question 1's title first (e.g. "Name").
  2. Set Question 1 type to "Short answer" so it is not left as Multiple choice with Option 1!
  3. To create Question 2 (e.g. "Email"), click "Add question" (+) on the floating toolbar on the right:
     selector: "div[role='button'][aria-label*='Add question' i], div[data-tooltip*='Add question' i]" or text: "Add question".
  4. Wait for the new question card to appear.
  5. Only THEN type Question 2's title into the new second question's title textbox.
  6. NEVER type a second question's title into Question 1 — that overwrites Question 1!
  7. NEVER declare goal_achieved if any requested question (e.g. "Name" or "Email") is missing from the page!

CRITICAL — step completion:
- Include "step_completed": true ONLY when the current plan milestone has actually been completed on the page.
- Include "step_completed": false if this action is an intermediate, preparatory, or recovery step (e.g. dismissing a popup, navigating, waiting, scrolling, or focusing).

Output format:
{{
  "action": "<tool_name or goal_achieved or cannot_proceed>",
  "args": {{ ... }},
  "reasoning": "<1 sentence: why this action right now, referencing current URL/page state>",
  "step_completed": true or false
}}

Available tools: {', '.join(sorted(ALL_AVAILABLE_TOOLS))}


For browser_click: args = {{"selector": "css", "text": "visible text", "xpath": ""}}
For browser_type:  args = {{"selector": "css", "text": "text to enter", "clear_first": true, "press_enter": true}}
For browser_navigate: args = {{"url": "https://...", "new_tab": false}}
For browser_get_tabs: args = {{}}
For browser_switch_tab: args = {{"tab_id": 123}} (or {{"url": "domain/url"}} or {{"title": "page title"}})
For browser_wait: args = {{"seconds": 2.0}}
For browser_execute_js: args = {{"script": "javascript code"}}
For browser_dismiss_popups: args = {{}}
For run_command: args = {{"command": "shell command"}}
For write_file: args = {{"path": "...", "content": "..."}}
For ai_response: args = {{"answer": "response text"}}
For ask_user: args = {{"prompt": "question or choice to ask user", "options": ["Option A", "Option B"], "placeholder": "Type response..."}}
For goal_achieved: args = {{"summary": "what was accomplished"}}
For cannot_proceed: args = {{"reason": "why stuck"}}

CRITICAL — asking the user for choices or resolving doubts:
- If you need a user decision, template choice, preference, or have ANY doubt about which user/item to select, use `ask_user`.
- The automation pill will display an interactive input drawer with clickable choice chips and a text input field, and will pause until the user clicks or types their response.
- Chat & Messaging Apps (WhatsApp, Slack, Discord, Teams, Reddit, etc.):
  1. Searching: Type the target contact/user name into the search bar.
  2. Ambiguity & Doubt: If search results show MULTIPLE possible candidates (e.g. multiple contacts with similar names, or a direct contact vs groups with shared names), or if you are unsure which user the user wants, DO NOT guess! Call `ask_user` with a clear prompt and candidate names in `options`:
     args = {{"prompt": "Multiple matches found for '<name>'. Which chat should I open?", "options": ["Option 1", "Option 2"], "placeholder": "Select or type contact name..."}}
  3. Clicking Contact: Once confirmed or when a clear match is visible, click the chat item using `browser_click` with `text="<Name>"` or selector `span[title*="<Name>"]`, `[role="listitem"]`, or `[role="row"]`.
  4. Sending Message: Once the chat window is open and the message composer is visible (e.g. editable textbox), use `browser_type` to write the message and press Enter.
- Email Clients & Complex Web Forms (Gmail, Outlook, Webmail):
  1. Compose: Click the Compose button (`text="Compose"` or `div[role="button"][gh="cm"]`).
  2. To Recipient: Enter recipient into `input[aria-label*="To recipients" i]` or `div[aria-label*="To" i] input` with `press_enter: true` so the recipient chip commits.
  3. Cc / Bcc: If Cc or Bcc is needed and the field is hidden, first click the "Cc" or "Bcc" toggle button (`span[role="button"][aria-label*="Add Cc" i]`, `text="Cc"`) to reveal the input, then type the address with `press_enter: true`.
  4. Subject: Type into `input[name="subjectbox"]` or `input[aria-label*="Subject" i]`.
  5. Message Body: Type into `div[role="textbox"][aria-label*="Message Body" i]` or `div[contenteditable="true"][aria-label*="Body" i]`.
  6. Send: Click Send button (`text="Send"` or `[aria-label*="Send" i]`)."""


async def _get_live_page_state() -> dict:
    """Inspect the live DOM. Returns structured page snapshot."""
    try:
        inspect_tool = tool_registry.get("browser_inspect")
        if inspect_tool:
            result = await inspect_tool.execute(max_elements=100)
            if result.success and result.output:
                try:
                    return json.loads(result.output)
                except Exception:
                    pass
    except Exception:
        pass
    return {}


async def _take_cdp_screenshot() -> Optional[bytes]:
    """Non-blocking CDP screenshot. Returns None if CDP not connected (extension-only mode)."""
    try:
        from backend.agent.tools.web_automation.driver import BrowserAutomationEngine
        engine = BrowserAutomationEngine.get_instance()
        return await asyncio.wait_for(engine.take_screenshot(), timeout=4.0)
    except Exception:
        return None


async def _fire_overlay(event: str, payload: dict | None = None) -> None:
    """
    Fire-and-forget: push an overlay control command to the Chrome extension
    and synchronize live step status to the independent automation pill.
    """
    try:
        from backend.agent.tools.web_automation.extension_bridge import extension_bridge
        if extension_bridge.is_connected():
            await extension_bridge.send_command(event, payload or {}, timeout=2.0)
    except Exception:
        pass  # Never block automation due to overlay errors

    try:
        from backend.api.nexus import push_event
        if event == "automation_update_step" and payload and "step" in payload:
            await push_event(None, "status", {"status": "executing", "message": payload["step"]})
        elif event == "automation_stop":
            await push_event(None, "status", {"status": "completed", "message": "Task completed successfully"})
    except Exception:
        pass


def _format_dom_for_llm(dom: dict, goal: str = "") -> str:
    """Format DOM snapshot into compact text for the LLM, filtering out intrusive AI buttons."""
    if not dom:
        return "Page state unavailable (extension not connected or no browser open)"

    url = dom.get("url", "unknown")
    title = dom.get("title", "")
    active_modal = dom.get("active_modal")
    elements = dom.get("interactive_elements", [])

    if dom.get("is_restricted_tab"):
        note = dom.get("note") or f"Active tab is restricted: '{url}'"
        return f"[Warning] {note}\nURL: {url}\nTitle: {title}\nInteractive elements: 0\n(Tip: use browser_navigate to go to your target website, or use browser_switch_tab to switch to an open tab)."

    # Filter out in-page AI assistant triggers (e.g. "Ask Gemini", "Help me create") unless explicitly requested
    goal_asks_for_ai = any(k in goal.lower() for k in ("ask gemini", "help me create", "copilot", "use gemini", "ai assistant"))
    if not goal_asks_for_ai:
        elements = [e for e in elements if not e.get("is_ai_assistant")]

    lines = [f"URL: {url}", f"Title: {title}"]
    if active_modal:
        is_intrusive = active_modal.get("is_intrusive", False)
        if is_intrusive:
            lines.append(
                f"[Modal Warning] Obstructive modal visible: '{active_modal.get('title', 'Popup')}'\n"
                f"   Close selector: {active_modal.get('close_selector', 'use browser_dismiss_popups')}\n"
                f"   NOTE: This popup blocks the underlying page canvas. Dismiss it before interacting with form fields."
            )
        else:
            lines.append(
                f"[Dialog Info] Application dialog open: '{active_modal.get('title', 'Dialog')}'\n"
                f"   Close selector: {active_modal.get('close_selector', 'N/A')}\n"
                f"   NOTE: If your current step interacts with this dialog, use its elements. Do NOT dismiss it if it is needed for the goal."
            )
    lines.append(f"Interactive elements ({len(elements)}):")
    for i, el in enumerate(elements[:80]):
        parts = [f"  [{i}]", f"<{el.get('tag','?')}>"]
        if el.get("id"):       parts.append(f"#{el['id']}")
        if el.get("selector"): parts.append(f"sel={el['selector']}")
        if el.get("aria_label"): parts.append(f'aria="{el["aria_label"][:40]}"')
        if el.get("placeholder"): parts.append(f'ph="{el["placeholder"][:30]}"')
        if el.get("text"):     parts.append(f'txt="{el["text"][:50]}"')
        if el.get("role"):     parts.append(f"role={el['role']}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _format_history(history: list[dict]) -> str:
    """Format execution history for the LLM."""
    if not history:
        return "No actions taken yet."
    lines = []
    for i, h in enumerate(history[-10:]):  # Last 10 actions max
        status = "✓" if h.get("success") else "✗"
        result_snippet = str(h.get("result", ""))[:120]
        lines.append(
            f"  [{i+1}] {status} {h.get('action')}({json.dumps(h.get('args', {}))[:80]})"
            + (f"\n       → {result_snippet}" if result_snippet else "")
        )
    return "\n".join(lines)


async def _react_decide(
    goal: str,
    dom: dict,
    history: list[dict],
    plan_guide: list[dict],
    is_web_task: bool,
    current_idx: int = 0,
) -> dict:
    """
    Core ReAct step: LLM observes current state and decides next action.
    Returns {action, args, reasoning}.
    """
    if current_idx >= len(plan_guide):
        return {"action": "goal_achieved", "args": {"summary": "All plan steps completed."}, "reasoning": "Plan complete."}

    api_key = get_groq_api_key()
    if not api_key:
        if current_idx < len(plan_guide):
            s = plan_guide[current_idx]
            return {"action": s.get("tool", "ai_response"), "args": s.get("args", {}), "reasoning": "No API key — using plan step directly"}
        return {"action": "goal_achieved", "args": {"summary": "All plan steps exhausted."}, "reasoning": ""}

    # ── Deterministic Milestone Execution ────────────────────────────────────
    # For non-browser, non-interactive deterministic tools (e.g. document, spreadsheet, system commands, media),
    # execute the planned milestone directly! This keeps execution fast, deterministic,
    # and completely immune to Groq TPM rate limits.
    # CRITICAL: Browser interaction tools (click, type, select, scroll, wait, inspect, etc.) or interactive web tasks
    # MUST ALWAYS flow through the ReAct loop so the agent observes the live page DOM, handles obstructive
    # popups/dialogs, resolves dynamic selectors, and adapts like an intelligent pair programmer.
    target_step = plan_guide[current_idx] if current_idx < len(plan_guide) else None
    target_tool = target_step.get("tool", "") if target_step else ""
    target_args = target_step.get("args", {}) if target_step else {}
    last_action_failed = bool(history and (not history[-1].get("success", True) or history[-1].get("validation_passed") is False))

    is_browser_interaction = (target_tool in BROWSER_TOOLS and target_tool != "browser_navigate")
    is_interactive_task = is_web_task and target_tool in BROWSER_TOOLS and target_tool != "browser_navigate"
    is_dialog_tool = target_tool in ("ask_user", "ai_response")

    if target_tool and target_args and not last_action_failed and not is_browser_interaction and not is_interactive_task and not is_dialog_tool:
        milestone_title = target_step.get("title") or target_tool
        return {
            "action": target_tool,
            "args": target_args,
            "reasoning": f"Advancing milestone: {milestone_title}",
            "step_completed": False,
        }

    dom_text = _format_dom_for_llm(dom, goal) if is_web_task else "N/A — non-browser task"
    history_text = _format_history(history)
    
    plan_lines = []
    for i, s in enumerate(plan_guide):
        if s.get("status") == "completed" or i < current_idx:
            status_tag = "✓ [COMPLETED]"
        elif i == current_idx:
            status_tag = ">>> [CURRENT TARGET]"
        else:
            status_tag = "    [PENDING]"
        plan_lines.append(f"  {status_tag} Step {i+1}: {s.get('title','?')} → {s.get('tool')}({json.dumps(s.get('args',{}))[:60]})")
    plan_text = "\n".join(plan_lines) or "  (no plan — use judgment)"

    user_msg = f"""GOAL: {goal}

EXECUTION PLAN (focus on the CURRENT TARGET step, adapting to the live page):
{plan_text}

ACTIONS ALREADY TAKEN:
{history_text}

CURRENT LIVE PAGE STATE:
{dom_text}

Decide the single best NEXT action to advance the CURRENT TARGET step:"""

    # Universal popup/modal dismissal check across ANY website
    active_modal = dom.get("active_modal") if isinstance(dom, dict) else None
    if active_modal:
        modal_title = (active_modal.get("title") or "").lower()
        goal_lower = goal.lower()
        is_work_modal = any(k in modal_title for k in ("compose", "new message", "draft", "mail", "editor", "message", "chat", "inbox"))
        user_wanted_modal = is_work_modal or any(k in goal_lower for k in ("open dialog", "open modal", "cookie settings", "view popup", "compose", "email", "mail", "send"))

        # Auto-dismiss if it's an intrusive blocking popup not explicitly requested
        if not user_wanted_modal:
            # Count previous attempts to dismiss popups in history
            popup_attempts = sum(
                1 for h in history
                if "popup" in h.get("reasoning", "").lower()
                or "modal" in h.get("reasoning", "").lower()
                or h.get("action") in ("browser_dismiss_popup", "browser_dismiss_popups")
                or (h.get("action") == "browser_execute_js" and "dialog" in str(h.get("args", {})))
            )
            close_sel = active_modal.get("close_selector")

            if popup_attempts == 0:
                # Level 1: Standard dismiss_popups (Escape + common selectors)
                return {
                    "action": "browser_dismiss_popups",
                    "args": {},
                    "reasoning": f"Dismissing obstructive popup '{active_modal.get('title', 'popup')}'",
                    "is_auxiliary": True,
                    "step_completed": False,
                }
            elif popup_attempts == 1 and close_sel:
                # Level 2: Targeted click on close selector with interactive ancestor resolution
                return {
                    "action": "browser_click",
                    "args": {"selector": close_sel},
                    "reasoning": f"Dismissing obstructive popup '{active_modal.get('title', 'popup')}' with targeted close button click",
                    "is_auxiliary": True,
                    "step_completed": False,
                }
            elif popup_attempts == 2:
                # Level 3: Modal is stubborn — forcibly hide/remove dialog and backdrop via DOM script
                js_script = (
                    "document.querySelectorAll('[role=\"dialog\"], [aria-modal=\"true\"], dialog[open], .quantumWizDialogPaperdialog')"
                    ".forEach(d => { d.style.setProperty('display', 'none', 'important'); d.style.setProperty('visibility', 'hidden', 'important'); }); "
                    "document.querySelectorAll('.quantumWizDialogPaperdialogBackdrop, [class*=\"backdrop\" i]').forEach(b => { if (b.id !== '__nexus-overlay-root__') b.remove(); }); "
                    "return 'Forcibly hid dialog and backdrop';"
                )
                return {
                    "action": "browser_execute_js",
                    "args": {"script": js_script},
                    "reasoning": f"Forcibly dismissing stubborn modal '{active_modal.get('title', 'popup')}' via DOM script injection",
                    "is_auxiliary": True,
                    "step_completed": False,
                }
            # If popup_attempts >= 3, do NOT loop further; proceed to page interaction or graceful fail.

    try:
        from backend.agent.router.model_router import ainvoke_with_dynamic_switch
        res = await ainvoke_with_dynamic_switch([
            SystemMessage(content=build_react_prompt()),
            HumanMessage(content=user_msg),
        ], operation="reasoning", temperature=0.1)
        raw = res.content.strip()
        decision = _extract_json_from_llm(raw)
        if isinstance(decision, list) and len(decision) > 0:
            decision = decision[0]
        if not isinstance(decision, dict):
            raise ValueError(f"Decision is not a JSON object: {type(decision)}")
        return decision
    except Exception as e:
        error_msg = f"LLM ReAct decision error: {e}"
        print(f"\n{'!'*68}\n[NEXUS REASONING ENGINE WARNING]\n{error_msg}\nUsing planned milestone...\n{'!'*68}\n", flush=True)
        # Fallback to current target plan step smoothly
        if current_idx < len(plan_guide):
            s = plan_guide[current_idx]
            milestone_title = s.get("title") or s.get("tool") or "Executing milestone"
            return {"action": s.get("tool"), "args": s.get("args", {}), "reasoning": milestone_title}
        return {"action": "goal_achieved", "args": {"summary": "All plan steps completed."}, "reasoning": ""}


def _extract_json_from_llm(raw: str) -> dict | list:
    """Extract parseable JSON object or array from model response, handling markdown and think traces."""
    raw = raw.strip()
    # 1. Direct parse
    try:
        return json.loads(raw)
    except Exception:
        pass

    import re
    # 2. Markdown codeblock ```json ... ```
    match = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # 3. Find balanced JSON object or list from text
    matches = list(re.finditer(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[.*\])", raw, re.DOTALL))
    for m in reversed(matches):
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

    # 4. Outermost braces fallback
    if "{" in raw and "}" in raw:
        candidate = raw[raw.rindex("{"):raw.rindex("}") + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
        candidate = raw[raw.index("{"):raw.rindex("}") + 1]
        return json.loads(candidate)

    raise ValueError(f"No parseable JSON found in response: {raw[:150]}")


def _is_terminal_connector_auth_error(action: str, output: str) -> bool:
    tool = tool_registry.get(action)
    if not getattr(tool, "connector_id", None):
        return False
    message = (output or "").lower()
    return bool(re.search(r"\b(?:401|403)\b|unauthorized|forbidden", message))


async def _execute_single_action(action: str, args: dict) -> tuple[bool, str]:
    """Execute a single tool and return (success, result_text)."""
    if action == "ai_response":
        explicit_answer = args.get("answer")
        if explicit_answer:
            return True, explicit_answer
        api_key = get_groq_api_key()
        if api_key:
            try:
                llm = get_llm("fast", temperature=0.5)
                now = datetime.datetime.now().strftime("%A %B %d %Y %I:%M %p")
                res = await llm.ainvoke([
                    SystemMessage(content=f"You are NEXUS. Current time: {now}. Answer directly."),
                    HumanMessage(content=args.get("question", "")),
                ])
                return True, res.content.strip()
            except Exception as e:
                return False, f"LLM error: {e}"
        return True, "No API key configured."

    if action == "ask_user":
        prompt = args.get("prompt") or args.get("question") or "Please provide your input or choice:"
        options = args.get("options") or []
        placeholder = args.get("placeholder") or "Type your response..."
        try:
            from backend.api.nexus import request_user_input, _task_queues
            from backend.core.file_dialog import open_native_save_dialog
            active_ids = list(_task_queues.keys())
            tid = active_ids[-1] if active_ids else "active_task"
            user_val = await request_user_input(tid, prompt=prompt, options=options, placeholder=placeholder)

            if user_val:
                clean_str = str(user_val).strip()
                def_name = "presentation.pptx" if any(w in prompt.lower() for w in ("powerpoint", "presentation", "ppt", "slides", ".pptx")) else "spreadsheet.xlsx"
                
                if "word" in prompt.lower() or "document" in prompt.lower() or ".docx" in prompt.lower():
                    def_name = "document.docx"
                elif any(w in prompt.lower() for w in ("powerpoint", "presentation", "ppt", "slides", ".pptx")):
                    match_ppt = re.search(r"\(([^)]+\.pptx)\)", prompt, re.IGNORECASE)
                    if match_ppt:
                        def_name = match_ppt.group(1)
                    else:
                        for opt in options:
                            if ".pptx" in opt:
                                def_name = opt.split("/")[-1].split("\\")[-1]
                                break
                elif ".xlsx" in prompt.lower():
                    for opt in options:
                        if ".xlsx" in opt:
                            def_name = opt.split("/")[-1].split("\\")[-1]
                            break

                if any(k in clean_str.lower() for k in ("browse", "explorer", "file explorer", "select file")):
                    chosen = open_native_save_dialog(default_filename=def_name, title="Select Where to Store Presentation")
                    if chosen:
                        user_val = chosen
                    else:
                        user_val = f"Desktop/{def_name}"
                elif clean_str.lower() in ("desktop", "documents", "downloads"):
                    user_val = f"{clean_str.capitalize()}/{def_name}"


            return True, f"User provided: {user_val}"
        except Exception as e:
            return False, f"Failed to obtain user input: {e}"

    tool = tool_registry.get(action)
    if not tool:
        return False, f"Tool '{action}' not found in registry."

    try:
        res = await tool.execute(**args)
        return res.success, str(res.output or res.error or "")
    except Exception as e:
        return False, f"Execution error: {e}"


def _propagate_user_param_input(param_name: str, user_val: str, plan: list[dict], state: NexusState):
    """Dynamically substitute user-provided parameter values across all subsequent pending plan steps.

    Writes to state["resolved_params"] which IS included in the returned state dict from
    executor_node, so the value survives LangGraph checkpointing across graph iterations.
    In-place plan mutation handles the current iteration; resolved_params handles future ones.
    """
    if not param_name or not user_val:
        return
    clean_val = str(user_val).strip()
    if clean_val.startswith("User provided: "):
        clean_val = clean_val[len("User provided: "):].strip()

    # Persist into state so the value is checkpointed and available to the next executor iteration
    if state.get("resolved_params") is None:
        state["resolved_params"] = {}
    state["resolved_params"][param_name] = clean_val  # type: ignore[index]

    # Also apply immediately to all still-pending plan steps in this iteration
    for st in plan:
        if st.get("status") == "pending":
            token = f"{{{{{param_name}}}}}"
            if st.get("title") and token in st["title"]:
                st["title"] = st["title"].replace(token, clean_val)
            if st.get("description") and token in st["description"]:
                st["description"] = st["description"].replace(token, clean_val)
            if st.get("args"):
                for k, v in list(st["args"].items()):
                    if isinstance(v, str) and token in v:
                        st["args"][k] = v.replace(token, clean_val)


def get_nexus_system_prompt() -> str:
    now_str = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M:%S %p")
    return f"""You are NEXUS, an autonomous AI execution and interaction runtime.
Current Local Date and Time: {now_str}.
Provide direct, concise, insightful, and accurate answers.
When presenting data or code, use clean markdown syntax."""


async def executor_node(state: NexusState) -> dict:
    from backend.agent.nodes.skill_executor import get_skill_execution_context
    
    plan = [dict(s) for s in state.get("plan", [])]
    goal = state.get("goal") or state.get("user_input", "")
    user_input = state.get("user_input", "")
    history: list[dict] = list(state.get("execution_history", []))
    tool_calls = state.get("tool_calls", []).copy()
    tool_results = state.get("tool_results", []).copy()
    observations = state.get("observations", []).copy()
    max_iterations = state.get("max_iterations", 20)
    current_idx = state.get("current_step", 0)
    
    # Determine which pill to use based on skill composition
    exec_context = get_skill_execution_context(plan)
    use_extension_pill = exec_context["use_extension_pill"]
    logger.info(
        "[SkillExecutor] Skill composition: %s | Using %s pill",
        exec_context["composition"],
        "extension" if use_extension_pill else "desktop"
    )

    # Hard stop: too many iterations
    if len(history) >= max_iterations:
        return {
            "execution_status": "failed",
            "goal_achieved": False,
            "error": f"Automation stopped: Reached maximum limit ({max_iterations} iterations) without completing goal.",
            "execution_history": history,
            "observations": observations + [f"Stopped: reached max {max_iterations} iterations."],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Determine if this is a web/browser task
    # ─────────────────────────────────────────────────────────────────────────
    has_browser_tools = any(s.get("tool") in BROWSER_TOOLS for s in plan)
    has_action_plan = bool(plan and not has_browser_tools)

    if has_action_plan:
        is_web_task = False
    else:
        is_web_task = (
            has_browser_tools or
            state.get("intent") == "web_automation" or
            any(w in goal.lower() for w in ("browser", "chrome", "website", "form", "http", "url", "web", "click", "fill"))
        )

    # ─────────────────────────────────────────────────────────────────────────
    # For non-web tasks with a clear plan: use plan steps directly (no DOM grounding needed)
    # ─────────────────────────────────────────────────────────────────────────
    if not is_web_task and current_idx < len(plan):
        step = dict(plan[current_idx])
        tool_name = step.get("tool", "ai_response")
        args = dict(step.get("args") or {})

        # Re-apply any parameters resolved in a prior graph iteration (survives checkpointing via resolved_params)
        prior_params = state.get("resolved_params") or {}
        if prior_params:
            token_re = re.compile(r"\{\{([^}]+)\}\}")
            for k, v in list(args.items()):
                if isinstance(v, str) and "{{" in v:
                    for param_name, param_val in prior_params.items():
                        v = v.replace(f"{{{{{param_name}}}}}", str(param_val))
                    args[k] = v
                    # Warn if any token is still unresolved
                    remaining = token_re.findall(v)
                    if remaining:
                        logger.warning("[Executor] Unresolved param token(s) in step '%s' arg '%s': %s", tool_name, k, remaining)

        step["status"] = "running"
        tool_calls.append({"step_id": step["id"], "tool": tool_name, "args": args})

        # If previous step was ask_user, inject the user's provided path into save / verify tools
        user_confirmed_path = None
        last_saved_path = None
        for hist_item in reversed(history):
            if hist_item.get("action") == "ask_user" and hist_item.get("success"):
                raw_res = str(hist_item.get("result", ""))
                if "User provided:" in raw_res:
                    user_confirmed_path = raw_res.split("User provided:", 1)[1].strip()
            elif hist_item.get("action") in ("spreadsheet_save", "document_save", "write_file") and hist_item.get("success"):
                meta = hist_item.get("metadata") or {}
                if meta.get("path"):
                    last_saved_path = meta.get("path")
                elif " to '" in str(hist_item.get("result", "")):
                    try:
                        last_saved_path = str(hist_item.get("result", "")).split(" to '", 1)[1].rstrip("'. ")
                    except Exception:
                        pass
                elif hist_item.get("args", {}).get("path"):
                    last_saved_path = hist_item["args"]["path"]

        if user_confirmed_path and tool_name in ("spreadsheet_save", "document_save"):
            if not args.get("path") or args.get("path") in ("<ask_user>", "user_choice", ""):
                args["path"] = user_confirmed_path

        # Always verify the exact directory and file that was saved, not a random path
        if last_saved_path and tool_name in ("spreadsheet_verify", "document_verify"):
            args["path"] = last_saved_path
        elif user_confirmed_path and tool_name in ("spreadsheet_verify", "document_verify"):
            args["path"] = user_confirmed_path

        if tool_name == "ai_response":
            explicit_answer = args.get("answer")
            if explicit_answer:
                answer = explicit_answer
                step["status"] = "completed"
                step["result"] = answer
                step["error"] = None
            else:
                api_key = get_groq_api_key()
                if api_key:
                    try:
                        llm = get_llm("fast", temperature=0.5)
                        res = await llm.ainvoke([
                            SystemMessage(content=get_nexus_system_prompt()),
                            HumanMessage(content=goal),
                        ])
                        answer = res.content.strip()
                        step["status"] = "completed"
                        step["result"] = answer
                        step["error"] = None
                    except Exception as e:
                        answer = f"Error: {e}"
                        step["status"] = "failed"
                        step["result"] = None
                        step["error"] = answer
                else:
                    answer = "No Groq API key configured."
                    step["status"] = "completed"
                    step["result"] = answer
                    step["error"] = None

            tool_results.append({"step_id": step["id"], "tool": tool_name, "output": answer, "success": step["status"] == "completed"})
        else:
            success, output = await _execute_single_action(tool_name, args)
            terminal_connector_auth_error = _is_terminal_connector_auth_error(tool_name, output) if not success else False
            if not success:
                reframing_count = state.get("reframing_count", 0)
                if terminal_connector_auth_error:
                    observations.append(f"[Connector] {tool_name} was denied; stopping without browser or desktop fallback.")
                elif reframing_count < 3:
                    try:
                        from backend.agent.skills.reframer import reframe_skill_steps
                        reframed = await reframe_skill_steps(
                            goal=goal,
                            user_input=user_input,
                            plan=plan,
                            current_idx=current_idx,
                            error_context=output or "Action execution failed",
                            history=history,
                            skill_id=state.get("skill_id"),
                            resolved_params=state.get("resolved_params"),
                        )
                        if reframed:
                            observations.append(f"[Skill Reframer] 🔄 Action '{tool_name}' failed ({output[:60]}). Reframed {len(reframed)} steps.")
                            new_plan = plan[:current_idx] + reframed
                            return {
                                "plan": new_plan,
                                "current_step": current_idx,
                                "tool_calls": tool_calls,
                                "tool_results": tool_results,
                                "observations": observations,
                                "execution_history": history,
                                "goal_achieved": False,
                                "execution_status": "executing",
                                "reframing_count": reframing_count + 1,
                                "resolved_params": state.get("resolved_params") or {},
                            }
                    except Exception as ref_exc:
                        logger.warning("[Executor] Non-web reframing failed: %s", ref_exc)

            step["status"] = "completed" if success else "failed"
            step["result"] = output if success else ""
            step["error"] = output if not success else None
            tool_results.append({"step_id": step["id"], "tool": tool_name, "output": output, "success": success})
            observations.append(f"{'✓' if success else '✗'} {step.get('title', tool_name)}: {output[:300]}")

            if tool_name == "ask_user" and success and args.get("parameter_name"):
                _propagate_user_param_input(args["parameter_name"], output, plan, state)

        plan[current_idx] = step

        history_entry = {
            "action": tool_name,
            "args": args,
            "result": step.get("result") or step.get("error") or "",
            "success": step["status"] == "completed",
            "url": "",
        }
        if step.get("result") and " to '" in str(step.get("result")):
            try:
                history_entry["metadata"] = {"path": str(step.get("result")).split(" to '", 1)[1].rstrip("'. ")}
            except Exception:
                pass
        history.append(history_entry)

        next_idx = current_idx + 1
        is_all_done = (next_idx >= len(plan))
        has_failed_steps = any(s.get("status") == "failed" for s in plan)
        terminal_failure = terminal_connector_auth_error if tool_name != "ai_response" else False

        return {
            "plan": plan,
            "current_step": next_idx,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "observations": observations,
            "execution_history": history,
            "goal_achieved": is_all_done and not has_failed_steps,
            "execution_status": "failed" if terminal_failure or (is_all_done and has_failed_steps) else "completed" if is_all_done else "observing",
            **({"error": output} if terminal_failure or (is_all_done and has_failed_steps) else {}),
            # Always checkpoint resolved_params so ask_user values survive graph iterations
            "resolved_params": state.get("resolved_params") or {},
        }


    # ─────────────────────────────────────────────────────────────────────────
    # WEB TASK: Full ReAct loop — Observe → Think → Act → Validate → Replan
    # ─────────────────────────────────────────────────────────────────────────

    # 1. OBSERVE: Inspect the live page
    if is_web_task and len(history) == 0:
        first_title = plan[0].get("title", "Starting automation...") if plan else "Starting automation..."
        asyncio.create_task(_fire_overlay("automation_start", {
            "task": goal,
            "total_steps": len(plan),
            "step": first_title,
        }))

    # Settle pause after navigation actions to let page load
    if history:
        last = history[-1]
        if last.get("action") in ("browser_click", "browser_navigate", "browser_press"):
            await asyncio.sleep(0.4)

    dom_before = await _get_live_page_state()
    dom = dom_before  # alias for readability
    current_url = dom.get("url", "")

    initial_dom = state.get("initial_dom")
    if not initial_dom and is_web_task:
        initial_dom = dom_before

    # 2. THINK: LLM decides next action based on real page state
    decision = await _react_decide(goal, dom, history, plan, is_web_task, current_idx)

    action = decision.get("action", "cannot_proceed")
    args = decision.get("args", {})
    reasoning = decision.get("reasoning", "")

    observations.append(f"[ReAct] {reasoning or action} | URL: {current_url[:60]}")

    # 3. HANDLE TERMINAL STATES
    if action == "goal_achieved":
        goal_lower = goal.lower()
        is_email_task = any(w in goal_lower for w in ("send email", "send mail", "compose email", "compose mail", "dispatch email"))
        is_form_task = any(w in goal_lower for w in ("create form", "google form", "new form", "build form"))

        # Sanity check 1: don't accept goal_achieved if we're still on a dashboard/home page
        DASHBOARD_PATTERNS = [
            "docs.google.com/forms/u/",
            "docs.google.com/document/u/",
            "docs.google.com/spreadsheets/u/",
            "drive.google.com",
            "calendar.google.com/calendar/r",
        ]
        if not is_email_task:
            DASHBOARD_PATTERNS.append("mail.google.com/#inbox")

        url_looks_like_dashboard = any(p in current_url for p in DASHBOARD_PATTERNS)
        too_few_actions = len(history) < 2

        # Sanity check 2: verify requested key entities from goal actually exist in the live DOM (only for form tasks)
        dom_dump = json.dumps(dom).lower() if dom else ""
        missing_entities = []
        if is_form_task:
            if "name" in goal_lower and "name" not in dom_dump:
                missing_entities.append("Name")
            if any(w in goal_lower for w in ("phone", "mobile", "contact number")) and not any(w in dom_dump for w in ("phone", "mobile", "contact")):
                missing_entities.append("Phone Number")
            if "email" in goal_lower and "email" not in dom_dump:
                missing_entities.append("Email")

        # Sanity check 3: are there pending plan action steps?
        pending_plan_steps = [
            s for i, s in enumerate(plan)
            if i >= current_idx and s.get("status") != "completed" and s.get("tool") in BROWSER_TOOLS
        ]

        if url_looks_like_dashboard and too_few_actions:
            observations.append(f"[ReAct] Overriding premature goal_achieved — still on dashboard: {current_url}")
            action = "browser_navigate"
            if "form" in goal.lower():
                args = {"url": "https://forms.new"}
            elif "doc" in goal.lower() or "document" in goal.lower():
                args = {"url": "https://docs.new"}
            elif "sheet" in goal.lower() or "spreadsheet" in goal.lower():
                args = {"url": "https://sheets.new"}
            elif "slide" in goal.lower() or "presentation" in goal.lower():
                args = {"url": "https://slides.new"}
        elif missing_entities:
            # Crucial requirement missing from live page — do NOT exit!
            observations.append(f"[ReAct] Rejecting premature goal_achieved — missing items in DOM: {missing_entities}")
            if current_idx < len(plan):
                s = plan[current_idx]
                action = s.get("tool", "browser_wait")
                args = s.get("args", {})
                reasoning = f"Recovering missing entity '{missing_entities[0]}' — executing {s.get('title')}"
        elif len(pending_plan_steps) >= 2 and len(history) < len(plan):
            # Still multiple planned action steps pending — do NOT exit early
            observations.append(f"[ReAct] Rejecting premature goal_achieved — {len(pending_plan_steps)} planned action steps remaining")
            if current_idx < len(plan):
                s = plan[current_idx]
                action = s.get("tool", "browser_wait")
                args = s.get("args", {})
                reasoning = f"Continuing planned milestone: {s.get('title')}"
        else:
            # ── Full goal validation: LLM + VLM dual-confirmation ──────────────
            val_msg = "Taking screenshot & verifying goal with VLM…"
            observations.append(f"[Validator] {val_msg}")
            if current_idx < len(plan):
                plan[current_idx]["description"] = val_msg
            asyncio.create_task(_fire_overlay("automation_update_step", {
                "step": val_msg,
                "step_index": current_idx,
                "total_steps": len(plan),
                "is_validation": True,
                "steps": [{"title": s.get("title", ""), "tool": s.get("tool", ""), "status": s.get("status", "pending")} for s in plan],
            }))

            screenshot_for_goal = await _take_cdp_screenshot()
            dom_for_goal = dom_before  # use the freshly observed dom

            goal_val = await validate_goal_completion(
                goal=goal,
                dom_final=dom_for_goal,
                screenshot_bytes=screenshot_for_goal,
                execution_history=history,
                initial_dom=initial_dom,
            )

            goal_check_count = state.get("goal_check_count", 0) + 1

            # ONLY declare success if the validator confirms the goal was passed!
            if goal_val.passed and goal_val.confidence >= 0.65:
                # Confirmed — stop overlay and declare success
                asyncio.create_task(_fire_overlay("automation_stop"))
                summary = args.get("summary", "Goal accomplished.")
                missing = goal_val.details.get("missing", [])
                if missing and goal_val.passed:
                    summary += f" (Verified: all requirements met. Validated by: {goal_val.tier})"
                observations.append(
                    f"[Validator] [Confirmed] Goal confirmed (conf={goal_val.confidence:.0%}): {goal_val.reason or 'All steps verified'}"
                )
                # Mark all plan steps as completed so no step is left dangling
                for s in plan:
                    if s.get("status") != "completed":
                        s["status"] = "completed"
                        if not s.get("result"):
                            s["result"] = "Completed successfully."
                return {
                    "plan": plan,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "observations": observations,
                    "execution_history": history,
                    "goal_achieved": True,
                    "initial_dom": initial_dom,
                    "execution_status": "completed",
                    "final_response": summary,
                    "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="completed", final_response=summary),
                    "goal_check_count": goal_check_count,
                }
            elif goal_check_count >= 3:
                # Validation rejected 3 times — DO NOT declare success if work is not complete!
                fail_msg = f"Task could not be verified as complete: {goal_val.reason or 'Requirements could not be confirmed on the page.'}"
                missing = goal_val.details.get("missing", [])
                if missing:
                    fail_msg += f" Missing items: {', '.join(str(m) for m in missing)}."
                print(f"\n{'!'*68}\n[NEXUS GOAL VERIFICATION FAILED]\n{fail_msg}\nDeclaring task incomplete.\n{'!'*68}\n", flush=True)
                observations.append(f"[Validator] [Incomplete] {fail_msg}")
                asyncio.create_task(_fire_overlay("automation_update_step", {
                    "step": "Task incomplete",
                    "error": fail_msg,
                }))
                return {
                    "plan": plan,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "observations": observations,
                    "execution_history": history,
                    "goal_achieved": False,
                    "initial_dom": initial_dom,
                    "execution_status": "completed",
                    "final_response": fail_msg,
                    "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=fail_msg),
                    "goal_check_count": goal_check_count,
                }
            else:
                # Validation rejected the goal_achieved claim — continue automation
                reason = goal_val.reason or "Goal not fully met yet."
                observations.append(
                    f"[Validator] [Rejected] goal_achieved rejected (conf={goal_val.confidence:.0%}, attempt={goal_check_count}): {reason}"
                )
                missing = goal_val.details.get("missing", [])
                if missing:
                    observations.append(f"[Validator] Still missing: {', '.join(str(m) for m in missing)}")
                # Let the ReAct loop continue — fall through to tool execution below
                action = "browser_inspect"
                args = {}
                reasoning = f"Verifying goal state: {reason[:100]}"


    if action == "cannot_proceed":
        reason = args.get("reason", "Agent cannot proceed with current page state.")
        reframing_count = state.get("reframing_count", 0)
        if reframing_count < 2:
            try:
                from backend.agent.skills.reframer import reframe_skill_steps
                asyncio.create_task(_fire_overlay("automation_update_step", {
                    "step": "Reframing steps with AI...",
                    "step_index": current_idx,
                    "total_steps": len(plan),
                }))
                reframed = await reframe_skill_steps(
                    goal=goal,
                    user_input=user_input,
                    plan=plan,
                    current_idx=current_idx,
                    error_context=reason,
                    dom=dom_before,
                    history=history,
                    skill_id=state.get("skill_id"),
                    resolved_params=state.get("resolved_params"),
                    task_id=state.get("task_id"),
                )
                if reframed:
                    observations.append(f"[Skill Reframer] 🔄 Cannot proceed ({reason[:60]}). Reframed {len(reframed)} steps to achieve goal.")
                    new_plan = plan[:current_idx] + reframed
                    history.append({
                        "action": "ai_reframing",
                        "args": {},
                        "result": f"Reframed {len(reframed)} steps",
                        "success": True,
                        "url": current_url,
                        "reasoning": "Plan reframed dynamically",
                    })
                    asyncio.create_task(_fire_overlay("automation_update_step", {
                        "step": new_plan[current_idx].get("title", "Executing reframed step"),
                        "step_index": current_idx,
                        "total_steps": len(new_plan),
                        "steps": [{"title": s.get("title", ""), "tool": s.get("tool", ""), "status": s.get("status", "pending")} for s in new_plan],
                    }))
                    return {
                        "plan": new_plan,
                        "current_step": current_idx,
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
                        "observations": observations,
                        "execution_history": history,
                        "goal_achieved": False,
                        "initial_dom": initial_dom,
                        "execution_status": "executing",
                        "reframing_count": reframing_count + 1,
                        "verification_retries": 0,
                    }
            except Exception as ref_exc:
                logger.warning("[Executor] Reframing on cannot_proceed failed: %s", ref_exc)

        # Release screen shield immediately so user has full control
        asyncio.create_task(_fire_overlay("automation_disable_shield"))
        asyncio.create_task(_fire_overlay("automation_update_step", {
            "step": "Stopped — issue encountered",
            "error": reason,
            "issues": [{"type": "blocked", "message": reason}],
        }))
        if current_idx < len(plan):
            plan[current_idx]["status"] = "failed"
            plan[current_idx]["error"] = reason
        return {
            "plan": plan,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "observations": observations,
            "execution_history": history,
            "goal_achieved": False,
            "execution_status": "failed",
            "error": reason,
            "final_response": f"Could not complete task: {reason}",
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=reason),
        }

    # 4. ACT: Execute the decided action
    tool_calls.append({"tool": action, "args": args, "reasoning": reasoning})

    # Update plan step UI + push overlay step text to browser
    step_desc = reasoning or (plan[current_idx].get("title") if current_idx < len(plan) else action)
    if current_idx < len(plan):
        plan[current_idx]["status"] = "running"
        plan[current_idx]["description"] = step_desc

    # Push overlay update to extension (fire-and-forget for regular steps)
    if action != "ask_user":
        asyncio.create_task(_fire_overlay("automation_update_step", {
            "step": step_desc,
            "step_index": current_idx,
            "total_steps": len(plan),
            "steps": [{"title": s.get("title", ""), "tool": s.get("tool", ""), "status": s.get("status", "pending")} for s in plan],
        }))

    # Capture DOM state BEFORE action (for validation diff)
    # dom_before is already captured above as part of OBSERVE

    success, result = await _execute_single_action(action, args)

    if action == "ask_user" and success and args.get("parameter_name"):
        _propagate_user_param_input(args["parameter_name"], result, plan, state)

    try:
        from backend.agent.tools.web_automation.logger import auto_logger
        auto_logger.log_step(
            step_idx=current_idx,
            total_steps=len(plan),
            action=action,
            args=args,
            reasoning=reasoning,
            result=result,
            success=success,
            url=current_url,
        )
    except Exception:
        pass

    # ── 4a. Validate the action outcome ─────────────────────────────────────
    validation_passed = True
    validation_conf = 1.0
    verification_retries = state.get("verification_retries", 0)

    if action in BROWSER_TOOLS and action not in SKIP_VALIDATION_ACTIONS:
        await asyncio.sleep(0.3)  # let SPA frameworks settle
        dom_after = await _get_live_page_state()

        # ── Tier 1: Check DOM diff validation first (zero latency) ──
        from backend.agent.tools.web_automation.validator import _dom_diff_validate, ValidationResult
        dom_diff_val = _dom_diff_validate(
            action=action,
            args=args,
            result=result,
            dom_before=dom_before,
            dom_after=dom_after,
        )

        if dom_diff_val is not None and dom_diff_val.passed:
            # Confirmed directly by live DOM inspection — skip screenshot & VLM delays!
            val = dom_diff_val
        else:
            # Ambiguous or failed DOM diff — fallback to screenshot + VLM validation
            screenshot_bytes: Optional[bytes] = None
            if success:
                val_msg = "Checking page state..."
                observations.append(f"[Validator] {val_msg}")
                screenshot_bytes = await _take_cdp_screenshot()

            val = await validate_step(
                action=action,
                args=args,
                result=result,
                dom_before=dom_before,
                dom_after=dom_after,
                screenshot_bytes=screenshot_bytes,
            )

        validation_passed = val.passed
        validation_conf = val.confidence

        try:
            from backend.agent.tools.web_automation.logger import auto_logger
            auto_logger.log_validation(
                action=action,
                passed=val.passed,
                confidence=val.confidence,
                tier=val.tier,
                reason=val.reason,
                suggestion=val.suggestion,
            )
        except Exception:
            pass

        logger.debug(
            "[Validator] action=%s passed=%s conf=%.2f tier=%s reason=%s",
            action, val.passed, val.confidence, val.tier, val.reason,
        )

        if not val.passed and val.confidence >= 0.65:
            # ── Adaptive Replanning ──────────────────────────────────────────
            verification_retries += 1
            observations.append(
                f"[Validator] [Failed] Step validation FAILED (conf={val.confidence:.0%}): {val.reason}"
            )
            success = False  # Mark as failed so plan doesn't advance

            if verification_retries <= 3 and val.suggestion:
                observations.append(f"[Validator] Replanning: {val.suggestion}")
                # Inject the corrective action as a signal for the next ReAct cycle
                # (the next loop iteration will pick up the modified dom and replan)
                history.append({
                    "action": "[validation_failure]",
                    "args": {"reason": val.reason, "suggestion": val.suggestion},
                    "result": f"Validator: {val.reason}",
                    "success": False,
                    "url": current_url,
                    "reasoning": "Automatic replanning triggered by VLM/DOM validator",
                })
            elif verification_retries > 3:
                fail_reason = (
                    f"Action '{action}' failed validation {verification_retries} times. "
                    f"Reason: {val.reason}. Suggestion: {val.suggestion}"
                )
                reframing_count = state.get("reframing_count", 0)
                if reframing_count < 2:
                    try:
                        from backend.agent.skills.reframer import reframe_skill_steps
                        asyncio.create_task(_fire_overlay("automation_update_step", {
                            "step": "Reframing steps with AI...",
                            "step_index": current_idx,
                            "total_steps": len(plan),
                        }))
                        reframed = await reframe_skill_steps(
                            goal=goal,
                            user_input=user_input,
                            plan=plan,
                            current_idx=current_idx,
                            error_context=fail_reason,
                            dom=dom_after,
                            history=history,
                            skill_id=state.get("skill_id"),
                            resolved_params=state.get("resolved_params"),
                            task_id=state.get("task_id"),
                        )
                        if reframed:
                            observations.append(f"[Skill Reframer] 🔄 Validation retries exceeded. Dynamically reframed {len(reframed)} steps.")
                            new_plan = plan[:current_idx] + reframed
                            history.append({
                                "action": "ai_reframing",
                                "args": {},
                                "result": f"Reframed {len(reframed)} steps",
                                "success": True,
                                "url": current_url,
                                "reasoning": "Plan reframed dynamically",
                            })
                            asyncio.create_task(_fire_overlay("automation_update_step", {
                                "step": new_plan[current_idx].get("title", "Executing reframed step"),
                                "step_index": current_idx,
                                "total_steps": len(new_plan),
                                "steps": [{"title": s.get("title", ""), "tool": s.get("tool", ""), "status": s.get("status", "pending")} for s in new_plan],
                            }))
                            return {
                                "plan": new_plan,
                                "current_step": current_idx,
                                "tool_calls": tool_calls,
                                "tool_results": tool_results,
                                "observations": observations,
                                "execution_history": history,
                                "goal_achieved": False,
                                "initial_dom": initial_dom,
                                "execution_status": "executing",
                                "reframing_count": reframing_count + 1,
                                "verification_retries": 0,
                            }
                    except Exception as ref_exc:
                        logger.warning("[Executor] Reframing on validation retries failed: %s", ref_exc)

                observations.append(
                    f"[Validator] [Exhausted] Validation retries exhausted — cancelling task: {fail_reason}"
                )
                # Release screen shield immediately so user has full interactive control
                asyncio.create_task(_fire_overlay("automation_disable_shield"))
                asyncio.create_task(_fire_overlay("automation_update_step", {
                    "step": "Task stopped — validation failed",
                    "error": fail_reason,
                    "issues": [{"type": "validation_failure", "message": fail_reason}],
                }))
                if current_idx < len(plan):
                    plan[current_idx]["status"] = "failed"
                    plan[current_idx]["error"] = fail_reason

                history.append({
                    "action": action,
                    "args": args,
                    "result": fail_reason[:300],
                    "success": False,
                    "url": current_url,
                    "reasoning": reasoning,
                    "validated": False,
                    "validation_confidence": val.confidence,
                })
                tool_results.append({
                    "tool": action,
                    "output": fail_reason,
                    "success": False,
                    "url": current_url,
                    "validated": False,
                })
                return {
                    "plan": plan,
                    "current_step": current_idx,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "observations": observations,
                    "execution_history": history,
                    "goal_achieved": False,
                    "initial_dom": initial_dom,
                    "execution_status": "failed",
                    "error": fail_reason,
                    "final_response": f"Automation cancelled due to persistent failure: {fail_reason}",
                    "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=fail_reason),
                    "verification_retries": verification_retries,
                }
        else:
            # Validation passed — reset retry counter
            verification_retries = 0

    # Record in history for the next iteration
    history.append({
        "action": action,
        "args": args,
        "result": result[:300],
        "success": success,
        "url": current_url,
        "reasoning": reasoning,
        "validated": validation_passed,
        "validation_confidence": validation_conf,
    })

    tool_results.append({
        "tool": action,
        "output": result,
        "success": success,
        "url": current_url,
        "validated": validation_passed,
    })

    # ── Step Advancement Logic ───────────────────────────────────────────────
    # A plan milestone only advances when:
    # 1. The action was NOT an auxiliary/preparatory action
    # 2. The execution was SUCCESSFUL
    # 3. Validation passed (or was skipped for non-browser actions)
    # 4. The model explicitly flagged step_completed=True, OR the action matched the step tool
    current_plan_tool = plan[current_idx].get("tool", "") if current_idx < len(plan) else ""
    current_title = plan[current_idx].get("title", "").lower() if current_idx < len(plan) else ""

    # An action is auxiliary ONLY if it was not explicitly the target tool or purpose of the current plan step
    is_auxiliary = (
        decision.get("is_auxiliary", False)
        or (action in ("browser_dismiss_popups", "browser_wait") and action != current_plan_tool and not any(w in current_title for w in ("wait", "pause", "delay", "load", "settle", "result", "dismiss", "popup", "modal")))
        or ("dismissing" in reasoning.lower() and not any(w in current_title for w in ("dismiss", "popup", "modal")))
        or ("popup" in reasoning.lower() and not any(w in current_title for w in ("dismiss", "popup", "modal")))
        or ("modal" in reasoning.lower() and not any(w in current_title for w in ("dismiss", "popup", "modal")))
    )
    step_completed = decision.get("step_completed", False)

    should_advance = False
    if success and validation_passed and not is_auxiliary and current_idx < len(plan):
        if step_completed or action == current_plan_tool:
            should_advance = True
        elif action == "browser_type" and any(w in current_title for w in ("type", "enter", "set", "title", "input", "write", "fill", "name", "phone", "email", "search", "message", "chat", "query", "subject", "body", "recipient", "cc", "bcc")):
            should_advance = True
        elif action == "browser_click" and any(w in current_title for w in ("click", "add", "press", "button", "open", "select", "create", "choose", "contact", "chat", "user", "send", "compose", "cc", "bcc", "submit")):
            should_advance = True
        elif action == "browser_wait" and any(w in current_title for w in ("wait", "load", "pause", "delay", "result", "settle")):
            should_advance = True
        elif action == "browser_inspect" and any(w in current_title for w in ("inspect", "check", "view", "interface", "examine", "see")):
            should_advance = True
        elif action == "ask_user":
            should_advance = True

    if should_advance and current_idx < len(plan):
        plan[current_idx]["status"] = "completed"
        plan[current_idx]["result"] = result
        plan[current_idx]["error"] = None
        next_plan_idx = current_idx + 1
    else:
        # Step still in progress (waiting, dismissed modal, retrying, or validation failed)
        if current_idx < len(plan):
            plan[current_idx]["status"] = "running"
            if not success:
                plan[current_idx]["error"] = result

        # Dynamic AI Reframing check: if action failed due to selector mismatch or repeated failure
        if not success:
            failed_attempts = sum(1 for h in history if not h.get("success") and h.get("action") == action)
            is_selector_missing = any(err_kw in str(result).lower() for err_kw in ("not found", "selector", "element not interactable", "timed out waiting for selector", "no element"))
            reframing_count = state.get("reframing_count", 0)
            if (failed_attempts >= 1 or is_selector_missing) and reframing_count < 2:
                try:
                    from backend.agent.skills.reframer import reframe_skill_steps
                    asyncio.create_task(_fire_overlay("automation_update_step", {
                        "step": "Reframing steps with AI...",
                        "step_index": current_idx,
                        "total_steps": len(plan),
                    }))
                    reframed = await reframe_skill_steps(
                        goal=goal,
                        user_input=user_input,
                        plan=plan,
                        current_idx=current_idx,
                        error_context=str(result),
                        dom=dom_after if 'dom_after' in locals() else dom_before,
                        history=history,
                        skill_id=state.get("skill_id"),
                        resolved_params=state.get("resolved_params"),
                        task_id=state.get("task_id"),
                    )
                    if reframed:
                        observations.append(f"[Skill Reframer] 🔄 Action '{action}' encountered issue ({str(result)[:60]}). Dynamically reframed {len(reframed)} steps.")
                        new_plan = plan[:current_idx] + reframed
                        history.append({
                            "action": "ai_reframing",
                            "args": {},
                            "result": f"Reframed {len(reframed)} steps to adapt to live page",
                            "success": True,
                            "url": current_url,
                            "reasoning": "Plan reframed dynamically",
                        })
                        asyncio.create_task(_fire_overlay("automation_update_step", {
                            "step": new_plan[current_idx].get("title", "Executing reframed step"),
                            "step_index": current_idx,
                            "total_steps": len(new_plan),
                            "steps": [{"title": s.get("title", ""), "tool": s.get("tool", ""), "status": s.get("status", "pending")} for s in new_plan],
                        }))
                        return {
                            "plan": new_plan,
                            "current_step": current_idx,
                            "tool_calls": tool_calls,
                            "tool_results": tool_results,
                            "observations": observations,
                            "execution_history": history,
                            "goal_achieved": False,
                            "initial_dom": initial_dom,
                            "execution_status": "executing",
                            "reframing_count": reframing_count + 1,
                            "verification_retries": 0,
                        }
                except Exception as ref_exc:
                    logger.warning("[Executor] Action failure reframing failed: %s", ref_exc)

        next_plan_idx = current_idx  # DO NOT ADVANCE!

    # Check if all plan steps are now settled or if we've completed the last step
    is_goal_done = (next_plan_idx >= len(plan)) or (plan and all(s.get("status") in ("completed", "failed") for s in plan))
    if is_goal_done:
        try:
            asyncio.create_task(_fire_overlay("automation_stop"))
        except Exception:
            pass

    return {
        "plan": plan,
        "current_step": next_plan_idx,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "observations": observations,
        "execution_history": history,
        "goal_achieved": is_goal_done,
        "initial_dom": initial_dom,
        "execution_status": "completed" if is_goal_done else "observing",
        "verification_retries": verification_retries,
    }
