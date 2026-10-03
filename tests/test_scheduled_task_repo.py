"""Unit tests for ScheduledTaskRepository enforcing user isolation, CRUD, and idempotency."""
import asyncio
from datetime import datetime, timezone, timedelta
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User, ScheduledTask, ScheduledTaskRun
from backend.database.repositories.scheduled_task_repo import ScheduledTaskRepository
from backend.api import scheduled_tasks as scheduled_tasks_api


class TestScheduledTaskRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.session_factory() as session:
            self.user1 = User(firebase_uid="uid_sched_1", email="user1@nexus.ai", display_name="User 1")
            self.user2 = User(firebase_uid="uid_sched_2", email="user2@nexus.ai", display_name="User 2")
            session.add_all([self.user1, self.user2])
            await session.commit()
            self.user1_id = self.user1.id
            self.user2_id = self.user2.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_create_and_list_scheduled_tasks(self):
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            now = datetime.now(timezone.utc)
            task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Morning Check",
                prompt="Check system status",
                task_type="automation",
                schedule_type="recurring",
                schedule_definition={"frequency": "daily", "time": "09:00"},
                timezone="Asia/Kolkata",
                next_run_at=now + timedelta(hours=1),
            )
            await session.commit()
            self.assertIsNotNone(task.id)
            self.assertEqual(task.name, "Morning Check")
            self.assertTrue(task.enabled)
            self.assertTrue(task.device_id)

            # List user 1 tasks
            user1_tasks = await repo.list_user_tasks(self.user1_id)
            self.assertEqual(len(user1_tasks), 1)
            self.assertEqual(user1_tasks[0].id, task.id)

            # User 2 isolation: user 2 should see 0 tasks
            user2_tasks = await repo.list_user_tasks(self.user2_id)
            self.assertEqual(len(user2_tasks), 0)

    async def test_due_tasks_and_task_lookup_are_device_scoped(self):
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            local_task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Local schedule",
                prompt="Check inbox",
                device_id="device-local",
                next_run_at=now - timedelta(minutes=1),
            )
            remote_task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Remote schedule",
                prompt="Check inbox elsewhere",
                device_id="device-remote",
                next_run_at=now - timedelta(minutes=1),
            )
            unbound_task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Legacy unbound schedule",
                prompt="Do not run on an arbitrary PC",
                device_id="unbound",
                next_run_at=now - timedelta(minutes=1),
            )
            await session.commit()

            due_here = await repo.get_due_tasks(now, device_id="device-local")
            self.assertEqual([task.id for task in due_here], [local_task.id])
            self.assertIsNone(await repo.get_by_id(remote_task.id, device_id="device-local"))
            self.assertNotIn(unbound_task.id, [task.id for task in due_here])

    async def test_owner_can_move_unbound_schedule_to_this_device(self):
        task = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=self.user1_id,
            device_id="unbound",
            enabled=False,
            schedule_type="recurring",
            schedule_definition={"frequency": "interval", "interval_minutes": 60},
            timezone="UTC",
            metadata_json={"device_binding_required": True},
            to_dict=lambda: {
                "id": str(task.id),
                "device_id": task.device_id,
                "enabled": task.enabled,
                "metadata": task.metadata_json,
            },
        )

        class FakeRepository:
            async def get_by_id(self, task_id, user_id=None):
                return task if task_id == task.id and user_id == self_user_id else None

            async def update_scheduled_task(self, task_id, user_id, **kwargs):
                for key, value in kwargs.items():
                    setattr(task, key, value)
                return task

        self_user_id = self.user1_id
        session = SimpleNamespace(commit=AsyncMock())
        repository = FakeRepository()

        with patch.object(scheduled_tasks_api, "ScheduledTaskRepository", return_value=repository):
            with patch.object(scheduled_tasks_api, "get_device_id", return_value="device-current"):
                with patch.object(scheduled_tasks_api, "calculate_next_run", return_value=datetime.now(timezone.utc)):
                    result = await scheduled_tasks_api.move_scheduled_task_to_this_device(
                        task.id,
                        SimpleNamespace(id=self.user1_id),
                        session,
                    )

        self.assertEqual(result["device_id"], "device-current")
        self.assertTrue(result["enabled"])
        self.assertNotIn("device_binding_required", result["metadata"])
        session.commit.assert_awaited_once()

    async def test_user_cannot_access_or_delete_other_user_task(self):
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Private Task",
                prompt="Secret prompt",
                task_type="reminder",
            )
            await session.commit()
            task_id = task.id

        # User 2 attempts to get by id with ownership enforcement
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            forbidden_task = await repo.get_by_id(task_id, user_id=self.user2_id)
            self.assertIsNone(forbidden_task)

            # User 2 attempts to delete
            deleted = await repo.delete_scheduled_task(task_id, user_id=self.user2_id)
            self.assertFalse(deleted)

            # User 1 can delete successfully
            deleted_by_owner = await repo.delete_scheduled_task(task_id, user_id=self.user1_id)
            self.assertTrue(deleted_by_owner)

    async def test_run_idempotency_and_overlap_protection(self):
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create_scheduled_task(
                user_id=self.user1_id,
                name="Scheduled Automation",
                prompt="Run tests",
                task_type="automation",
            )
            await session.commit()
            task_id = task.id

        scheduled_time = datetime(2026, 10, 2, 9, 0, 0, tzinfo=timezone.utc)

        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            run1 = await repo.create_run(
                scheduled_task_id=task_id,
                user_id=self.user1_id,
                scheduled_for=scheduled_time,
                status="running",
            )
            await session.commit()
            self.assertIsNotNone(run1.id)

            # Check overlap protection: task is currently running
            is_running = await repo.is_task_currently_running(task_id)
            self.assertTrue(is_running)

            # Idempotent call with same scheduled_for returns existing run
            run2 = await repo.create_run(
                scheduled_task_id=task_id,
                user_id=self.user1_id,
                scheduled_for=scheduled_time,
            )
            self.assertEqual(run1.id, run2.id)

            # Complete run
            await repo.update_run(run1.id, status="completed", completed_at=datetime.now(timezone.utc), result="All OK")
            await session.commit()

            # Now is_task_currently_running should be False
            is_running_after = await repo.is_task_currently_running(task_id)
            self.assertFalse(is_running_after)

