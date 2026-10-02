"""
Tests for Data Ownership Isolation, Privacy Redaction, and Resilient Storage.
"""
import asyncio
import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User
from backend.database.repositories.task_repo import TaskRepository
from backend.core.privacy import sanitize_value, detect_application, normalize_task_category


class TestDatabaseIsolationAndPrivacy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        # Seed two distinct users
        async with self.session_factory() as session:
            self.user_a = User(firebase_uid="uid_alice", email="alice@test.com", display_name="Alice")
            self.user_b = User(firebase_uid="uid_bob", email="bob@test.com", display_name="Bob")
            session.add_all([self.user_a, self.user_b])
            await session.commit()
            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_user_ownership_isolation(self):
        """User A must NOT be able to view or query tasks created by User B."""
        async with self.session_factory() as session:
            repo = TaskRepository(session)
            # Create a task for User B
            task_b = await repo.upsert_task(
                task_id_str="task_bob_secret",
                user_id=self.user_b_id,
                user_prompt="Analyze Bob's private financial sheet",
                task_type="spreadsheet_analysis",
                status="completed",
            )
            await session.commit()

        # Alice attempts to fetch Bob's task
        async with self.session_factory() as session:
            repo = TaskRepository(session)
            alice_lookup = await repo.get_by_task_id("task_bob_secret", user_id=self.user_a_id)
            self.assertIsNone(alice_lookup, "User A must not access User B's task")

            # Alice lists her own tasks
            alice_tasks = await repo.list_user_tasks(user_id=self.user_a_id)
            self.assertEqual(len(alice_tasks), 0)

            # Bob lists his own tasks
            bob_tasks = await repo.list_user_tasks(user_id=self.user_b_id)
            self.assertEqual(len(bob_tasks), 1)
            self.assertEqual(bob_tasks[0].task_id_str, "task_bob_secret")

    def test_privacy_redaction_removes_sensitive_data(self):
        """Sensitive parameters like API keys, passwords, and tokens must be scrubbed."""
        payload = {
            "api_key": "gsk_1234567890abcdef1234567890",
            "password": "supersecretpassword",
            "url": "https://example.com/api",
            "safe_arg": "python_script.py",
            "nested": {
                "token": "bearer eyJhbGciOi...",
                "title": "Document Title",
            },
        }
        sanitized = sanitize_value(payload)

        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["token"], "[REDACTED]")
        self.assertEqual(sanitized["safe_arg"], "python_script.py")
        self.assertEqual(sanitized["nested"]["title"], "Document Title")

    def test_detect_application_classification(self):
        """Tools should normalize to recognizable desktop and browser applications."""
        self.assertEqual(detect_application("browser_click"), "Chrome")
        self.assertEqual(detect_application("docx_write"), "Word")
        self.assertEqual(detect_application("xlsx_read"), "Excel")
        self.assertEqual(detect_application("run_command"), "Terminal")
        self.assertEqual(detect_application("write_file"), "Filesystem")

    def test_normalize_task_category(self):
        """Intent / prompts normalize into structured taxonomy categories."""
        self.assertEqual(normalize_task_category(None, "open report.docx and edit header"), "document_editing")
        self.assertEqual(normalize_task_category(None, "analyze financial.xlsx"), "spreadsheet_analysis")
        self.assertEqual(normalize_task_category(None, "open youtube and search video"), "web_automation")
        self.assertEqual(normalize_task_category("coding", "fix function bug"), "coding")


if __name__ == "__main__":
    unittest.main()
