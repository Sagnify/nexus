"""
Unit tests for Firebase Authentication and Token Verification.
Tests token decoding, claim extraction, user resolution, and security checks.
"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.database.session import Base
from backend.database.models import User
from backend.core.firebase_auth import verify_id_token, get_or_create_user


class TestFirebaseAuth(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_verify_test_token(self):
        """Test token format parsing for testing / offline environments."""
        token = "test-token-:usr_123:alex@nexus.ai:Alex Nexus"
        claims = await verify_id_token(token)
        self.assertEqual(claims["uid"], "usr_123")
        self.assertEqual(claims["email"], "alex@nexus.ai")
        self.assertEqual(claims["name"], "Alex Nexus")

    async def test_get_or_create_new_user(self):
        """Test that first-time login creates a new User with proper firebase_uid."""
        async with self.session_factory() as session:
            claims = {
                "uid": "fb_uid_999",
                "email": "user999@test.com",
                "name": "User 999",
                "picture": "https://example.com/avatar.jpg",
            }
            user = await get_or_create_user(session, claims)
            await session.commit()

            self.assertIsNotNone(user.id)
            self.assertEqual(user.firebase_uid, "fb_uid_999")
            self.assertEqual(user.email, "user999@test.com")
            self.assertEqual(user.display_name, "User 999")
            self.assertEqual(user.profile_image_url, "https://example.com/avatar.jpg")

    async def test_returning_user_updates_without_duplication(self):
        """Test that a returning login updates existing record and prevents duplicate accounts."""
        async with self.session_factory() as session:
            claims = {"uid": "fb_uid_repeat", "email": "repeat@test.com", "name": "Initial Name", "picture": None}
            user1 = await get_or_create_user(session, claims)
            await session.commit()
            user1_id = user1.id

        # Second login with updated name
        async with self.session_factory() as session:
            updated_claims = {"uid": "fb_uid_repeat", "email": "repeat@test.com", "name": "Updated Name", "picture": None}
            user2 = await get_or_create_user(session, updated_claims)
            await session.commit()

            self.assertEqual(user2.id, user1_id)
            self.assertEqual(user2.display_name, "Updated Name")


if __name__ == "__main__":
    unittest.main()
