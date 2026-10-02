"""
Scheduled Task and ScheduledTaskRun Repository.
Provides database access for task scheduling, recurring definitions, and run executions.
Enforces strict user data ownership.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import ScheduledTask, ScheduledTaskRun


class ScheduledTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_scheduled_task(
        self,
        user_id: uuid.UUID,
        name: str,
        prompt: str,
        task_type: str = "reminder",
        schedule_type: str = "one_time",
        schedule_definition: Optional[dict[str, Any]] = None,
        timezone: str = "Asia/Kolkata",
        next_run_at: Optional[datetime.datetime] = None,
        description: Optional[str] = None,
        missed_policy: str = "skip",
        normalized_intent: Optional[dict[str, Any]] = None,
        execution_config: Optional[dict[str, Any]] = None,
        last_run_status: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> ScheduledTask:
        """Create and persist a new scheduled task."""
        task = ScheduledTask(
            user_id=user_id,
            name=name,
            description=description,
            task_type=task_type,
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_definition=schedule_definition or {},
            timezone=timezone,
            enabled=True,
            next_run_at=next_run_at,
            missed_policy=missed_policy,
            normalized_intent=normalized_intent or {},
            execution_config=execution_config or {},
            last_run_status=last_run_status,
            metadata_json=metadata_json or {},
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, task_id: uuid.UUID, user_id: Optional[uuid.UUID] = None) -> Optional[ScheduledTask]:
        """Fetch scheduled task by ID, optionally enforcing user ownership."""
        stmt = select(ScheduledTask).where(ScheduledTask.id == task_id)
        if user_id is not None:
            stmt = stmt.where(ScheduledTask.user_id == user_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_user_tasks(
        self,
        user_id: uuid.UUID,
        task_type: Optional[str] = None,
        enabled: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScheduledTask]:
        """List scheduled tasks for a user, sorted next_run_at ascending (nulls last)."""
        stmt = select(ScheduledTask).where(ScheduledTask.user_id == user_id)
        if task_type:
            stmt = stmt.where(ScheduledTask.task_type == task_type)
        if enabled is not None:
            stmt = stmt.where(ScheduledTask.enabled == enabled)

        stmt = stmt.order_by(
            ScheduledTask.enabled.desc(),
            ScheduledTask.next_run_at.asc().nulls_last(),
            desc(ScheduledTask.created_at)
        ).limit(limit).offset(offset)

        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_scheduled_task(
        self,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs: Any,
    ) -> Optional[ScheduledTask]:
        """Update fields of a user's scheduled task."""
        task = await self.get_by_id(task_id, user_id=user_id)
        if not task:
            return None

        for k, v in kwargs.items():
            if hasattr(task, k):
                setattr(task, k, v)

        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def delete_scheduled_task(self, task_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Delete a scheduled task belonging to a specific user."""
        stmt = delete(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user_id
        )
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def toggle_enabled(self, task_id: uuid.UUID, user_id: uuid.UUID, enabled: bool) -> Optional[ScheduledTask]:
        """Enable or pause a scheduled task."""
        return await self.update_scheduled_task(task_id, user_id, enabled=enabled)

    async def get_due_tasks(self, now: datetime.datetime, limit: int = 25) -> list[ScheduledTask]:
        """
        Fetch all tasks across users that are enabled and due for execution.
        """
        stmt = (
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled == True,
                ScheduledTask.next_run_at != None,
                ScheduledTask.next_run_at <= now,
            )
            .order_by(ScheduledTask.next_run_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_after_run(
        self,
        task_id: uuid.UUID,
        last_run_at: datetime.datetime,
        next_run_at: Optional[datetime.datetime],
        success: bool,
        status_override: Optional[str] = None,
    ) -> Optional[ScheduledTask]:
        """
        Advance state of task after execution.
        If schedule_type is 'one_time', disable it automatically.
        """
        task = await self.get_by_id(task_id)
        if not task:
            return None

        task.last_run_at = last_run_at
        task.total_runs = (task.total_runs or 0) + 1
        task.last_run_status = status_override or ("completed" if success else "failed")
        if success:
            task.consecutive_failures = 0
        else:
            task.consecutive_failures = (task.consecutive_failures or 0) + 1

        if task.schedule_type == "one_time" or not next_run_at:
            task.enabled = False
            task.next_run_at = None
        else:
            task.next_run_at = next_run_at

        await self.session.flush()
        await self.session.refresh(task)
        return task

    # =========================================================================
    # Run Management
    # =========================================================================

    async def create_run(
        self,
        scheduled_task_id: uuid.UUID,
        user_id: uuid.UUID,
        scheduled_for: datetime.datetime,
        execution_id: Optional[str] = None,
        status: str = "pending",
        worker_id: Optional[str] = None,
        claimed_at: Optional[datetime.datetime] = None,
        artifacts: Optional[list[Any]] = None,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> Optional[ScheduledTaskRun]:
        """
        Create run record. Enforces idempotency via unique (task_id, scheduled_for).
        """
        # Check if already exists for this exact time
        stmt = select(ScheduledTaskRun).where(
            ScheduledTaskRun.scheduled_task_id == scheduled_task_id,
            ScheduledTaskRun.scheduled_for == scheduled_for,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        run = ScheduledTaskRun(
            scheduled_task_id=scheduled_task_id,
            user_id=user_id,
            scheduled_for=scheduled_for,
            execution_id=execution_id,
            status=status,
            worker_id=worker_id,
            claimed_at=claimed_at,
            artifacts=artifacts or [],
            metadata_json=metadata_json or {},
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def claim_pending_run(
        self,
        run_id: uuid.UUID,
        worker_id: str,
        execution_id: str,
        now: Optional[datetime.datetime] = None,
    ) -> Optional[ScheduledTaskRun]:
        """
        Atomic task claim: updates status to 'running' iff status is currently 'pending'.
        Guarantees that multiple concurrent workers cannot claim the same run.
        """
        claim_time = now or datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            update(ScheduledTaskRun)
            .where(
                ScheduledTaskRun.id == run_id,
                ScheduledTaskRun.status == "pending",
            )
            .values(
                status="running",
                worker_id=worker_id,
                claimed_at=claim_time,
                started_at=claim_time,
                execution_id=execution_id,
            )
        )
        res = await self.session.execute(stmt)
        if (res.rowcount or 0) > 0:
            await self.session.flush()
            return await self.get_run_by_id(run_id)
        return None

    async def get_run_by_id(self, run_id: uuid.UUID) -> Optional[ScheduledTaskRun]:
        stmt = select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_run_by_execution_id(self, execution_id: str) -> Optional[ScheduledTaskRun]:
        stmt = select(ScheduledTaskRun).where(ScheduledTaskRun.execution_id == execution_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_run(
        self,
        run_id: uuid.UUID,
        status: str,
        started_at: Optional[datetime.datetime] = None,
        completed_at: Optional[datetime.datetime] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
        artifacts: Optional[list[Any]] = None,
        worker_id: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> Optional[ScheduledTaskRun]:
        """Update status, timing, and result of a run."""
        run = await self.get_run_by_id(run_id)
        if not run:
            return None

        run.status = status
        if started_at:
            run.started_at = started_at
        if completed_at:
            run.completed_at = completed_at
        if result is not None:
            run.result = result
        if error is not None:
            run.error = error
        if artifacts is not None:
            run.artifacts = artifacts
        if worker_id is not None:
            run.worker_id = worker_id
        if metadata_json:
            current_meta = run.metadata_json or {}
            current_meta.update(metadata_json)
            run.metadata_json = current_meta

        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def is_task_currently_running(self, scheduled_task_id: uuid.UUID) -> bool:
        """Overlap protection: check if there is an active running run."""
        stmt = select(func.count(ScheduledTaskRun.id)).where(
            ScheduledTaskRun.scheduled_task_id == scheduled_task_id,
            ScheduledTaskRun.status.in_(["running", "pending"]),
        )
        res = await self.session.execute(stmt)
        return (res.scalar() or 0) > 0

    async def list_task_runs(
        self,
        scheduled_task_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        limit: int = 30,
    ) -> list[ScheduledTaskRun]:
        """List execution history for a scheduled task."""
        stmt = select(ScheduledTaskRun).where(ScheduledTaskRun.scheduled_task_id == scheduled_task_id)
        if user_id:
            stmt = stmt.where(ScheduledTaskRun.user_id == user_id)
        stmt = stmt.order_by(desc(ScheduledTaskRun.scheduled_for)).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

