"""
Self-Healing & Dynamic Step Reframing Engine for NEXUS Skills and Execution Plans.
===================================================================================
When an execution step fails, is blocked, encounters an altered DOM, or cannot proceed,
this engine triggers AI-driven reframing to adapt the remaining workflow steps
to the live environment state.

CRITICAL DIRECTIVE: "Failing is the worst case ever possible."
The agent must dynamically observe, reframe, and successfully complete the user's goal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.router.model_router import ainvoke_with_dynamic_switch
from backend.agent.state import PlanStep
from backend.core.config import get_groq_api_key, get_gemma_api_key
from backend.core.policies import RiskLevel

logger = logging.getLogger("nexus.reframer")


def _format_dom_snapshot(dom: Optional[dict]) -> str:
    """Format compact, actionable summary of current page DOM for AI reframing."""
    if not isinstance(dom, dict) or not dom:
        return "No DOM available (offline or non-browser window)."

    url = dom.get("url", "")
    title = dom.get("title", "")
    elements = dom.get("interactive_elements") or []

    lines = [f"URL: {url}", f"Page Title: {title}", f"Interactive Elements ({len(elements)} found):"]
    for el in elements[:65]:
        parts = [f"<{el.get('tag', 'div')}"]
        if el.get("id"):
            parts.append(f'id="{el["id"]}"')
        if el.get("name"):
            parts.append(f'name="{el["name"]}"')
        if el.get("aria_label"):
            parts.append(f'aria-label="{el["aria_label"]}"')
        if el.get("placeholder"):
            parts.append(f'placeholder="{el["placeholder"]}"')
        if el.get("text"):
            parts.append(f'text="{el["text"][:60]}"')
        if el.get("role"):
            parts.append(f'role="{el["role"]}"')
        if el.get("selector"):
            parts.append(f'css="{el["selector"]}"')
        parts.append(">")
        lines.append("  " + " ".join(parts))

    return "\n".join(lines)


async def reframe_skill_steps(
    goal: str,
    user_input: str,
    plan: list[dict],
    current_idx: int,
    error_context: str,
    dom: Optional[dict] = None,
    history: Optional[list[dict]] = None,
    skill_name: Optional[str] = None,
    skill_id: Optional[str] = None,
    resolved_params: Optional[dict] = None,
    task_id: Optional[str] = None,
) -> list[PlanStep]:
    """
    Trigger the AI to reframe remaining steps after a step failure, blocked condition, or unexpected state.
    Returns the newly reframed PlanStep sequence to replace the pending steps.
    """
    logger.info(
        "[StepReframer] 🔄 Triggering AI reframing for '%s' at step %d/%d. Issue: %s",
        skill_name or goal[:30],
        current_idx + 1,
        len(plan),
        error_context[:100],
    )

    # 1. Summarize successfully completed steps
    completed_steps: list[str] = []
    for i, s in enumerate(plan[:current_idx]):
        if s.get("status") == "completed":
            tool = s.get("tool", "")
            args_str = json.dumps(s.get("args") or {})[:60]
            res_str = (s.get("result") or "")[:60]
            completed_steps.append(f"- Step {i+1} [{s.get('title')}]: {tool}({args_str}) -> {res_str}")

    completed_summary = "\n".join(completed_steps) if completed_steps else "None (failed at or before first action)"

    # 2. Summarize the problematic step
    failed_step = plan[current_idx] if current_idx < len(plan) else {}
    failed_summary = (
        f"Title: {failed_step.get('title', 'Unknown')}\n"
        f"Tool: {failed_step.get('tool', 'Unknown')}\n"
        f"Args: {json.dumps(failed_step.get('args', {}))}\n"
        f"Error: {error_context or failed_step.get('error', 'Execution blocked or selector not found')}"
    )

    # 3. Format DOM snapshot
    dom_text = _format_dom_snapshot(dom)

    # 4. Construct high-priority prompt
    system_prompt = """You are NEXUS's Autonomous Execution Reframer and Self-Healing Engine.
A skill workflow encountered a blocker or execution error.
CRITICAL MANDATE: FAILING IS THE WORST POSSIBLE OUTCOME AND IS STRICTLY FORBIDDEN.
You must adapt, reframe the plan steps, and achieve the user's goal completely.

