import pytest
import uuid
from backend.core.device_identity import get_device_id
from backend.core.firebase_auth import (
    get_device_local_user_info,
    get_device_local_user_id,
    LOCAL_USER_ID,
    LOCAL_USER_UID,
    get_or_create_local_user,
)
from backend.database.session import AsyncSessionLocal
from backend.database.models import User, Skill, SkillVersion
from backend.database.repositories.skill_repo import SkillRepository
from backend.agent.skills.matcher import matcher


@pytest.mark.asyncio
async def test_device_local_user_identity():
    dev_id = get_device_id()
    assert dev_id is not None
    user_id, user_uid, email, name = get_device_local_user_info()
    assert user_id == get_device_local_user_id()
    assert user_uid == f"local_device_{dev_id}"
    assert dev_id[:8] in email
    assert dev_id[:8] in name
    assert user_id == LOCAL_USER_ID
    assert user_uid == LOCAL_USER_UID


@pytest.mark.asyncio
async def test_skill_repository_strict_isolation():
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # Create user A and user B records
        user_a = User(id=user_a_id, firebase_uid=f"fb_{user_a_id.hex[:10]}", email="a@nexus.test")
        user_b = User(id=user_b_id, firebase_uid=f"fb_{user_b_id.hex[:10]}", email="b@nexus.test")
        session.add_all([user_a, user_b])
        await session.flush()

        # Create skill for user A
        skill_a = Skill(
            user_id=user_a_id,
            name="Skill A Special",
            trigger_phrases=["run test alpha"],
            is_active=True,
            health_status="healthy",
        )
        session.add(skill_a)
        await session.flush()

        ver_a = SkillVersion(
            skill_id=skill_a.id,
            version_number=1,
            steps_json=[{"action_type": "browser_navigate", "url": "https://example.com/a"}],
        )
        session.add(ver_a)

        # Create skill for user B
        skill_b = Skill(
            user_id=user_b_id,
            name="Skill B Special",
            trigger_phrases=["run test beta"],
            is_active=True,
            health_status="healthy",
        )
        session.add(skill_b)
        await session.flush()

        ver_b = SkillVersion(
            skill_id=skill_b.id,
            version_number=1,
            steps_json=[{"action_type": "browser_navigate", "url": "https://example.com/b"}],
        )
        session.add(ver_b)
        await session.flush()

        repo = SkillRepository(session)

        # Query active skills for User A
        skills_for_a = await repo.get_active_skills_for_matching(user_a_id)
        skills_for_a_ids = {s.id for s in skills_for_a}
        assert skill_a.id in skills_for_a_ids
        assert skill_b.id not in skills_for_a_ids

        # Query active skills for User B
        skills_for_b = await repo.get_active_skills_for_matching(user_b_id)
        skills_for_b_ids = {s.id for s in skills_for_b}
        assert skill_b.id in skills_for_b_ids
        assert skill_a.id not in skills_for_b_ids

        # Test skill matcher for User A
        match_a = await matcher.match_skill("run test alpha", user_a_id, session)
        assert match_a is not None
        assert match_a.skill.id == skill_a.id

        # User B should NEVER match User A's skill
        match_b_alpha = await matcher.match_skill("run test alpha", user_b_id, session)
        if match_b_alpha:
            assert match_b_alpha.skill.id != skill_a.id
            assert match_b_alpha.skill.user_id == user_b_id

        # User B should match User B's skill
        match_b_beta = await matcher.match_skill("run test beta", user_b_id, session)
        assert match_b_beta is not None
        assert match_b_beta.skill.id == skill_b.id

        # User A should NEVER match User B's skill
        match_a_beta = await matcher.match_skill("run test beta", user_a_id, session)
        if match_a_beta:
            assert match_a_beta.skill.id != skill_b.id
            assert match_a_beta.skill.user_id == user_a_id

        # Unrelated query returns None for both
        match_unrelated_a = await matcher.match_skill("check weather in tokyo", user_a_id, session)
        assert match_unrelated_a is None
        match_unrelated_b = await matcher.match_skill("check weather in tokyo", user_b_id, session)
        assert match_unrelated_b is None

        # Cleanup test records
        await session.rollback()
