"""
Task and TaskEvent Repository.
Provides database access for task execution history, status updates, and event tracking.
Enforces strict user data ownership.
"""
from __future__ import annotations
import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import Task, TaskEvent
from backend.core.privacy import sanitize_value


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_task_id(self, task_id_str: str, user_id: uuid.UUID) -> Optional[Task]:
        """Fetch task by string identifier, enforcing user ownership."""
        stmt = (
            select(Task)
            .where(Task.task_id_str == task_id_str, Task.user_id == user_id)
            .options(selectinload(Task.events))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_id(self, task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Task]:
        """Fetch task by UUID primary key, enforcing user ownership."""
        stmt = (
            select(Task)
            .where(Task.id == task_id, Task.user_id == user_id)
            .options(selectinload(Task.events))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_user_tasks(
        self,
        user_id: uuid.UUID,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks belonging to a specific user, sorted latest first."""
        stmt = select(Task).where(Task.user_id == user_id)
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            stmt = stmt.where(Task.task_type == task_type)

        stmt = stmt.order_by(desc(Task.created_at)).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def upsert_task(
        self,
        task_id_str: str,
        user_id: uuid.UUID,
        user_prompt: str,
        goal: Optional[str] = None,
        task_type: str = "general",
        status: str = "running",
        model_used: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        started_at: Optional[datetime.datetime] = None,
    ) -> Task:
        """Insert a new task or update an existing task idempotently."""
        stmt = select(Task).where(Task.task_id_str == task_id_str, Task.user_id == user_id)
        res = await self.session.execute(stmt)
        task = res.scalar_one_or_none()

        clean_metadata = sanitize_value(metadata or {})
        now = datetime.datetime.now(datetime.timezone.utc)

        if task is None:
            task = Task(
                task_id_str=task_id_str,
                user_id=user_id,
                user_prompt=user_prompt,
                goal=goal,
                task_type=task_type,
                status=status,
                model_used=model_used,
                metadata_json=clean_metadata,
                started_at=started_at or now,
            )
            self.session.add(task)
        else:
            if goal:
                task.goal = goal
            if task_type:
                task.task_type = task_type
            if model_used:
                task.model_used = model_used
            if status:
                task.status = status
            merged_meta = {**(task.metadata_json or {}), **clean_metadata}
            task.metadata_json = merged_meta

        await self.session.flush()
        return task

    async def update_task_completion(
        self,
        task_id_str: str,
        user_id: uuid.UUID,
        status: str,
        final_response: Optional[str] = None,
        error: Optional[str] = None,
        step_count: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[Task]:
        """Mark task completed or failed with verified outcome."""
        stmt = select(Task).where(Task.task_id_str == task_id_str, Task.user_id == user_id)
        res = await self.session.execute(stmt)
        task = res.scalar_one_or_none()

        if task is None:
            return None

        task.status = status
        if final_response:
            task.final_response = final_response
        if error:
            task.error = error
        if step_count is not None:
            task.step_count = step_count
        task.completed_at = datetime.datetime.now(datetime.timezone.utc)

        if metadata:
            clean_meta = sanitize_value(metadata)
            task.metadata_json = {**(task.metadata_json or {}), **clean_meta}

        await self.session.flush()
        return task

    async def add_event(
        self,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        event_type: str,
        tool_name: Optional[str] = None,
        application: Optional[str] = None,
        status: str = "success",
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TaskEvent:
        """Append a structured, privacy-sanitized execution event."""
        clean_metadata = sanitize_value(metadata or {})
        event = TaskEvent(
            task_id=task_id,
            user_id=user_id,
            event_type=event_type,
            tool_name=tool_name,
            application=application,
            status=status,
            duration_ms=duration_ms,
            metadata_json=clean_metadata,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def delete_task(self, task_id_str: str, user_id: uuid.UUID) -> bool:
        """Delete task and associated events, enforcing user ownership."""
        stmt = delete(Task).where(Task.task_id_str == task_id_str, Task.user_id == user_id)
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0
