"""Evaluator node — decides whether to continue plan, re-plan, or complete with live DOM intent verification."""
from __future__ import annotations
import json
import datetime
import time
from langchain_core.messages import SystemMessage, HumanMessage
from backend.agent.state import NexusState
from backend.agent.router.model_router import ainvoke_with_dynamic_switch, get_llm
from backend.core.config import get_groq_api_key, get_gemma_api_key
from backend.core.speech import generate_spoken_message, generate_spoken_brief


async def _record_skill_telemetry(
    state: NexusState,
    status: str,
    error_message: str | None = None,
) -> None:
    """Safely log skill execution telemetry if state was triggered by a learned skill."""
    skill_id_raw = state.get("skill_id")
    user_id_raw = state.get("user_id")
    if not skill_id_raw or not user_id_raw:
        return

    try:
        import uuid
        skill_id = uuid.UUID(str(skill_id_raw)) if not isinstance(skill_id_raw, uuid.UUID) else skill_id_raw
        user_id = uuid.UUID(str(user_id_raw)) if not isinstance(user_id_raw, uuid.UUID) else user_id_raw
        version_number = int(state.get("skill_version") or 1)
        plan = state.get("plan", [])
        failed_step_idx = None
        for i, s in enumerate(plan):
            if s.get("status") == "failed":
                failed_step_idx = i
                break

        from backend.database.session import AsyncSessionLocal
        from backend.database.repositories.skill_repo import SkillRepository
        async with AsyncSessionLocal() as session:
            repo = SkillRepository(session)
            await repo.record_execution(
                skill_id=skill_id,
                user_id=user_id,
                version_number=version_number,
                status=status,
                parameters_used=state.get("resolved_params") or {},
                step_results=[
                    {
                        "id": s.get("id"),
                        "title": s.get("title"),
                        "status": s.get("status"),
                        "result": s.get("result"),
                        "error": s.get("error"),
                    }
                    for s in plan
                ],
                error_message=error_message,
                failed_step_index=failed_step_idx,
            )
            await session.commit()
    except Exception as exc:
        import logging
        logging.getLogger("nexus.evaluator").warning("Skill execution telemetry recording skipped: %s", exc)


def get_synthesis_prompt() -> str:
    now_str = datetime.datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
    return f"""You are NEXUS, synthesizing completed execution results into a polished, definitive response for the user.
Current Local Date and Time: {now_str}.
Highlight key findings and outcomes using clean markdown formatting (tables, bold, lists).
Do not use emojis."""


