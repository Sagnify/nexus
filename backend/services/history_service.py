"""
Dual Persistence & History Service for NEXUS.
Saves task states, executions, and structured events to PostgreSQL when available.
Guarantees 100% failure isolation: any database or network issue is logged safely
while local operation continues unaffected.
"""
from __future__ import annotations
import asyncio
import datetime
import logging
import uuid
from typing import Any, Optional

from backend.database.session import safe_db_context
from backend.database.repositories.task_repo import TaskRepository
from backend.core.privacy import detect_application, normalize_task_category, sanitize_value

logger = logging.getLogger("nexus.persistence")


class HistoryPersistenceService:
    @staticmethod
    def persist_task_start_bg(
        task_id_str: str,
        user_id: Optional[uuid.UUID],
        user_prompt: str,
        goal: Optional[str] = None,
        intent: Optional[str] = None,
        model_used: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Fire-and-forget task start persistence."""
        if not user_id:
            return
        asyncio.create_task(
            HistoryPersistenceService._persist_task_start(
                task_id_str, user_id, user_prompt, goal, intent, model_used, metadata
            )
        )

    @staticmethod
    async def _persist_task_start(
        task_id_str: str,
        user_id: uuid.UUID,
        user_prompt: str,
        goal: Optional[str] = None,
        intent: Optional[str] = None,
        model_used: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        try:
            category = normalize_task_category(intent, user_prompt)
            async with safe_db_context() as session:
                if session is None:
                    return
                repo = TaskRepository(session)
                task = await asyncio.wait_for(
                    repo.upsert_task(
                        task_id_str=task_id_str,
                        user_id=user_id,
                        user_prompt=user_prompt,
                        goal=goal,
                        task_type=category,
                        status="running",
                        model_used=model_used,
                        metadata=metadata,
                    ),
                    timeout=5.0,
                )
                await asyncio.wait_for(
                    repo.add_event(
                        task_id=task.id,
                        user_id=user_id,
                        event_type="task_started",
                        application=detect_application(intent or "General"),
                        status="success",
                        metadata={"goal": goal, "intent": intent},
                    ),
                    timeout=5.0,
                )
        except Exception as exc:
            logger.debug(f"[Persistence] Background task start write skipped/transient: {exc}")

    @staticmethod
    def persist_step_event_bg(
        task_id_str: str,
        user_id: Optional[uuid.UUID],
        tool_name: str,
        event_type: str = "tool_executed",
        status: str = "success",
        args: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Fire-and-forget tool/step event persistence."""
        if not user_id:
            return
        asyncio.create_task(
            HistoryPersistenceService._persist_step_event(
                task_id_str, user_id, tool_name, event_type, status, args, duration_ms, metadata
            )
        )

    @staticmethod
    async def _persist_step_event(
        task_id_str: str,
        user_id: uuid.UUID,
        tool_name: str,
        event_type: str = "tool_executed",
        status: str = "success",
        args: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        try:
            async with safe_db_context() as session:
                if session is None:
                    return
                repo = TaskRepository(session)
                task = await asyncio.wait_for(repo.get_by_task_id(task_id_str, user_id), timeout=5.0)
                if not task:
                    return

                app = detect_application(tool_name, args)
                event_meta = {"args": sanitize_value(args or {})}
                if metadata:
                    event_meta.update(sanitize_value(metadata))

                await asyncio.wait_for(
                    repo.add_event(
                        task_id=task.id,
                        user_id=user_id,
                        event_type=event_type,
                        tool_name=tool_name,
                        application=app,
                        status=status,
                        duration_ms=duration_ms,
                        metadata=event_meta,
                    ),
                    timeout=5.0,
                )
        except Exception as exc:
            logger.debug(f"[Persistence] Background step event write skipped/transient: {exc}")

    @staticmethod
    def persist_task_completion_bg(
        task_id_str: str,
        user_id: Optional[uuid.UUID],
        status: str,
        final_response: Optional[str] = None,
        error: Optional[str] = None,
        step_count: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Fire-and-forget task completion / failure persistence."""
        if not user_id:
            return
        asyncio.create_task(
            HistoryPersistenceService._persist_task_completion(
                task_id_str, user_id, status, final_response, error, step_count, metadata
            )
        )

    @staticmethod
    async def _persist_task_completion(
        task_id_str: str,
        user_id: uuid.UUID,
        status: str,
        final_response: Optional[str] = None,
        error: Optional[str] = None,
        step_count: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        try:
            async with safe_db_context() as session:
                if session is None:
                    return
                repo = TaskRepository(session)
                task = await asyncio.wait_for(
                    repo.update_task_completion(
                        task_id_str=task_id_str,
                        user_id=user_id,
                        status=status,
                        final_response=final_response,
                        error=error,
                        step_count=step_count,
                        metadata=metadata,
                    ),
                    timeout=5.0,
                )
                if task:
                    await asyncio.wait_for(
                        repo.add_event(
                            task_id=task.id,
                            user_id=user_id,
                            event_type="task_completed" if status == "completed" else "task_failed",
                            status="success" if status == "completed" else "failed",
                            metadata={"error": error} if error else None,
                        ),
                        timeout=5.0,
                    )
        except Exception as exc:
            logger.debug(f"[Persistence] Background task completion write skipped/transient: {exc}")


history_service = HistoryPersistenceService()
