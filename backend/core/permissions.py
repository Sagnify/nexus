"""Permission engine for NEXUS — evaluates risk levels and enforces human-in-the-loop gates."""
from __future__ import annotations
from typing import Optional
from backend.core.policies import RiskLevel, classify_command, classify_file_op, requires_permission


class PermissionEngine:
    """Evaluates operations and enforces human-in-the-loop confirmation policies."""

    def __init__(self, auto_approve_safe: bool = True):
        self.auto_approve_safe = auto_approve_safe
        self._pending_requests: dict[str, dict] = {}

    def evaluate_step(self, tool_name: str, args: dict) -> tuple[RiskLevel, bool]:
        """
        Returns (RiskLevel, requires_approval).
        """
        risk = RiskLevel.SAFE

        if tool_name == "run_command":
            cmd = args.get("command", "")
            risk = classify_command(cmd)
        elif tool_name in ("write_file", "delete_file"):
            op = "delete" if tool_name == "delete_file" else "write"
            risk = classify_file_op(op)
        elif tool_name in ("read_file", "list_directory", "search_files"):
            risk = RiskLevel.READ_ONLY
        elif tool_name.startswith("browser_"):
            risk = RiskLevel.NETWORK
        elif tool_name in ("gmail_send_email", "send_email", "email_send"):
            risk = RiskLevel.PRIVILEGED
            return risk, True
        else:
            try:
                from backend.agent.tools.registry import tool_registry
                reg_tool = tool_registry.get(tool_name)
                if reg_tool and hasattr(reg_tool, "risk_level"):
                    risk = reg_tool.risk_level
            except Exception:
                pass

        # High risk requires human permission
        need_approval = requires_permission(risk)
        if risk in (RiskLevel.MODIFYING, RiskLevel.NETWORK, RiskLevel.DESTRUCTIVE) and not self.auto_approve_safe:
            need_approval = True

        return risk, need_approval


    def register_pending(self, task_id: str, step_id: str, tool_name: str, args: dict, risk: RiskLevel) -> dict:
        req = {
            "task_id": task_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk.value,
            "status": "pending",
        }
        self._pending_requests[f"{task_id}:{step_id}"] = req
        return req

    def resolve_permission(self, task_id: str, step_id: str, approved: bool) -> Optional[dict]:
        key = f"{task_id}:{step_id}"
        if key in self._pending_requests:
            req = self._pending_requests.pop(key)  # Remove resolved entry — prevents unbounded growth
            req["status"] = "approved" if approved else "rejected"
            return req
        return None

    def get_pending(self, task_id: str) -> list[dict]:
        return [req for k, req in self._pending_requests.items() if req["task_id"] == task_id and req["status"] == "pending"]

    def purge_resolved(self) -> int:
        """Remove all resolved (approved/rejected) entries from the pending registry.
        Called opportunistically to cap memory use in long-running sessions.
        """
        stale = [k for k, req in self._pending_requests.items() if req.get("status") in ("approved", "rejected")]
        for k in stale:
            self._pending_requests.pop(k, None)
        return len(stale)


permission_engine = PermissionEngine()