async def _verify_web_automation(
    goal: str,
    user_input: str,
    plan: list[dict],
    history: list[dict],
) -> tuple[bool, str, dict]:
    """
    Thoroughly inspect the live DOM to verify if user's intent is fulfilled without errors.
    Returns (fulfilled, verification_summary, raw_details).
    """
    from backend.agent.tools.web_automation.extension_bridge import extension_bridge
    if not extension_bridge.is_connected():
        return True, "Extension bridge offline — skipped live DOM verification.", {}

    try:
        # 1. Thoroughly inspect DOM
        dom = await extension_bridge.send_command("inspect_dom", {"max_elements": 100}, timeout=6.0)
        current_url = dom.get("url", "")
        title = dom.get("title", "")
        elements = dom.get("interactive_elements", [])
        full_goal_text = f"{goal} {user_input}".lower()
        dom_dump = json.dumps(dom).lower()

        # Check if email sending task
        is_email_sending = any(w in full_goal_text for w in ("send email", "send mail", "compose email", "compose mail", "dispatch email"))
        if is_email_sending:
            has_send = any(h.get("action") == "browser_click" and any(w in str(h.get("args", {})).lower() for w in ("send", "submit")) for h in history)
            has_toast = any("message sent" in str(e.get("text") or e.get("aria_label") or "").lower() for e in elements)
            no_compose = not any("compose" in (e.get("aria_label") or "").lower() or "subjectbox" in (e.get("selector") or "").lower() for e in elements)
            if has_send and (has_toast or no_compose):
                summary = "Email successfully dispatched and confirmed on screen."
                return True, summary, {"fulfilled": True, "summary": summary, "elements_verified": ["Email Sent Confirmation"]}

        # Deterministic entity extraction & presence check (for form creation tasks)
        is_form_creation = any(w in full_goal_text for w in ("create form", "build form", "google form", "new form", "add field", "add question"))
        if is_form_creation:
            required_entities = []
            if "name" in full_goal_text:
                required_entities.append(("name", "Name"))
            if any(w in full_goal_text for w in ("phone", "mobile", "contact number")):
                required_entities.append(("phone", "Phone Number"))
            if "email" in full_goal_text:
                required_entities.append(("email", "Email"))
            if "address" in full_goal_text:
                required_entities.append(("address", "Address"))

            missing_required = []
            for key, display_name in required_entities:
                if key not in dom_dump:
                    missing_required.append(display_name)

            if missing_required:
                summary = f"Live DOM inspection detected missing required items: {', '.join(missing_required)}."
                data = {
                    "fulfilled": False,
                    "summary": summary,
                    "elements_verified": [d for k, d in required_entities if k in dom_dump],
                    "errors_found": [f"Missing required fields on page: {', '.join(missing_required)}"],
                    "missing_items": missing_required,
                    "corrective_instruction": f"The form is missing the '{', '.join(missing_required)}' question. Add or set the missing question title.",
                }
                return False, summary, data

        # 2. Format compact text snapshot of DOM
        dom_lines = [f"URL: {current_url}", f"Title: {title}", f"Interactive & Visible Elements ({len(elements)}):"]
        for el in elements[:70]:
            parts = [f"<{el.get('tag', '?')}>"]
            if el.get("id"): parts.append(f"#{el['id']}")
            if el.get("aria_label"): parts.append(f'aria="{el["aria_label"]}"')
            if el.get("placeholder"): parts.append(f'ph="{el["placeholder"]}"')
            if el.get("text"): parts.append(f'txt="{el["text"][:60]}"')
            if el.get("value"): parts.append(f'val="{el["value"][:60]}"')
            if el.get("role"): parts.append(f"role={el['role']}")
            dom_lines.append("  " + " ".join(parts))
        dom_snapshot = "\n".join(dom_lines)

        # 3. LLM verification prompt
        llm = get_llm("fast", temperature=0.1)
        plan_titles = [f"- {s.get('title')}: {s.get('result', '')}" for s in plan]
        prompt = f"""You are the NEXUS Intent Verification Engine.

USER GOAL: {goal or user_input}

EXECUTION PLAN MILESTONES:
{chr(10).join(plan_titles)}

LIVE POST-AUTOMATION DOM STATE:
{dom_snapshot}

YOUR TASK:
Carefully and thoroughly inspect the live DOM to verify if the user's intent has been PROPERLY and COMPLETELY fulfilled on this page without errors.
Check specifically:
1. Did the automation produce ALL required fields/questions/items (e.g. if user asked for Name and Phone, do BOTH exist as separate questions)?
2. Did any action accidentally overwrite an earlier field (e.g. Name was replaced by Phone Number)?
3. Are there any visible validation errors, alerts, or missing required fields?

Respond ONLY with a raw JSON object in this exact format:
{{
  "fulfilled": true or false,
  "summary": "<1-2 sentences explaining exactly what was verified on the live page>",
  "elements_verified": ["<item 1 found in DOM>", "<item 2 found in DOM>"],
  "errors_found": ["<any validation error or issue on page>"],
  "missing_items": ["<any missing requirement from user's goal>"],
  "corrective_instruction": "<if not fulfilled, what specific action must be taken to complete it>"
}}"""

        messages = [
            SystemMessage(content="You are a strict QA verification engine. Output only raw JSON."),
            HumanMessage(content=prompt),
        ]
        res = await ainvoke_with_dynamic_switch(messages, operation="fast", temperature=0.1)
        raw = res.content.strip()
        if "{" in raw:
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
        data = json.loads(raw)

        fulfilled = bool(data.get("fulfilled", False))
        summary = data.get("summary", "DOM verification complete.")
        return fulfilled, summary, data

    except Exception as e:
        return False, f"Live DOM verification error: {e}", {"corrective_instruction": "Inspect active page DOM and ensure all fields exist."}


