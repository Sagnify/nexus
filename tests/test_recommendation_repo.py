"""
Tests for Recommendation Data Layer queries.
Verifies aggregation of user categories, tools, applications, and activity patterns.
"""
import asyncio
import unittest
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User, Task, TaskEvent
from backend.database.repositories.recommendation_repo import RecommendationRepository


class TestRecommendationRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.session_factory() as session:
            self.user = User(firebase_uid="uid_rec_test", email="rec@nexus.ai", display_name="Rec User")
            session.add(self.user)
            await session.commit()
            self.user_id = self.user.id

            # Seed tasks with different categories
            t1 = Task(task_id_str="t1", user_id=self.user_id, user_prompt="Edit doc", task_type="document_editing", status="completed")
            t2 = Task(task_id_str="t2", user_id=self.user_id, user_prompt="Edit doc 2", task_type="document_editing", status="completed")
            t3 = Task(task_id_str="t3", user_id=self.user_id, user_prompt="Analyze sheet", task_type="spreadsheet_analysis", status="completed")
            t4 = Task(task_id_str="t4", user_id=self.user_id, user_prompt="Write code", task_type="coding", status="failed")
            session.add_all([t1, t2, t3, t4])
            await session.flush()

            # Seed events
            e1 = TaskEvent(task_id=t1.id, user_id=self.user_id, event_type="tool_executed", tool_name="docx_write", application="Word", status="success")
            e2 = TaskEvent(task_id=t2.id, user_id=self.user_id, event_type="tool_executed", tool_name="docx_write", application="Word", status="success")
            e3 = TaskEvent(task_id=t3.id, user_id=self.user_id, event_type="tool_executed", tool_name="xlsx_read", application="Excel", status="success")
            e4 = TaskEvent(task_id=t4.id, user_id=self.user_id, event_type="tool_executed", tool_name="run_command", application="Terminal", status="failed")
            session.add_all([e1, e2, e3, e4])
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_get_frequent_task_categories(self):
        """Top categories should rank document_editing first."""
        async with self.session_factory() as session:
            repo = RecommendationRepository(session)
            cats = await repo.get_frequent_task_categories(self.user_id)
            self.assertGreaterEqual(len(cats), 2)
            self.assertEqual(cats[0]["category"], "document_editing")
            self.assertEqual(cats[0]["count"], 2)

    async def test_get_frequent_tools(self):
        """Top tools should rank docx_write highest."""
        async with self.session_factory() as session:
            repo = RecommendationRepository(session)
            tools = await repo.get_frequent_tools(self.user_id)
            self.assertGreaterEqual(len(tools), 2)
            self.assertEqual(tools[0]["tool"], "docx_write")
            self.assertEqual(tools[0]["count"], 2)

    async def test_get_frequent_applications(self):
        """Top applications should rank Word highest."""
        async with self.session_factory() as session:
            repo = RecommendationRepository(session)
            apps = await repo.get_frequent_applications(self.user_id)
            self.assertGreaterEqual(len(apps), 2)
            self.assertEqual(apps[0]["application"], "Word")
            self.assertEqual(apps[0]["count"], 2)

    async def test_activity_summary(self):
        """Activity summary should aggregate all dimensions cleanly."""
        async with self.session_factory() as session:
            repo = RecommendationRepository(session)
            summary = await repo.get_activity_summary(self.user_id)
            self.assertIn("top_categories", summary)
            self.assertIn("top_tools", summary)
            self.assertIn("top_applications", summary)
            self.assertIn("suggested_reruns", summary)


if __name__ == "__main__":
    unittest.main()