Available Tools:
- browser_navigate: {"url": "<url>"}
- browser_click: {"selector": "<css_selector>", "text": "<text>"}
- browser_type: {"selector": "<css_selector>", "text": "<text>", "press_enter": true}
- browser_press: {"key": "Enter|Escape|Tab"}
- browser_wait: {"timeout_seconds": 2.0}
- browser_inspect: {}
- browser_scroll: {"y": 300}
- run_command: {"command": "<powershell_cmd>"}
- activate_window: {"window_title": "<title>"}
- click_mouse: {"target": "<text>"}
- type_text: {"text": "<text>"}

RULES:
1. Examine the CURRENT LIVE PAGE STATE and INTERACTIVE ELEMENTS. Use real selectors/text from the page!
2. If navigating directly to a search URL or webmail (e.g. 'https://mail.google.com' for email or 'https://www.youtube.com/results?search_query=...' for YouTube) is required, DO THAT FIRST!
3. Do NOT repeat steps that are already completed.
4. If typing into a search box, ALWAYS set "press_enter": true so the search executes immediately.
5. Return ONLY a valid JSON array of objects with keys: "title", "description", "tool", "args"."""

    user_prompt = f"""USER GOAL: {goal or user_input}
SKILL WORKFLOW: {skill_name or 'Learned Skill'}

STEPS ALREADY COMPLETED (DO NOT RE-RUN THESE):
{completed_summary}

FAILED / PROBLEMATIC STEP:
{failed_summary}

CURRENT LIVE PAGE STATE:
{dom_text}

