"""
Recommendation Data Foundation Repository.
Extracts user activity signals: frequent categories, tools, applications,
workflow patterns, success/failure rates, and temporal metrics.
Strictly scoped to the authenticated user.
"""
from __future__ import annotations
import datetime
import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Task, TaskEvent


class RecommendationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_frequent_task_categories(
        self, user_id: uuid.UUID, limit: int = 5, days: int = 30
    ) -> list[dict[str, Any]]:
        """Return the user's most frequently executed task categories."""
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        stmt = (
            select(
                Task.task_type.label("category"),
                func.count(Task.id).label("count"),
                func.count().filter(Task.status == "completed").label("completed_count"),
            )
            .where(Task.user_id == user_id, Task.created_at >= since)
            .group_by(Task.task_type)
            .order_by(desc("count"))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [
            {
                "category": row.category,
                "count": row.count,
                "completed_count": row.completed_count,
                "success_rate": round(row.completed_count / row.count, 2) if row.count > 0 else 0.0,
            }
            for row in res
        ]

    async def get_frequent_tools(
        self, user_id: uuid.UUID, limit: int = 10, days: int = 30
    ) -> list[dict[str, Any]]:
        """Return the user's most frequently executed tools."""
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        stmt = (
            select(
                TaskEvent.tool_name.label("tool"),
                func.count(TaskEvent.id).label("count"),
                func.count().filter(TaskEvent.status == "success").label("success_count"),
            )
            .where(
                TaskEvent.user_id == user_id,
                TaskEvent.tool_name.isnot(None),
                TaskEvent.timestamp >= since,
            )
            .group_by(TaskEvent.tool_name)
            .order_by(desc("count"))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [
            {
                "tool": row.tool,
                "count": row.count,
                "success_count": row.success_count,
                "success_rate": round(row.success_count / row.count, 2) if row.count > 0 else 0.0,
            }
            for row in res
        ]

    async def get_frequent_applications(
        self, user_id: uuid.UUID, limit: int = 5, days: int = 30
    ) -> list[dict[str, Any]]:
        """Return the desktop and browser applications most frequently targeted by the user."""
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        stmt = (
            select(
                TaskEvent.application.label("application"),
                func.count(TaskEvent.id).label("count"),
            )
            .where(
                TaskEvent.user_id == user_id,
                TaskEvent.application.isnot(None),
                TaskEvent.timestamp >= since,
            )
            .group_by(TaskEvent.application)
            .order_by(desc("count"))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [{"application": row.application, "count": row.count} for row in res]

    async def get_recent_successful_tasks(
        self, user_id: uuid.UUID, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Return recent successfully verified tasks for quick re-run suggestions."""
        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.status == "completed")
            .order_by(desc(Task.completed_at))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        tasks = res.scalars().all()
        return [
            {
                "task_id": t.task_id_str,
                "prompt": t.user_prompt,
                "category": t.task_type,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "step_count": t.step_count,
            }
            for t in tasks
        ]

    async def get_recent_failed_tasks(
        self, user_id: uuid.UUID, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return recently failed workflows to identify friction points or recovery opportunities."""
        stmt = (
            select(Task)
            .where(Task.user_id == user_id, Task.status == "failed")
            .order_by(desc(Task.completed_at))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        tasks = res.scalars().all()
        return [
            {
                "task_id": t.task_id_str,
                "prompt": t.user_prompt,
                "error": t.error,
                "category": t.task_type,
            }
            for t in tasks
        ]

    async def get_activity_summary(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate high-level activity telemetry for the authenticated user."""
        categories = await self.get_frequent_task_categories(user_id, limit=5)
        tools = await self.get_frequent_tools(user_id, limit=6)
        apps = await self.get_frequent_applications(user_id, limit=4)
        recent_success = await self.get_recent_successful_tasks(user_id, limit=5)

        return {
            "top_categories": categories,
            "top_tools": tools,
            "top_applications": apps,
            "suggested_reruns": recent_success,
        }
