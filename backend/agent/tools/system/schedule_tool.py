"""
Schedule Task Tool for N.E.X.U.S.
Allows the agent to create and persist scheduled reminders and automated tasks.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.database.session import AsyncSessionLocal
from backend.database.repositories.scheduled_task_repo import ScheduledTaskRepository
from backend.core.firebase_auth import get_or_create_local_user
from backend.services.schedule_parser import calculate_next_run

logger = logging.getLogger("nexus.tools.schedule")


class ScheduleTaskTool(NexusTool):
    name = "schedule_task"
    description = (
        "Schedule a future task or recurring automation. "
        "Supports 'reminder' (notification) and 'automation' (autonomous N.E.X.U.S. task execution)."
    )
    risk_level = RiskLevel.SAFE

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short title for the scheduled task"},
                    "prompt": {"type": "string", "description": "Command or reminder text to execute/display"},
                    "task_type": {"type": "string", "enum": ["reminder", "automation"], "description": "Type of scheduled task"},
                    "schedule_type": {"type": "string", "enum": ["one_time", "recurring"], "description": "Schedule frequency type"},
                    "schedule_definition": {"type": "object", "description": "Normalized schedule parameters, e.g. {'frequency': 'daily', 'time': '09:00'}"},
                    "timezone": {"type": "string", "description": "IANA timezone string, e.g. 'Asia/Kolkata'"},
                    "missed_policy": {"type": "string", "enum": ["skip", "run_once"], "description": "Policy if system was offline when scheduled"},
                    "user_id": {"type": "string", "description": "Optional user ID to associate task with"},
                },
                "required": ["name", "prompt", "schedule_definition"],
            },
        }

    async def execute(
        self,
        name: str,
        prompt: str,
        schedule_definition: dict[str, Any],
        task_type: str = "reminder",
        schedule_type: str = "one_time",
        timezone: str = "Asia/Kolkata",
        missed_policy: str = "skip",
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            async with AsyncSessionLocal() as session:
                target_user_id = None
                if user_id:
                    try:
                        target_user_id = uuid.UUID(str(user_id))
                    except Exception:
                        pass

                if not target_user_id:
                    user = await get_or_create_local_user(session)
                    target_user_id = user.id

                next_run = calculate_next_run(schedule_type, schedule_definition, timezone)
                from backend.services.schedule_parser import schedule_parser
                _, norm_intent, exec_cfg = schedule_parser._extract_automation_metadata(
                    prompt, prompt, is_explicit_reminder=(task_type == "reminder")
                )

                repo = ScheduledTaskRepository(session)
                task = await repo.create_scheduled_task(
                    user_id=target_user_id,
                    name=name,
                    description=prompt,
                    prompt=prompt,
                    task_type=task_type,
                    schedule_type=schedule_type,
                    schedule_definition=schedule_definition,
                    timezone=timezone,
                    next_run_at=next_run,
                    missed_policy=missed_policy,
                    normalized_intent=norm_intent,
                    execution_config=exec_cfg,
                )
                await session.commit()

                next_str = next_run.strftime("%A, %B %d at %I:%M %p %Z") if next_run else "immediate"
                output = (
                    f"Successfully scheduled {task_type} '{name}'.\n"
                    f"• Next run: {next_str}\n"
                    f"• Prompt: {prompt}\n"
                    f"• ID: {task.id}"
                )
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"task_id": str(task.id), "next_run_at": next_run.isoformat() if next_run else None},
                )
        except Exception as exc:
            logger.error("ScheduleTaskTool failed: %s", exc)
            return ToolResult(success=False, output="", error=f"Failed to create scheduled task: {str(exc)}")