async def evaluator_node(state: NexusState) -> dict:
    plan = state.get("plan", [])
    current_idx = state.get("current_step", 0)
    goal_achieved = state.get("goal_achieved", False)
    history = list(state.get("execution_history", []))
    max_iterations = state.get("max_iterations", 20)
    user_input = state.get("user_input", "")
    goal = state.get("goal") or user_input
    target_goal = goal
    observations = list(state.get("observations", []))
    has_api_key = bool(get_groq_api_key() or get_gemma_api_key())

    is_web_task = (
        any(s.get("tool", "").startswith("browser_") for s in plan)
        or any(h.get("action", "").startswith("browser_") for h in history)
        or state.get("intent") == "web_automation"
        or any(w in target_goal.lower() for w in ("browser", "chrome", "form", "google", "url", "web", "page", "click", "type", "fill"))
    )

    # ── Early-exit guards ─────────────────────────────────────────────────────
    # 1. If every step in the plan is already completed/failed, we're done —
    #    regardless of the goal_achieved flag (which is only set by the ReAct web loop).
    all_steps_settled = plan and all(s.get("status") in ("completed", "failed") for s in plan)
    # 2. If current_step has advanced past the end of the plan, we're done.
    step_exhausted = plan and current_idx >= len(plan)

    failed_steps = [step for step in plan if step.get("status") == "failed"]
    if all_steps_settled and failed_steps:
        error_message = state.get("error") or failed_steps[0].get("error") or "One or more actions failed."
        await _record_skill_telemetry(state, "failed", error_message)
        return {
            "execution_status": "failed",
            "goal_achieved": False,
            "error": error_message,
            "final_response": f"### Task Incomplete / Failed\n\n{error_message}",
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=error_message),
            "plan": plan,
        }

    if all_steps_settled or step_exhausted:
        # Fall through to synthesis/completion block below
        pass
    elif not goal_achieved:
        if current_idx < len(plan) and len(history) < max_iterations and state.get("execution_status") != "failed":
            return {
                "current_step": current_idx,
                "execution_status": "executing",
            }


        # Hit max iterations or executor reported failure without goal being achieved
        for s in plan:
            if s.get("status") not in ("completed", "failed"):
                s["status"] = "failed"
                if not s.get("error"):
                    s["error"] = "Halted before step could be reached."
        err_msg = state.get("error") or f"Automation stopped: Reached iteration limit ({max_iterations}) without completing goal."
        steps_summary_lines = []
        for s in plan:
            err_suffix = f" ({s['error']})" if s.get("error") else ""
            steps_summary_lines.append(f"- **{s.get('title')}**: {s.get('status')}{err_suffix}")
        await _record_skill_telemetry(state, "failed", err_msg)
        return {
            "execution_status": "failed",
            "goal_achieved": False,
            "error": err_msg,
            "final_response": f"### Task Incomplete / Failed\n\n{err_msg}\n\n**Steps Summary:**\n" + "\n".join(steps_summary_lines),
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=err_msg),
            "plan": plan,
        }

    # For non-web static plans, advance to next step if not yet at end
    if not is_web_task and not goal_achieved and not all_steps_settled:
        next_idx = current_idx + 1
        if next_idx < len(plan) and state.get("execution_status") != "completed":
            return {
                "current_step": next_idx,
                "execution_status": "executing",
            }

    # ─────────────────────────────────────────────────────────────────────────
    # All steps completed or goal claimed — VERIFY LIVE DOM BEFORE COMPLETING
    # ─────────────────────────────────────────────────────────────────────────
    action_tools = {
        "run_command", "write_file", "delete_file",
        "browser_navigate", "browser_inspect", "browser_click", "browser_type",
        "browser_select", "browser_press", "browser_wait", "browser_get_tabs",
        "browser_switch_tab", "browser_dismiss_popup", "browser_dismiss_popups", "browser_execute_js",
        "browser_get_source", "browser_scroll",
        "press_hotkey", "type_text", "press_key", "click_mouse", "activate_window", "inspect_screen"
    }
    has_media_tool = any(s.get("tool", "") in ("play_music", "media_control") for s in plan)
    is_web_task = not has_media_tool and (
        any(s.get("tool", "").startswith("browser_") for s in plan)
        or any(h.get("action", "").startswith("browser_") for h in history)
        or (state.get("intent") == "web_automation" and any(s.get("tool", "").startswith("browser_") for s in plan))
    )

    is_simple_open_intent = (
        (len(plan) == 1 and plan[0].get("tool") == "browser_navigate")
        or any(target_goal.lower().strip().startswith(p) for p in ("open ", "go to ", "visit ", "navigate to ", "launch "))
    )

    verification_badge = ""
    if is_web_task and history and not is_simple_open_intent:
        verification_attempts = state.get("verification_retries", 0)
        fulfilled, summary, details = await _verify_web_automation(
            target_goal, user_input, plan, history
        )

        # If verification failed and we have retries remaining (< 2), re-engage executor with corrective feedback!
        if not fulfilled and details.get("corrective_instruction") and verification_attempts < 2:
            corrective = details.get("corrective_instruction")
            missing = details.get("missing_items", [])
            errs = details.get("errors_found", [])
            observations.append(
                f"[Verification Failed] Missing: {', '.join(missing) if missing else 'intent unfulfilled'}. Corrective: {corrective}"
            )
            history.append({
                "action": "verification_feedback",
                "args": {"missing": missing, "errors": errs},
                "result": f"VERIFICATION FAILED: {corrective}",
                "success": False,
                "url": details.get("url", ""),
                "reasoning": f"Live DOM inspection detected unfulfilled goal: {corrective}",
            })
            return {
                "execution_status": "executing",
                "goal_achieved": False,
                "verification_retries": verification_attempts + 1,
                "execution_history": history,
                "observations": observations,
            }



            for s in plan:
                if s.get("status") not in ("completed", "failed"):
                    s["status"] = "failed"
                    if not s.get("error"):
                        s["error"] = "Intent verification failed on active page."
            fail_err = f"DOM Verification failed: {summary}"
            await _record_skill_telemetry(state, "failed", fail_err)
            return {
                "execution_status": "failed",
                "goal_achieved": False,
                "error": fail_err,
                "final_response": f"### Task Failed Verification\n\nLive DOM inspection detected that required elements are missing:\n- **Summary**: {summary}\n- **Errors**: {', '.join(details.get('errors_found', [])) or 'Incomplete elements on page'}",
                "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=fail_err),
                "plan": plan,
            }

        # Verification succeeded
        verified_items = details.get("elements_verified", [])
        status_badge = "**DOM Verification: Passed**"
        v_lines = [
            f"{status_badge}",
            f"- **Result**: {summary}",
        ]
        if verified_items:
            v_lines.append(f"- **Verified on Page**: {', '.join(verified_items)}")
        if details.get("errors_found"):
            v_lines.append(f"- **Errors Detected**: {', '.join(details['errors_found'])}")
    # ── Multi-Tier Outcome Validation Layer ─────────────────────────────────
    from backend.agent.validation.outcome_validator import validate_task_outcome
    outcome_val = await validate_task_outcome(state)

    start_time = state.get("start_time") or time.time()
    latency_ms = max(1, round((time.time() - start_time) * 1000))
    fast_path = state.get("fast_path_used")
    cache_hit = bool(state.get("cache_hit"))
    is_deterministic = bool(fast_path or cache_hit)
    llm_calls = 0 if is_deterministic else max(1, state.get("llm_calls_count") or 1)
    det_actions = state.get("deterministic_actions_count") or (len(plan) if is_deterministic else len([s for s in plan if s.get("tool") != "ai_response"]))
    tokens_saved = state.get("tokens_saved_estimate") or (2800 if is_deterministic else 0)

    if not outcome_val.passed:
        fail_msg = outcome_val.reason
        if outcome_val.corrective_suggestion:
            fail_msg += f"\n\n**Suggestion:** {outcome_val.corrective_suggestion}"
        await _record_skill_telemetry(state, "failed", fail_msg)
        return {
            "execution_status": "failed",
            "goal_achieved": False,
            "error": fail_msg,
            "final_response": f"### Task Failed Outcome Verification\n\n{fail_msg}",
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="failed", error=outcome_val.reason),
            "validation_passed": False,
            "validation_tier": outcome_val.tier,
            "validation_reason": outcome_val.reason,
            "llm_calls_count": llm_calls,
            "deterministic_actions_count": det_actions,
            "tokens_saved_estimate": tokens_saved,
            "latency_ms": latency_ms,
            "fast_path_used": fast_path,
            "cache_hit": cache_hit,
            "plan": plan,
        }

    # Store successful plan in plan_cache for future instant execution
    try:
        from backend.agent.router.plan_cache import store_successful_plan
        store_successful_plan(user_input, plan)
    except Exception:
        pass

    outcome_badge = f"\n\n✓ **Outcome Verified**: {outcome_val.reason}"
    if verification_badge:
        verification_badge += outcome_badge
    else:
        verification_badge = outcome_badge

    # All steps completed — synthesize final response
    api_key = get_groq_api_key()

    # Collect steps summary
    step_summaries = []
    for s in plan:
        res = s.get("result") or s.get("error") or "No output"
        step_summaries.append(f"- **{s.get('title')}** ({s.get('tool')}): {res}")
    results_text = "\n".join(step_summaries)

    # If the single step was ai_response, deep_research, or media tools, verify live status before completing
    if len(plan) == 1 and plan[0].get("tool") in ("ai_response", "deep_research", "play_music", "media_control"):
        res = plan[0].get("result") or plan[0].get("error") or "Task completed."
        is_media = plan[0].get("tool") in ("play_music", "media_control")
        is_failed = False
        if is_media and plan[0].get("tool") == "play_music":
            try:
                import re
                from backend.agent.tools.system.media_tool import _get_smtc_media_info
                smtc = _get_smtc_media_info()
                target_q = plan[0].get("args", {}).get("query", "") or user_input
                q_words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", target_q) if len(w) > 2]
                stop_words = {"song", "track", "music", "play", "from", "the", "and", "audio", "listen", "hits", "single"}
                q_tokens = [w for w in q_words if w not in stop_words] or q_words
                ttl = (smtc.get("title") or "").lower()
                art = (smtc.get("artist") or "").lower()
                alb = (smtc.get("album") or "").lower()
                matches = any(tok in ttl or tok in art or tok in alb for tok in q_tokens) if q_tokens else True
                if plan[0].get("status") == "failed" or (smtc.get("status") != "Playing") or not matches:
                    if "Verified" not in str(res):
                        is_failed = True
            except Exception:
                if plan[0].get("status") == "failed":
                    is_failed = True
        elif plan[0].get("status") == "failed":
            is_failed = True

        status = "failed" if is_failed else "completed"
        await _record_skill_telemetry(state, status, res if is_failed else None)
        return {
            "execution_status": status,
            "final_response": res,
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status=status, final_response=res if not is_failed else "", error=res if is_failed else None),
            "plan": plan,
            "validation_passed": outcome_val.passed,
            "validation_tier": outcome_val.tier,
            "validation_reason": outcome_val.reason,
            "llm_calls_count": llm_calls,
            "deterministic_actions_count": det_actions,
            "tokens_saved_estimate": tokens_saved,
            "latency_ms": latency_ms,
            "fast_path_used": fast_path,
            "cache_hit": cache_hit,
        }

    # If all executed steps were action tools, provide confirmation
    action_tools.update({"play_music", "media_control"})
    if all(s.get("tool") in action_tools for s in plan):
        lines = []
        for s in plan:
            title = s.get("title", "Action")
            tool = s.get("tool", "")
            args = s.get("args", {})
            out = s.get("result", "")
            err = s.get("error")
            if err:
                lines.append(f"Execution issue in {title}: {err}")
            elif tool == "browser_navigate":
                lines.append(f"Navigated browser to `{args.get('url')}`.")
            elif tool == "browser_inspect":
                lines.append(f"Inspected active webpage DOM and interactive elements.")
            elif tool in ("browser_dismiss_popup", "browser_dismiss_popups"):
                lines.append(f"Scanned and dismissed blocking popups/modals.")
            elif tool == "browser_click":
                target_desc = args.get("selector") or args.get("text") or args.get("xpath")
                lines.append(f"Clicked element `{target_desc}` in active browser tab.")
            elif tool == "browser_type":
                lines.append(f"Entered text into `{args.get('selector')}`.")
            elif tool == "browser_select":
                lines.append(f"Selected option in `{args.get('selector')}`.")
            elif tool == "browser_press":
                lines.append(f"Sent key press `{args.get('key', 'Enter')}`.")
            elif tool == "browser_wait":
                lines.append(f"Waited for browser page condition.")
            elif tool == "browser_get_tabs":
                lines.append(f"Discovered active browser tabs.")
                target = args.get('target_id') or args.get('tab_id') or args.get('url') or args.get('title') or "target tab"
                lines.append(f"Switched active tab to `{target}`.")
            elif tool == "browser_execute_js":
                lines.append(f"Evaluated JavaScript in browser console.")
            elif tool == "run_command":
                cmd = args.get("command", "")
                if "chrome" in cmd.lower() and "incognito" in cmd.lower():
                    lines.append("Google Chrome opened in Incognito mode.")
                elif "chrome" in cmd.lower():
                    lines.append("Google Chrome opened.")
                elif "edge" in cmd.lower() or "msedge" in cmd.lower():
                    lines.append("Microsoft Edge opened.")
                elif out and out != "(no output)":
                    lines.append(f"Executed `{cmd}`:\n```\n{out}\n```")
                else:
                    lines.append(f"Successfully executed `{cmd}`.")
            elif tool == "press_hotkey":
                keys = args.get("keys") or [args.get("shortcut", "")]
                lines.append(f"Pressed keyboard hotkey: `{' + '.join(keys)}`.")
            elif tool == "activate_window":
                lines.append(f"Brought `{args.get('title')}` to the foreground.")
            elif tool == "inspect_screen":
                lines.append("Inspected active screen state and window layout.")
            elif tool == "type_text":
                lines.append(f"Typed text into active window.")
            elif tool == "press_key":
                lines.append(f"Pressed key `{args.get('key')}`.")
            elif tool == "click_mouse":
                target = args.get("target")
                if target:
                    lines.append(f"Located and clicked '{target}' on screen.")
                else:
                    lines.append(f"Clicked mouse at ({args.get('x')}, {args.get('y')}).")
            elif tool == "write_file":
                lines.append(f"Successfully wrote file `{args.get('path')}`.")
            elif tool == "delete_file":
                lines.append(f"Successfully deleted file `{args.get('path')}`.")

        if verification_badge:
            lines.append(verification_badge.strip())

        final_text = "\n\n".join(lines)
        await _record_skill_telemetry(state, "completed")
        if state.get("reframing_count", 0) > 0 and state.get("skill_id") and state.get("user_id"):
            try:
                import asyncio
                from backend.agent.skills.reframer import heal_skill_in_background
                asyncio.create_task(
                    heal_skill_in_background(
                        user_id_str=str(state["user_id"]),
                        skill_id_str=str(state["skill_id"]),
                        executed_plan=plan,
                        change_summary=f"Auto-healed recipe: dynamically reframed on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    )
                )
            except Exception:
                pass
        return {
            "execution_status": "completed",
            "final_response": final_text,
            "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="completed", final_response=final_text),
            "validation_passed": True,
            "validation_tier": outcome_val.tier,
            "validation_reason": outcome_val.reason,
            "llm_calls_count": llm_calls,
            "deterministic_actions_count": det_actions,
            "tokens_saved_estimate": tokens_saved,
            "latency_ms": latency_ms,
            "fast_path_used": fast_path,
            "cache_hit": cache_hit,
            "plan": plan,
        }

    final_response = ""
    if has_api_key:
        try:
            messages = [
                SystemMessage(content=get_synthesis_prompt()),
                HumanMessage(content=f"User Request: {user_input}\n\nExecution Results:\n{results_text}")
            ]
            res = await ainvoke_with_dynamic_switch(messages, operation="fast", temperature=0.3)
            final_response = res.content.strip()
        except Exception:
            final_response = f"### Task Completed\n\n{results_text}"
    else:
        final_response = f"### Completed Successfully\n\n{results_text}"

    if verification_badge:
        final_response = f"{final_response}\n\n{verification_badge.strip()}"

    await _record_skill_telemetry(state, "completed")
    if state.get("reframing_count", 0) > 0 and state.get("skill_id") and state.get("user_id"):
        try:
            import asyncio
            from backend.agent.skills.reframer import heal_skill_in_background
            asyncio.create_task(
                heal_skill_in_background(
                    user_id_str=str(state["user_id"]),
                    skill_id_str=str(state["skill_id"]),
                    executed_plan=plan,
                    change_summary=f"Auto-healed recipe: dynamically reframed on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                )
            )
        except Exception:
            pass
    return {
        "execution_status": "completed",
        "final_response": final_response,
        "spoken_response": await generate_spoken_brief(goal, user_input, plan, execution_status="completed", final_response=final_response),
        "validation_passed": True,
        "validation_tier": outcome_val.tier,
        "validation_reason": outcome_val.reason,
        "llm_calls_count": llm_calls,
        "deterministic_actions_count": det_actions,
        "tokens_saved_estimate": tokens_saved,
        "latency_ms": latency_ms,
        "fast_path_used": fast_path,
        "cache_hit": cache_hit,
        "plan": plan,
    }
