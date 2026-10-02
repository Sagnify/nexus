"""Permission Gate Node — halts execution for human confirmation if a step exceeds safe threshold."""
from __future__ import annotations
from backend.agent.state import NexusState
from backend.core.permissions import permission_engine
from backend.core.policies import RiskLevel


async def permission_gate_node(state: NexusState) -> dict:
    plan = state.get("plan", [])
    current_idx = state.get("current_step", 0)

    if current_idx >= len(plan):
        return {
            "permission_required": False,
            "permission_status": "none",
        }

    step = plan[current_idx]
    tool_name = step.get("tool", "")
    args = step.get("args", {})
    task_id = state.get("task_id", "default")

    # Per-step evaluation: do NOT use blanket approval from prior steps
    # Each step must be individually evaluated for risk
    risk, needs_approval = permission_engine.evaluate_step(tool_name, args)

    if needs_approval:
        desc = f"{step.get('title')}: {tool_name}({args})"
        permission_engine.register_pending(task_id, step["id"], tool_name, args, risk)
        return {
            "permission_required": True,
            "permission_status": "pending",
            "permission_items": [desc],
            "execution_status": "paused",
        }

    return {
        "permission_required": False,
        "permission_status": "none",
    }
