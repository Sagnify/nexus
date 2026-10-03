"""
Skill, SkillVersion, and SkillExecution Repository.
Provides database access for user-defined automation skills, versioning, health tracking, and execution telemetry.
Enforces strict tenant isolation and user data ownership.
"""
from __future__ import annotations
import datetime
import logging
import uuid
from typing import Any, List, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import Skill, SkillVersion, SkillExecution

logger = logging.getLogger("nexus.database.skill_repo")



class SkillRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, skill_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Skill]:
        """Fetch skill by UUID primary key, enforcing strict user ownership."""
        stmt = (
            select(Skill)
            .where(Skill.id == skill_id, Skill.user_id == user_id)
            .options(
                selectinload(Skill.versions),
                selectinload(Skill.executions),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_name(self, name: str, user_id: uuid.UUID) -> Optional[Skill]:
        """Fetch skill by name, enforcing strict user ownership."""
        stmt = (
            select(Skill)
            .where(func.lower(Skill.name) == name.strip().lower(), Skill.user_id == user_id)
            .options(selectinload(Skill.versions))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_user_skills(
        self,
        user_id: uuid.UUID,
        category: Optional[str] = None,
        environment: Optional[str] = None,
        is_active: Optional[bool] = None,
        health_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Skill]:
        """List skills belonging to a specific user with optional filters, sorted latest updated first.
        
        STRICT ISOLATION: Only returns skills owned by the authenticated user.
        Desktop users (LOCAL_USER_ID) can only see their own skills.
        """
        stmt = (
            select(Skill)
            .where(Skill.user_id == user_id)
            .options(selectinload(Skill.versions))
        )
        if category:
            stmt = stmt.where(Skill.category == category)
        if environment:
            stmt = stmt.where(Skill.environment == environment)
        if is_active is not None:
            stmt = stmt.where(Skill.is_active == is_active)
        if health_status:
            stmt = stmt.where(Skill.health_status == health_status)

        if not self.session:
            return []

        stmt = stmt.order_by(desc(Skill.updated_at)).limit(limit).offset(offset)
        try:
            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as exc:
            lower_exc = (str(exc) + " " + type(exc).__name__).lower()
            if any(w in lower_exc for w in ("10054", "forcibly closed", "connection reset", "broken pipe", "timeout", "connectiondoesnotexist")):
                logger.debug("[SkillRepo] Database connection warming up or reset in list_user_skills: %s", exc or type(exc).__name__)
            else:
                logger.warning("[SkillRepo] Error executing list_user_skills: %s", exc or type(exc).__name__)
            return []

    async def get_active_skills_for_matching(self, user_id: uuid.UUID) -> List[Skill]:
        """Retrieve all active, non-suspended skills with their latest version for runtime matching."""
        if not self.session:
            return []

        from backend.core.firebase_auth import LOCAL_USER_ID
        where_conds = [
            Skill.is_active.is_(True),
            Skill.health_status != "suspended",
        ]
        if user_id and user_id != LOCAL_USER_ID:
            where_conds.append(Skill.user_id.in_([user_id, LOCAL_USER_ID]))

        stmt = (
            select(Skill)
            .where(*where_conds)
            .options(selectinload(Skill.versions))
        )
        try:
            res = await self.session.execute(stmt)
            skills = list(res.scalars().all())
            active_skills = [s for s in skills if not s.is_draft]
            return active_skills if active_skills else skills
        except Exception as exc:
            logger.warning("[SkillRepo] Error executing get_active_skills_for_matching: %s", exc)
            return []

    async def create_skill(
        self,
        user_id: uuid.UUID,
        name: str,
        steps_json: list[dict[str, Any]],
        description: Optional[str] = None,
        category: str = "general",
        environment: str = "mixed",
        trigger_phrases: Optional[list[str]] = None,
        parameters_schema: Optional[list[dict[str, Any]]] = None,
        preconditions: Optional[list[dict[str, Any]]] = None,
        postconditions: Optional[list[dict[str, Any]]] = None,
        is_draft: bool = False,
    ) -> Skill:
        """Create a new skill and its initial version (v1) in an atomic transaction."""
        skill = Skill(
            user_id=user_id,
            name=name.strip(),
            description=description.strip() if description else None,
            category=category.strip().lower(),
            environment=environment.strip().lower(),
            trigger_phrases=trigger_phrases or [],
            parameters_schema=parameters_schema or [],
            is_active=True,
            is_draft=is_draft,
            current_version=1,
            health_status="healthy",
            consecutive_failures=0,
        )
        self.session.add(skill)
        await self.session.flush()

        version = SkillVersion(
            skill_id=skill.id,
            version_number=1,
            steps_json=steps_json,
            preconditions=preconditions or [],
            postconditions=postconditions or [],
            change_summary="Initial demonstration version",
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(skill)

        # Eager load versions
        stmt = (
            select(Skill)
            .where(Skill.id == skill.id)
            .options(selectinload(Skill.versions))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one()

    async def upsert_skill(
        self,
        user_id: uuid.UUID,
        name: str,
        steps_json: list[dict[str, Any]],
        description: Optional[str] = None,
        category: str = "general",
        environment: str = "mixed",
        trigger_phrases: Optional[list[str]] = None,
        parameters_schema: Optional[list[dict[str, Any]]] = None,
        preconditions: Optional[list[dict[str, Any]]] = None,
        postconditions: Optional[list[dict[str, Any]]] = None,
        is_draft: bool = False,
    ) -> Skill:
        """Create a skill or update it if a skill with the same name already exists for this user."""
        existing = await self.get_by_name(name, user_id)
        if not existing:
            return await self.create_skill(
                user_id=user_id,
                name=name,
                steps_json=steps_json,
                description=description,
                category=category,
                environment=environment,
                trigger_phrases=trigger_phrases,
                parameters_schema=parameters_schema,
                preconditions=preconditions,
                postconditions=postconditions,
                is_draft=is_draft,
            )

        if description is not None:
            existing.description = description.strip() if description else None
        if category:
            existing.category = category.strip().lower()
        if environment:
            existing.environment = environment.strip().lower()
        if trigger_phrases is not None:
            existing.trigger_phrases = trigger_phrases
        if parameters_schema is not None:
            existing.parameters_schema = parameters_schema
        existing.is_draft = is_draft
        existing.is_active = True
        existing.health_status = "healthy"

        if existing.versions:
            latest_v = existing.versions[-1]
            latest_v.steps_json = steps_json
            latest_v.preconditions = preconditions or []
            latest_v.postconditions = postconditions or []
        else:
            new_v = SkillVersion(
                skill_id=existing.id,
                version_number=1,
                steps_json=steps_json,
                preconditions=preconditions or [],
                postconditions=postconditions or [],
                change_summary="Updated demonstration version",
            )
            self.session.add(new_v)

        await self.session.commit()
        await self.session.refresh(existing)
        stmt = (
            select(Skill)
            .where(Skill.id == existing.id)
            .options(selectinload(Skill.versions))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one()

    async def update_skill_metadata(
        self,
        skill_id: uuid.UUID,
        user_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        environment: Optional[str] = None,
        trigger_phrases: Optional[list[str]] = None,
        parameters_schema: Optional[list[dict[str, Any]]] = None,
        is_active: Optional[bool] = None,
        is_draft: Optional[bool] = None,
    ) -> Optional[Skill]:
        """Update mutable metadata on a skill without modifying its version history."""
        skill = await self.get_by_id(skill_id, user_id)
        if not skill:
            return None

        if name is not None:
            skill.name = name.strip()
        if description is not None:
            skill.description = description.strip()
        if category is not None:
            skill.category = category.strip().lower()
        if environment is not None:
            skill.environment = environment.strip().lower()
        if trigger_phrases is not None:
            skill.trigger_phrases = trigger_phrases
        if parameters_schema is not None:
            skill.parameters_schema = parameters_schema
        if is_active is not None:
            skill.is_active = is_active
        if is_draft is not None:
            skill.is_draft = is_draft

        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def create_new_version(
        self,
        skill_id: uuid.UUID,
        user_id: uuid.UUID,
        steps_json: list[dict[str, Any]],
        preconditions: Optional[list[dict[str, Any]]] = None,
        postconditions: Optional[list[dict[str, Any]]] = None,
        change_summary: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Optional[tuple[Skill, SkillVersion]]:
        """
        Create a new immutable version of a skill with optimistic concurrency check.
        Resets consecutive failures and restores health to 'healthy' upon approved update/repair.
        """
        skill = await self.get_by_id(skill_id, user_id)
        if not skill:
            return None

        if expected_version is not None and skill.current_version != expected_version:
            raise ValueError(
                f"Concurrent modification detected. Expected version {expected_version}, but current version is {skill.current_version}."
            )

        new_version_number = skill.current_version + 1
        skill.current_version = new_version_number
        skill.health_status = "healthy"
        skill.consecutive_failures = 0

        version = SkillVersion(
            skill_id=skill.id,
            version_number=new_version_number,
            steps_json=steps_json,
            preconditions=preconditions or [],
            postconditions=postconditions or [],
            change_summary=change_summary or f"Updated to version {new_version_number}",
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(skill)
        await self.session.refresh(version)
        return skill, version

    async def rollback_version(
        self,
        skill_id: uuid.UUID,
        user_id: uuid.UUID,
        target_version_number: int,
    ) -> Optional[Skill]:
        """
        Roll back a skill to a previous version by cloning its steps into a new incremented version.
        Preserves complete append-only audit history.
        """
        skill = await self.get_by_id(skill_id, user_id)
        if not skill:
            return None

        stmt = select(SkillVersion).where(
            SkillVersion.skill_id == skill_id,
            SkillVersion.version_number == target_version_number,
        )
        res = await self.session.execute(stmt)
        target_version = res.scalar_one_or_none()
        if not target_version:
            raise ValueError(f"Version {target_version_number} not found for skill {skill_id}")

        new_version_number = skill.current_version + 1
        skill.current_version = new_version_number
        skill.health_status = "healthy"
        skill.consecutive_failures = 0

        rolled_back_version = SkillVersion(
            skill_id=skill.id,
            version_number=new_version_number,
            steps_json=target_version.steps_json,
            preconditions=target_version.preconditions,
            postconditions=target_version.postconditions,
            change_summary=f"Rolled back to contents of version {target_version_number}",
        )
        self.session.add(rolled_back_version)
        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def record_execution(
        self,
        skill_id: uuid.UUID,
        user_id: uuid.UUID,
        version_number: int,
        status: str,
        parameters_used: Optional[dict[str, Any]] = None,
        step_results: Optional[list[dict[str, Any]]] = None,
        recovery_attempts: Optional[list[dict[str, Any]]] = None,
        error_message: Optional[str] = None,
        failed_step_index: Optional[int] = None,
        duration_ms: Optional[int] = None,
        task_id: Optional[uuid.UUID] = None,
    ) -> SkillExecution:
        """
        Record skill execution telemetry and update skill health status.
        Automatically sets health_status to 'degraded' (2 failures) or 'suspended' (>=3 failures).
        """
        skill = await self.get_by_id(skill_id, user_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        execution = SkillExecution(
            skill_id=skill_id,
            version_number=version_number,
            user_id=user_id,
            task_id=task_id,
            status=status,
            parameters_used=parameters_used or {},
            step_results=step_results or [],
            recovery_attempts=recovery_attempts or [],
            error_message=error_message,
            failed_step_index=failed_step_index,
            duration_ms=duration_ms,
        )
        self.session.add(execution)

        if skill:
            skill.last_executed_at = now
            if status in ("completed", "recovered"):
                skill.success_count += 1
                skill.consecutive_failures = 0
                if status == "recovered":
                    skill.recovery_count += 1
                # If was degraded due to consecutive failures, restore to healthy
                if skill.health_status == "degraded" and skill.consecutive_failures == 0:
                    skill.health_status = "healthy"
            elif status == "failed":
                skill.failure_count += 1
                skill.consecutive_failures += 1
                skill.last_failed_at = now
                if skill.consecutive_failures >= 3:
                    skill.health_status = "suspended"
                    logger.warning(
                        f"[Health Alert] Skill '{skill.name}' ({skill.id}) SUSPENDED after {skill.consecutive_failures} consecutive failures."
                    )
                elif skill.consecutive_failures >= 2:
                    skill.health_status = "degraded"

        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def set_health_status(
        self,
        skill_id: uuid.UUID,
        user_id: uuid.UUID,
        health_status: str,
    ) -> Optional[Skill]:
        """Manually override skill health status (e.g. reactivate a suspended skill)."""
        skill = await self.get_by_id(skill_id, user_id)
        if not skill:
            return None

        skill.health_status = health_status.strip().lower()
        if skill.health_status == "healthy":
            skill.consecutive_failures = 0

        await self.session.commit()
        await self.session.refresh(skill)
        return skill

    async def delete_skill(self, skill_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Delete skill and cascade delete versions and executions, enforcing strict user ownership."""
        stmt = delete(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return res.rowcount > 0
