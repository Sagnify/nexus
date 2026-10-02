"""
API integration tests for /api/skills endpoints.
Verifies:
- 401 Unauthorized for missing tokens
- 403 Forbidden for guest users
- 201 Created for valid skill creation
- Multi-tenant isolation (User B receives 404 for User A's skill ID)
- Version incrementing and rollback
- Skill deletion
"""
import os
import unittest
import uuid
import httpx

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.main import app
from backend.database.session import Base, get_db_session
from backend.database.models import User


class TestSkillsAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["NEXUS_TEST_MODE"] = "1"
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

        async def override_get_db_session():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_get_db_session

        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

        self.alice_token = "test-token-:uid_alice_api:alice@test.com:Alice API"
        self.bob_token = "test-token-:uid_bob_api:bob@test.com:Bob API"
        self.guest_token = "test-token-:guest_anon_123:guest@nexus.local:Guest"

    async def asyncTearDown(self):
        os.environ.pop("NEXUS_TEST_MODE", None)
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.engine.dispose()

    async def test_missing_auth_header_returns_401(self):
        resp = await self.client.get("/api/skills")
        self.assertEqual(resp.status_code, 401)

    async def test_guest_user_returns_403(self):
        resp = await self.client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {self.guest_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Guest accounts cannot create", resp.json()["detail"])

    async def test_create_and_list_skills(self):
        create_payload = {
            "name": "Stripe Invoices",
            "description": "Download stripe invoices",
            "category": "finance",
            "environment": "browser",
            "trigger_phrases": ["download invoices", "get stripe billing"],
            "parameters_schema": [{"name": "month", "type": "string", "required": True}],
            "steps": [
                {
                    "step_id": "s1",
                    "title": "Navigate",
                    "action_type": "browser_navigate",
                    "execution_engine": "browser",
                }
            ],
            "preconditions": [],
            "postconditions": [],
        }

        # User Alice creates skill
        resp = await self.client.post(
            "/api/skills",
            json=create_payload,
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        skill_id = data["skill"]["id"]
        self.assertEqual(data["skill"]["name"], "Stripe Invoices")
        self.assertEqual(data["skill"]["current_version"], 1)

        # Alice lists skills
        list_resp = await self.client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()["count"], 1)

        # User Bob lists skills -> should see 0
        bob_list_resp = await self.client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {self.bob_token}"},
        )
        self.assertEqual(bob_list_resp.status_code, 200)
        self.assertEqual(bob_list_resp.json()["count"], 0)

        # User Bob attempts to get Alice's skill -> 404
        bob_get_resp = await self.client.get(
            f"/api/skills/{skill_id}",
            headers={"Authorization": f"Bearer {self.bob_token}"},
        )
        self.assertEqual(bob_get_resp.status_code, 404)

        # Alice gets skill -> 200
        alice_get_resp = await self.client.get(
            f"/api/skills/{skill_id}",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(alice_get_resp.status_code, 200)
        self.assertEqual(alice_get_resp.json()["skill"]["name"], "Stripe Invoices")

        # Alice creates version 2
        v2_resp = await self.client.post(
            f"/api/skills/{skill_id}/versions",
            json={
                "steps": [
                    {"step_id": "s1", "title": "Navigate"},
                    {"step_id": "s2", "title": "Click download"},
                ],
                "change_summary": "Added step 2",
                "expected_version": 1,
            },
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(v2_resp.status_code, 201)
        self.assertEqual(v2_resp.json()["skill"]["current_version"], 2)

        # Alice rolls back to v1
        rollback_resp = await self.client.post(
            f"/api/skills/{skill_id}/rollback",
            json={"target_version_number": 1},
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(rollback_resp.status_code, 200)
        self.assertEqual(rollback_resp.json()["skill"]["current_version"], 3)

        # Alice deletes skill
        del_resp = await self.client.delete(
            f"/api/skills/{skill_id}",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(del_resp.status_code, 200)

        # Now get returns 404
        alice_recheck = await self.client.get(
            f"/api/skills/{skill_id}",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(alice_recheck.status_code, 404)

    async def test_db_timeout_returns_degraded_status_instead_of_500(self):
        """Verify that when database connection fails or times out, list_skills returns degraded state gracefully."""
        async def mock_broken_db_session():
            raise TimeoutError("Database connection timed out during SSL handshake")
            yield None

        app.dependency_overrides[get_db_session] = mock_broken_db_session
        resp = await self.client.get(
            "/api/skills",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertIn(resp.status_code, (200, 503))
        if resp.status_code == 200:
            data = resp.json()
            self.assertEqual(data["skills"], [])
            self.assertEqual(data["db_status"], "degraded")
        elif resp.status_code == 503:
            data = resp.json()
            self.assertEqual(data.get("type"), "DatabaseTimeoutError")


if __name__ == "__main__":
    unittest.main()