Provide the reframed steps to achieve the goal without failing:"""

    reframed_steps: list[PlanStep] = []

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        raw = ""

        # Prefer Google Gemma: real-time streaming thoughts & fast JSON generation
        if get_gemma_api_key():
            try:
                from backend.agent.router.model_router import stream_gemma_with_thoughts
                content, thought = await stream_gemma_with_thoughts(
                    messages,
                    task_id=task_id,
                    temperature=0.1,
                    timeout=10.0,
                    response_json=True,
                )
                raw = content.strip()
            except Exception as gemma_exc:
                logger.warning("[StepReframer] Gemma stream failed (%s), falling back to router", gemma_exc)

        if not raw:
            res = await ainvoke_with_dynamic_switch(messages, operation="reasoning", temperature=0.1, per_attempt_timeout=15.0)
            raw = res.content.strip()

        # Extract JSON array
        json_str = ""
        if "[" in raw and "]" in raw:
            json_str = raw[raw.index("[") : raw.rindex("]") + 1]
        elif "{" in raw and "}" in raw:
            json_str = f"[{raw[raw.index('{') : raw.rindex('}') + 1]}]"

        if json_str:
            raw_list = json.loads(json_str)
            if isinstance(raw_list, list):
                for idx, item in enumerate(raw_list):
                    if not isinstance(item, dict):
                        continue
                    tool = item.get("tool") or "browser_click"
                    args = item.get("args") or {}
                    title = item.get("title") or f"Reframed Step {idx + 1}"
                    desc = item.get("description") or f"Adapted action to achieve {goal}"

                    reframed_steps.append({
                        "id": f"reframed-step-{uuid.uuid4().hex[:6]}",
                        "title": f"🔄 {title}",
                        "description": desc,
                        "tool": tool,
                        "args": args,
                        "risk_level": RiskLevel.SAFE.value,
                        "status": "pending",
                        "result": None,
                        "error": None,
                    })

    except Exception as exc:
        logger.warning("[StepReframer] LLM reframing call failed: %s. Using heuristic recovery.", exc)

    # 5. Deterministic heuristic fallback if LLM returned no steps
    if not reframed_steps:
        reframed_steps = _heuristic_recovery_steps(goal, user_input, dom, failed_step)

    logger.info("[StepReframer] ✅ Reframed into %d executable steps", len(reframed_steps))
    return reframed_steps


def _heuristic_recovery_steps(
    goal: str,
    user_input: str,
    dom: Optional[dict],
    failed_step: dict,
) -> list[PlanStep]:
    """Generate resilient deterministic steps when LLM is unavailable."""
    steps: list[PlanStep] = []
    text_corpus = f"{goal} {user_input}".lower()

    # Email sending recovery: if email/mail task and not on Gmail yet or step failed
    if any(w in text_corpus for w in ("email", "mail", "gmail", "compose")):
        curr_url = dom.get("url", "") if isinstance(dom, dict) else ""
        if "mail.google.com" not in curr_url:
            steps.append({
                "id": f"reframed-email-nav-{uuid.uuid4().hex[:6]}",
                "title": "🔄 Open Webmail (Gmail)",
                "description": "Navigate to Gmail to begin email composition",
                "tool": "browser_navigate",
                "args": {"url": "https://mail.google.com"},
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })
            steps.append({
                "id": f"reframed-email-wait-{uuid.uuid4().hex[:6]}",
                "title": "🔄 Wait for Gmail to Load",
                "description": "Allow webmail interface to settle",
                "tool": "browser_wait",
                "args": {"timeout_seconds": 3.0},
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })
        steps.append({
            "id": f"reframed-email-compose-{uuid.uuid4().hex[:6]}",
            "title": "🔄 Click Compose",
            "description": "Click the Compose button to start a new message",
            "tool": "browser_click",
            "args": {"selector": "div[role='button'][gh='cm'], [aria-label*='Compose' i]", "text": "Compose"},
            "risk_level": RiskLevel.SAFE.value,
            "status": "pending",
            "result": None,
            "error": None,
        })
        steps.append({
            "id": f"reframed-email-inspect-{uuid.uuid4().hex[:6]}",
            "title": "🔄 Inspect Compose Form",
            "description": "Inspect live compose fields to fill recipient, subject, and body",
            "tool": "browser_inspect",
            "args": {"max_elements": 60},
            "risk_level": RiskLevel.SAFE.value,
            "status": "pending",
            "result": None,
            "error": None,
        })
        return steps

    logger.info("[StepReframer] ✅ Reframed into %d executable steps", len(reframed_steps))
    return reframed_steps


def _heuristic_recovery_steps(
    goal: str,
    user_input: str,
    dom: Optional[dict],
    failed_step: dict,
) -> list[PlanStep]:
    """Generate resilient deterministic steps when LLM is unavailable."""
    steps: list[PlanStep] = []
    text_corpus = f"{goal} {user_input}".lower()

    # YouTube recovery: if YouTube search or video open
    if "youtube" in text_corpus:
        query = ""
        m = re.search(r"(?:youtube.*?(?:search|play|find|for|open)|search.*?on youtube)\s+['\"]?([^'\"]+)['\"]?", text_corpus)
        if m:
            query = m.group(1).strip()
        elif "play " in text_corpus:
            query = text_corpus.split("play ", 1)[1].replace("on youtube", "").strip()
        elif "open " in text_corpus:
            query = text_corpus.split("open ", 1)[1].replace("on youtube", "").strip()

        if query:
            import urllib.parse
            encoded = urllib.parse.quote_plus(query)
            steps.append({
                "id": f"reframed-yt-nav-{uuid.uuid4().hex[:6]}",
                "title": f"🔄 Open YouTube Search: '{query}'",
                "description": f"Directly navigate to search results for '{query}'",
                "tool": "browser_navigate",
                "args": {"url": f"https://www.youtube.com/results?search_query={encoded}"},
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })
            steps.append({
                "id": f"reframed-yt-wait-{uuid.uuid4().hex[:6]}",
                "title": "🔄 Wait for Results to Load",
                "description": "Allow YouTube search results to settle",
                "tool": "browser_wait",
                "args": {"timeout_seconds": 2.0},
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })
            steps.append({
                "id": f"reframed-yt-click-{uuid.uuid4().hex[:6]}",
                "title": "🔄 Play First Video Result",
                "description": "Click the primary video renderer thumbnail or title",
                "tool": "browser_click",
                "args": {
                    "selector": "ytd-video-renderer a#video-title, #contents ytd-video-renderer a#thumbnail",
                },
                "risk_level": RiskLevel.SAFE.value,
                "status": "pending",
                "result": None,
                "error": None,
            })
            return steps

    # General DOM fallback: if DOM has interactive elements matching the goal
    if isinstance(dom, dict) and dom.get("interactive_elements"):
        elements = dom["interactive_elements"]
        # Look for buttons or links matching words in goal
        goal_words = [w for w in text_corpus.split() if len(w) > 3 and w not in ("with", "that", "this", "from", "click", "open", "please")]
        for el in elements:
            el_text = (el.get("text") or el.get("aria_label") or "").lower()
            if any(w in el_text for w in goal_words):
                steps.append({
                    "id": f"reframed-dom-click-{uuid.uuid4().hex[:6]}",
                    "title": f"🔄 Click '{el.get('text') or el.get('aria_label')}'",
                    "description": "Targeting matching interactive element found in live DOM",
                    "tool": "browser_click",
                    "args": {"selector": el.get("selector") or f"text={el.get('text')}"},
                    "risk_level": RiskLevel.SAFE.value,
                    "status": "pending",
                    "result": None,
                    "error": None,
                })
                break

    if not steps:
        # Ultimate fallback: wait and inspect live DOM
        steps.append({
            "id": f"reframed-fallback-inspect-{uuid.uuid4().hex[:6]}",
            "title": "🔄 Inspect Live Page State",
            "description": "Re-reading page elements to determine next action",
            "tool": "browser_inspect",
            "args": {"max_elements": 80},
            "risk_level": RiskLevel.SAFE.value,
            "status": "pending",
            "result": None,
            "error": None,
        })

    return steps


async def heal_skill_in_background(
    user_id_str: str,
    skill_id_str: str,
    executed_plan: list[dict],
    change_summary: str = "Auto-healed steps after dynamic reframing",
) -> None:
    """
    Persist the successfully reframed execution plan back into the skill definition in the database.
    This ensures that subsequent replays of the skill use the working, healed recipe.
    """
    if not user_id_str or not skill_id_str or not executed_plan:
        return

    try:
        import uuid
        uid = uuid.UUID(str(user_id_str)) if isinstance(user_id_str, str) else user_id_str
        sid = uuid.UUID(str(skill_id_str)) if isinstance(skill_id_str, str) else skill_id_str

        # Convert executed plan steps to skill step format
        new_steps: list[dict[str, Any]] = []
        for s in executed_plan:
            tool = s.get("tool", "")
            args = s.get("args") or {}
            title = s.get("title", "").replace("🔄 ", "")

            action_type = "browser_click"
            if tool == "browser_navigate":
                action_type = "browser_navigate"
            elif tool == "browser_type":
                action_type = "browser_type"
            elif tool == "browser_press":
                action_type = "browser_press"
            elif tool == "browser_wait":
                action_type = "browser_wait"
            elif tool == "activate_window":
                action_type = "desktop_focus"
            elif tool == "click_mouse":
                action_type = "desktop_click"
            elif tool == "type_text":
                action_type = "desktop_type"
            elif tool == "run_command":
                action_type = "run_command"

            new_steps.append({
                "action_type": action_type,
                "title": title,
                "url": args.get("url"),
                "value": args.get("text") or args.get("key"),
                "selector_bundle": {
                    "cssPath": args.get("selector"),
                    "textAnchor": args.get("text"),
                } if args.get("selector") or args.get("text") else None,
                "metadata": args,
            })

        from backend.database.session import get_session_factory
        session_factory = get_session_factory()
        if not session_factory:
            return
        from backend.database.repositories.skill_repo import SkillRepository

        async with session_factory() as session:
            repo = SkillRepository(session)
            skill = await repo.get_by_id(sid, uid)
            if skill and skill.versions:
                latest_v = skill.versions[-1]
                latest_v.steps_json = new_steps
                latest_v.change_summary = change_summary
                skill.health_status = "healthy"
                skill.consecutive_failures = 0
                await session.commit()
                logger.info("[StepReframer] 💾 Auto-healed skill '%s' (v%s) with updated recipe", skill.name, latest_v.version_number)

    except Exception as exc:
        logger.warning("[StepReframer] Auto-heal skill persistence skipped: %s", exc)
