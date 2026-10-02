"""Unit tests for SchedulerService background processing."""
import asyncio
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch, AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User, ScheduledTask, ScheduledTaskRun
from backend.database.repositories.scheduled_task_repo import ScheduledTaskRepository
from backend.services.scheduler_service import SchedulerService


class TestSchedulerService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.session_factory() as session:
            self.user = User(firebase_uid="uid_sched_svc", email="svc@nexus.ai", display_name="Svc User")
            session.add(self.user)
            await session.commit()
            self.user_id = self.user.id

        self.scheduler = SchedulerService(poll_interval_seconds=1)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_execute_reminder_completes_and_notifies(self):
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(seconds=10)

        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create_scheduled_task(
                user_id=self.user_id,
                name="Drink Water",
                prompt="Drink a glass of water",
                task_type="reminder",
                schedule_type="one_time",
                schedule_definition={"frequency": "once", "target_time": past_time.isoformat()},
                next_run_at=past_time,
            )
            await session.commit()
            task_id = task.id

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_safe_db():
            async with self.session_factory() as s:
                yield s

        with patch("backend.database.session.safe_db_context", mock_safe_db):
            with patch("backend.services.scheduler_service.send_user_notification", new_callable=AsyncMock) as mock_notify:
                await self.scheduler._execute_scheduled_task(task_id)

                mock_notify.assert_called_once()
                call_args = mock_notify.call_args[0]
                self.assertIn("Reminder", call_args[0])
                self.assertIn("Drink a glass of water", call_args[1])

        # Verify task is marked completed and one-time task is disabled
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            updated_task = await repo.get_by_id(task_id)
            self.assertFalse(updated_task.enabled)
            self.assertIsNone(updated_task.next_run_at)
            self.assertEqual(updated_task.total_runs, 1)

            runs = await repo.list_task_runs(task_id)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, "completed")
            self.assertIn("Delivered reminder", runs[0].result)

    async def test_missed_policy_skip(self):
        now = datetime.now(timezone.utc)
        # 1 hour ago -> exceeds 15 minutes threshold
        past_time = now - timedelta(hours=1)

        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create_scheduled_task(
                user_id=self.user_id,
                name="Generate Hourly Report",
                prompt="compile report",
                task_type="automation",
                schedule_type="recurring",
                schedule_definition={"frequency": "interval", "interval_minutes": 60},
                next_run_at=past_time,
                missed_policy="skip",
            )
            await session.commit()
            task_id = task.id

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_safe_db():
            async with self.session_factory() as s:
                yield s

        with patch("backend.database.session.safe_db_context", mock_safe_db):
            await self.scheduler._execute_scheduled_task(task_id)

        # Should be marked skipped and next_run_at advanced
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            runs = await repo.list_task_runs(task_id)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, "skipped")
            self.assertIn("Skipped per missed policy", runs[0].result)

