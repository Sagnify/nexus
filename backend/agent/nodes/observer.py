"""Observer node — inspects tool outputs and updates state context."""
from __future__ import annotations
from backend.agent.state import NexusState


async def observer_node(state: NexusState) -> dict:
    plan = state.get("plan", [])
    current_idx = state.get("current_step", 0)
    obs = state.get("observations", []).copy()

    # 1. Log latest tool call output if present
    tool_calls = state.get("tool_calls", [])
    tool_results = state.get("tool_results", [])
    if tool_calls and tool_results and len(tool_calls) == len(tool_results):
        last_call = tool_calls[-1]
        last_res = tool_results[-1]
        t_name = last_call.get("tool", "")
        t_success = last_res.get("success", False)
        t_out = str(last_res.get("output", ""))[:120]
        if t_success:
            obs.append(f"[Success] {t_name}: {t_out}")
        else:
            obs.append(f"[Tool Error] {t_name}: {t_out}")

    # 2. Reflect settled plan steps
    for s in plan:
        title = s.get("title", "Milestone")
        tool = s.get("tool", "")
        if s.get("status") == "completed":
            res_preview = str(s.get("result", ""))[:80]
            tag = f"[Completed] {title} ({tool}): {res_preview}"
            if tag not in obs:
                obs.append(tag)
        elif s.get("status") == "failed":
            err = s.get("error", "Failed")
            tag = f"[Failed] {title} ({tool}): {err}"
            if tag not in obs:
                obs.append(tag)

    return {
        "observations": obs,
        "execution_status": state.get("execution_status", "observing"),
    }
