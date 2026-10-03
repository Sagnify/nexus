"""
Authenticated Skill Management API Endpoints.
Provides CRUD operations, version creation, rollback, and execution telemetry for automation skills.
Enforces strict Firebase user authentication, tenant isolation, and blocks guest accounts from persistent skills.
"""
from __future__ import annotations
import asyncio
import datetime
import logging
import uuid
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.firebase_auth import get_current_user
from backend.database.models import User
from backend.database.session import get_db_session
from backend.database.repositories.skill_repo import SkillRepository

logger = logging.getLogger("nexus.api.skills")
router = APIRouter()


def ensure_authenticated_non_guest(user: User) -> None:
    """Allow local desktop user and registered accounts; block anonymous guest accounts."""
    if not user:
        return
    # Block firebase_uid-tagged guest sessions
    if user.firebase_uid and user.firebase_uid.startswith("guest_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest accounts cannot create or persist automation skills. Please log in with a registered account.",
        )
    # Block synthesised local guest emails (exact pattern: guest_<hex>@nexus.local or @nexus.guest)
    # Deliberately narrow — avoids blocking real users whose names contain "guest" (e.g. guestavo@...)
    if user.email:
        email_lower = user.email.lower()
        is_guest_email = (
            email_lower.endswith("@nexus.local")
            or email_lower.endswith("@nexus.guest")
            or (email_lower.startswith("guest_") and "@" in email_lower)
        )
        # Internal desktop accounts (@nexus.desktop) are always allowed
        is_desktop_account = email_lower.endswith("@nexus.desktop")
        if is_guest_email and not is_desktop_account:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guest accounts cannot create or persist automation skills. Please log in with a registered account.",
            )


def _skill_owner_uuid(user_id: str) -> uuid.UUID:
    if not user_id:
        raise ValueError("Refusing to persist a skill without an authenticated owner ID.")
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Refusing to persist a skill with an invalid owner ID.") from exc



# --- Request & Response Models ---

class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Unique human-readable skill name")
    description: Optional[str] = Field(None, max_length=2000)
    category: str = Field("general", max_length=64)
    environment: str = Field("mixed", description="'browser' | 'desktop' | 'mixed'")
    trigger_phrases: List[str] = Field(default_factory=list, description="Activation phrases matching user prompts")
    parameters_schema: List[dict[str, Any]] = Field(default_factory=list, description="Declared parameters schema")
    steps: List[dict[str, Any]] = Field(..., min_length=1, description="List of semantic action steps")
    preconditions: List[dict[str, Any]] = Field(default_factory=list)
    postconditions: List[dict[str, Any]] = Field(default_factory=list)
    is_draft: bool = Field(False)


class UpdateSkillMetadataRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = None
    environment: Optional[str] = None
    trigger_phrases: Optional[List[str]] = None
    parameters_schema: Optional[List[dict[str, Any]]] = None
    is_active: Optional[bool] = None
    is_draft: Optional[bool] = None


class CreateSkillVersionRequest(BaseModel):
    steps: List[dict[str, Any]] = Field(..., min_length=1, description="Updated semantic action steps")
    preconditions: List[dict[str, Any]] = Field(default_factory=list)
    postconditions: List[dict[str, Any]] = Field(default_factory=list)
    change_summary: Optional[str] = Field(None, max_length=500)
    expected_version: Optional[int] = Field(None, description="Current version number for optimistic concurrency")


class RollbackVersionRequest(BaseModel):
    target_version_number: int = Field(..., ge=1, description="Version number to restore")


class SetHealthRequest(BaseModel):
    health_status: str = Field(..., description="'healthy' | 'degraded' | 'suspended'")


class StartTeachRequest(BaseModel):
    prompt: str = Field("", description="Natural language description of the workflow to teach")
    target_environment: str = Field("browser", description="'browser' | 'desktop' | 'mixed'")
    allow_desktop_fallback: bool = Field(False, description="If True and browser extension is offline, fallback to desktop recording instead of failing.")


class StopTeachRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session id to complete")
    save_immediately: bool = Field(False)


# --- Endpoints ---

@router.get("")
async def list_skills(
    category: Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    health_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: Optional[AsyncSession] = Depends(get_db_session),
):
    """List skills belonging to the authenticated user with optional filtering."""
    ensure_authenticated_non_guest(user)
    if session is None:
        return {
            "skills": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "db_status": "offline",
        }
    try:
        repo = SkillRepository(session)
        skills = await repo.list_user_skills(
            user_id=user.id,
            category=category,
            environment=environment,
            is_active=is_active,
            health_status=health_status,
            limit=limit,
            offset=offset,
        )
        return {
            "skills": [s.to_dict() for s in skills],
            "count": len(skills),
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.warning("[Skills] Database connection or timeout issue listing skills: %s", exc)
        return {
            "skills": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "db_status": "degraded",
        }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: CreateSkillRequest,
    user: User = Depends(get_current_user),
    session: Optional[AsyncSession] = Depends(get_db_session),
):
    """Create a new automation skill and initialize its v1 version."""
    ensure_authenticated_non_guest(user)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is temporarily unavailable. Please retry in a few moments.",
        )

    try:
        repo = SkillRepository(session)
        skill = await repo.upsert_skill(
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            environment=payload.environment,
            trigger_phrases=payload.trigger_phrases,
            parameters_schema=payload.parameters_schema,
            steps_json=payload.steps,
            preconditions=payload.preconditions,
            postconditions=payload.postconditions,
            is_draft=payload.is_draft,
        )
        return {
            "skill": skill.to_dict(),
            "versions": [v.to_dict() for v in skill.versions],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[Skills] Database error creating skill: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is temporarily warming up or unavailable. Please retry shortly.",
        ) from exc


# ── Interactive Demonstration / Teach Mode Endpoints ─────────────────────────

@router.post("/teach/start")
async def start_teach_session(
    req: StartTeachRequest,
    user: User = Depends(get_current_user),
):
    """Start an interactive demonstration recording session."""
    ensure_authenticated_non_guest(user)
    from backend.agent.skills.session import session_manager
    from backend.agent.tools.web_automation.extension_bridge import extension_bridge

    ext_connected = extension_bridge.is_connected()
    target_env = req.target_environment

    session = await session_manager.start_session(
        user_id=str(user.id),
        target_environment=target_env,
        prompt_intent=req.prompt.strip() or None,
    )

    if req.target_environment in ("browser", "mixed"):
        if not ext_connected:
            ext_connected = await extension_bridge.wait_for_connection(timeout_seconds=3.5)
        if not ext_connected:
            if req.allow_desktop_fallback or req.target_environment == "mixed":
                logger.info("[Teach] Browser extension not connected; seamlessly switching to desktop recording mode.")
                session.target_environment = "desktop"
            else:
                await session_manager.discard_session(session.session_id, str(user.id))
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Browser recording could not start because the NEXUS extension is not connected.",
                )

        if ext_connected and session.target_environment in ("browser", "mixed"):
            try:
                result = await extension_bridge.send_command(
                    "start_teach_mode",
                    {"session_id": session.session_id, "prompt": req.prompt.strip()},
                    timeout=8.0,
                )
                if not result.get("success"):
                    if req.allow_desktop_fallback:
                        logger.warning("[Teach] Browser extension did not confirm recording; falling back to desktop.")
                        session.target_environment = "desktop"
                    else:
                        raise RuntimeError("The browser extension did not confirm that recording started.")
            except Exception as exc:
                if req.allow_desktop_fallback:
                    logger.warning(f"[Teach] Browser extension error: {exc}; falling back to desktop.")
                    session.target_environment = "desktop"
                else:
                    await session_manager.discard_session(session.session_id, str(user.id))
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Browser recording could not start: {exc}",
                    ) from exc

    if session.target_environment in ("desktop", "mixed"):
        try:
            from backend.agent.skills.desktop_observer import desktop_observer
            await desktop_observer.start_observing(session.session_id)
            logger.info("[Teach] Desktop demonstration observer engaged for session %s", session.session_id)
        except Exception as do_exc:
            logger.warning("[Teach] Could not engage desktop observer: %s", do_exc)

    return {
        "session_id": session.session_id,
        "status": session.status,
        "target_environment": session.target_environment,
        "extension_connected": ext_connected,
        "started_at": session.started_at.isoformat(),
        "prompt": session.prompt_intent,
    }


@router.get("/teach/status")
async def get_teach_session_status(
    user: User = Depends(get_current_user),
):
    """Get active teach session telemetry, duration, and recent captured events."""
    from backend.agent.skills.session import session_manager
    from backend.agent.tools.web_automation.extension_bridge import extension_bridge

    ensure_authenticated_non_guest(user)
    user_id = str(user.id)
    session = await session_manager.get_active_session_for_user(user_id)
    if not session:
        return {
            "is_active": False,
            "session_id": None,
            "status": "idle",
            "events_count": 0,
            "duration_seconds": 0,
            "recent_actions": [],
            "extension_connected": extension_bridge.is_connected(),
        }

    now = datetime.datetime.now(datetime.timezone.utc)
    duration = (now - session.started_at).total_seconds()

    recent_actions = []
    for ev in session.events[-6:]:
        if ev.event_type == "click":
            target = ""
            if ev.selector_bundle:
                target = ev.selector_bundle.get("textAnchor") or ev.selector_bundle.get("ariaLabel") or ev.selector_bundle.get("name") or ev.selector_bundle.get("id") or "button"
            recent_actions.append(f"Clicked '{target[:30]}'")
        elif ev.event_type in ("input", "change"):
            val = "[hidden]" if ev.is_sensitive else (ev.value or "")
            recent_actions.append(f"Entered '{val[:20]}'")
        elif ev.event_type == "navigate":
            recent_actions.append(f"Navigated to {ev.url or 'page'}")
        else:
            recent_actions.append(f"{ev.event_type.title()} event")

    return {
        "is_active": session.status in ("recording", "paused"),
        "session_id": session.session_id,
        "status": session.status,
        "events_count": len(session.events),
        "duration_seconds": round(duration, 1),
        "recent_actions": recent_actions,
        "prompt": session.prompt_intent,
        "extension_connected": extension_bridge.is_connected(),
    }


_compiling_futures: dict[str, asyncio.Future] = {}


@router.post("/teach/stop-direct")
async def stop_teach_direct(
    http_req: Request,
    req: StopTeachRequest = StopTeachRequest(),
):
    """Direct loopback endpoint for Chrome Extension to trigger session finish without JWT overhead."""
    client_host = http_req.client.host if http_req.client else ""
    if client_host not in ("127.0.0.1", "localhost", "::1"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Loopback only")

    from backend.agent.skills.session import session_manager
    session = await session_manager.get_session(req.session_id) if req.session_id else None
    if not session:
        session = await session_manager.get_active_session_for_user("")
    if not session:
        return {"success": False, "status": "idle", "message": "No active session"}

    await session_manager.complete_session(session.session_id, session.user_id)

    # ⚡ Instant non-blocking loopback trigger to Electron spotlight window
    async def _wake_electron():
        try:
            import urllib.request
            wake_req = urllib.request.Request("http://127.0.0.1:8765/show-spotlight", method="POST")
            await asyncio.to_thread(urllib.request.urlopen, wake_req, timeout=0.2)
        except Exception:
            pass
    asyncio.create_task(_wake_electron())

    return {"success": True, "status": "completed", "session_id": session.session_id}


@router.post("/teach/stop")
async def stop_teach_session(
    req: StopTeachRequest = StopTeachRequest(),
    user: User = Depends(get_current_user),
):
    """Complete active demonstration and compile raw events into a structured skill draft."""
    from backend.agent.skills.session import session_manager
    from backend.agent.skills.semanticizer import semanticizer
    from backend.agent.skills.compiler import compiler
    from backend.agent.tools.web_automation.extension_bridge import extension_bridge

    ensure_authenticated_non_guest(user)
    user_id = str(user.id)

    # Purge completed or cancelled futures to prevent stale deadlocks
    stale_keys = [k for k, f in list(_compiling_futures.items()) if f.done()]
    for k in stale_keys:
        _compiling_futures.pop(k, None)

    session = await session_manager.get_active_session_for_user(user_id)
    if not session and req.session_id:
        candidate = await session_manager.get_session(req.session_id)
        if candidate and candidate.user_id == user_id:
            session = candidate

    from backend.core.auto_healer import auto_healer

    # The request may only compile a session owned by the authenticated user.
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active demonstration session found for this user.",
        )

    # Deduplicate concurrent requests for the exact same session
    if session.session_id in _compiling_futures:
        try:
            return await asyncio.wait_for(asyncio.shield(_compiling_futures[session.session_id]), timeout=3.5)
        except Exception:
            _compiling_futures.pop(session.session_id, None)

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _compiling_futures[session.session_id] = fut

    raw_events = []
    try:
        try:
            from backend.agent.skills.desktop_observer import desktop_observer
            await desktop_observer.stop_observing()
        except Exception:
            pass

        if extension_bridge.is_connected():
            try:
                await extension_bridge.send_command("stop_teach_mode", {}, timeout=0.8)
            except Exception:
                pass

        completed_session = await session_manager.complete_session(session.session_id, user_id)
        raw_events = completed_session.events if completed_session else (session.events or [])

        logger.info(
            "[SkillCompiler] 🏁 Compiling demonstration session '%s' (%d captured events, intent: '%s')",
            session.session_id,
            len(raw_events),
            session.prompt_intent or "Workflow",
        )

        semantic_actions = semanticizer.semanticize_events(raw_events)
        if not semantic_actions:
            from backend.agent.skills.semanticizer import RawSemanticAction
            semantic_actions = [
                RawSemanticAction(
                    action_type="browser_navigate",
                    execution_engine="browser",
                    title="Open Target Page",
                    url="https://google.com",
                    target_app="Chrome",
                )
            ]

        # Autonomous guaranteed compilation: tries fast AI (4.5s ceiling), auto-falls back to deterministic compiler in <10ms
        compiled_draft = await auto_healer.safe_compile_demonstration(
            raw_actions=semantic_actions,
            prompt_intent=session.prompt_intent or "Demonstrated Workflow",
            target_environment=session.target_environment or "browser",
        )

        draft_dict = compiled_draft.model_dump()
        if not draft_dict.get("steps"):
            draft_dict["steps"] = [
                {
                    "step_id": "step-1",
                    "title": "Perform Task",
                    "action_type": "browser_navigate",
                    "execution_engine": "browser",
                    "url": "https://google.com",
                    "preconditions": [],
                    "postconditions": [],
                }
            ]
            draft_dict["warning"] = "No interactions were detected during demonstration. Make sure the target page was interacted with."

        logger.info(
            "[SkillCompiler] ✅ Skill compilation succeeded! (%d steps, %d parameters)",
            len(draft_dict.get("steps", [])),
            len(draft_dict.get("parameters_schema", [])),
        )

        # Validate step order and dependencies using AI
        from backend.agent.skills.step_validator import validator
        try:
            validation_result = await validator.validate_steps(
                steps=draft_dict.get("steps", []),
                prompt_intent=session.prompt_intent or "Demonstrated Workflow",
                auto_fix=True,
            )
            
            # Add validation metadata to draft
            draft_dict["validation"] = {
                "is_valid": validation_result.is_valid,
                "issues": [issue.model_dump() for issue in validation_result.issues],
                "confidence_score": validation_result.confidence_score,
                "notes": validation_result.validation_notes,
            }
            
            # If AI suggested corrections, use them
            if validation_result.corrected_steps:
                logger.info(
                    "[StepValidator] Applying evidence-based reorder of %d recorded steps",
                    len(validation_result.corrected_steps),
                )
                draft_dict["steps"] = validation_result.corrected_steps
            
            if validation_result.issues:
                logger.info(
                    "[StepValidator] Validation complete: %d issues found (confidence: %.2f)",
                    len(validation_result.issues),
                    validation_result.confidence_score,
                )
        except Exception as val_exc:
            logger.warning("[StepValidator] Validation failed (non-blocking): %s", val_exc)
            draft_dict["validation"] = {
                "is_valid": True,
                "issues": [],
                "confidence_score": 0.0,
                "notes": f"Validation skipped: {str(val_exc)}",
            }

        # Non-blocking background persistence: immediately return draft so UI does not wait on DB network
        async def _persist_background(d_dict: dict, u_id: str):
            try:
                from backend.database.session import get_db_session
                from backend.database.repositories.skill_repo import SkillRepository
                uid_obj = _skill_owner_uuid(u_id)

                async for db_session in get_db_session():
                    if db_session is None:
                        break
                    repo = SkillRepository(db_session)
                    saved_skill = await repo.upsert_skill(
                        user_id=uid_obj,
                        name=d_dict.get("name", "Demonstrated Skill"),
                        description=d_dict.get("description", ""),
                        category=d_dict.get("category", "general"),
                        environment=d_dict.get("environment", "browser"),
                        trigger_phrases=d_dict.get("trigger_phrases", []),
                        parameters_schema=d_dict.get("parameters_schema", []),
                        steps_json=d_dict.get("steps", []),
                        preconditions=d_dict.get("preconditions", []),
                        postconditions=d_dict.get("postconditions", []),
                        is_draft=True,
                    )
                    logger.info("[SkillCompiler] 💾 Skill persisted to database in background: %s", saved_skill.id)
                    break
            except Exception as save_exc:
                logger.warning("[SkillCompiler] ⚠️ Background DB persist warning: %s", save_exc)

        asyncio.create_task(_persist_background(draft_dict, user_id))

        result = {
            "status": "compiled",
            "draft": draft_dict,
            "events_count": len(raw_events),
        }
        if not fut.done():
            fut.set_result(result)
        return result

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("[SkillCompiler] ❌ Fatal error compiling session %s: %s\n%s", session.session_id, e, tb)
        if not fut.done():
            fut.set_exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": f"Compilation failed: {str(e)}",
                "error": str(e),
                "traceback": tb,
                "events_count": len(raw_events),
            },
        )
    finally:
        _compiling_futures.pop(session.session_id, None)
        try:
            await session_manager.discard_session(session.session_id, user_id)
        except Exception:
            pass


@router.post("/teach/discard")
async def discard_teach_session(
    user: User = Depends(get_current_user),
):
    """Discard active demonstration without saving."""
    from backend.agent.skills.session import session_manager
    from backend.agent.tools.web_automation.extension_bridge import extension_bridge

    ensure_authenticated_non_guest(user)
    user_id = str(user.id)
    session = await session_manager.get_active_session_for_user(user_id)
    if session:
        await session_manager.discard_session(session.session_id, user_id)

    try:
        from backend.agent.skills.desktop_observer import desktop_observer
        await desktop_observer.stop_observing()
    except Exception:
        pass

    if extension_bridge.is_connected():
        try:
            await extension_bridge.send_command("stop_teach_mode", {}, timeout=0.8)
        except Exception:
            pass

    return {"message": "Demonstration discarded successfully."}


@router.post("/teach/recover")
async def recover_teach_session(
    user: User = Depends(get_current_user),
):
    """Emergency auto-recovery endpoint: deterministic instant compilation — skips AI entirely.

    Unlike /teach/stop, this endpoint NEVER calls the AI model pool. It goes straight to the
    sub-millisecond heuristic compiler, guaranteeing a response in < 50ms regardless of model
    availability or rate-limiting state.
    """
    from backend.agent.skills.session import session_manager
    from backend.core.auto_healer import auto_healer
    from backend.agent.skills.semanticizer import semanticizer
    from backend.agent.skills.compiler import compiler, CompiledSkillDraft, CompiledStepSchema

    ensure_authenticated_non_guest(user)
    user_id = str(user.id)
    session = await session_manager.get_active_session_for_user(user_id)
    raw_events = session.events if session else []
    semantic_actions = semanticizer.semanticize_events(raw_events)
    prompt_intent = session.prompt_intent if session else "Recovered Workflow"
    target_environment = session.target_environment if session else "browser"

    # ── Instant deterministic compilation (< 10ms, no AI, no network) ──────────
    draft = None
    try:
        det_draft = compiler.compile(
            raw_actions=semantic_actions,
            prompt_intent=prompt_intent,
            category="browser" if target_environment == "browser" else "general",
        )
        if det_draft and det_draft.steps:
            draft = det_draft
    except Exception as det_exc:
        logger.warning("[RecoverEndpoint] Deterministic compiler error (%s); synthesising safe draft.", det_exc)

    # ── Guaranteed safe fallback: synthesise from raw actions directly ──────────
    if not draft:
        steps = []
        for idx, act in enumerate(semantic_actions):
            from backend.agent.skills.compiler import CompiledStepSchema
            action_type = getattr(act, "action_type", "browser_navigate")
            engine = getattr(act, "execution_engine", "browser")
            if engine not in ("browser", "desktop", "system"):
                engine = "browser"
            steps.append(
                CompiledStepSchema(
                    step_id=f"step-recovered-{idx + 1}",
                    title=getattr(act, "title", f"Step {idx + 1}"),
                    action_type=action_type,
                    execution_engine=engine,
                    url=getattr(act, "url", None),
                    value_template=getattr(act, "value", None),
                )
            )
        if not steps:
            steps = [
                CompiledStepSchema(
                    step_id="step-recovered-1",
                    title="Open Demonstrated Page",
                    action_type="browser_navigate",
                    execution_engine="browser",
                    url="https://google.com",
                )
            ]
        draft = CompiledSkillDraft(
            name=prompt_intent or "Recovered Workflow",
            description=f"Auto-recovered workflow ({len(raw_events)} captured events)",
            category="browser" if target_environment == "browser" else "general",
            environment=target_environment,
            steps=steps,
        )

    auto_healer.record_recovery(
        f"Emergency deterministic recovery compiled {len(draft.steps)} steps from {len(raw_events)} events."
    )
    logger.info(
        "[RecoverEndpoint] ⚡ Instant deterministic recovery: %d steps from %d events (intent: '%s')",
        len(draft.steps), len(raw_events), prompt_intent,
    )
    return {
        "status": "compiled",
        "draft": draft.model_dump(),
        "events_count": len(raw_events),
        "recovered": True,
    }


@router.get("/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get full skill details, version history, and execution records."""
    ensure_authenticated_non_guest(user)
    repo = SkillRepository(session)
    skill = await repo.get_by_id(skill_id, user.id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )

    return {
        "skill": skill.to_dict(),
        "versions": [v.to_dict() for v in skill.versions],
        "executions": [e.to_dict() for e in skill.executions[-10:]],
    }


@router.put("/{skill_id}")
async def update_skill_metadata(
    skill_id: uuid.UUID,
    payload: UpdateSkillMetadataRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Update mutable metadata on a skill without bumping its version number."""
    ensure_authenticated_non_guest(user)
    repo = SkillRepository(session)

    if payload.name:
        existing = await repo.get_by_name(payload.name, user.id)
        if existing and existing.id != skill_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Another skill named '{payload.name}' already exists.",
            )

    updated = await repo.update_skill_metadata(
        skill_id=skill_id,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        environment=payload.environment,
        trigger_phrases=payload.trigger_phrases,
        parameters_schema=payload.parameters_schema,
        is_active=payload.is_active,
        is_draft=payload.is_draft,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )
    return {"skill": updated.to_dict()}


@router.post("/{skill_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_skill_version(
    skill_id: uuid.UUID,
    payload: CreateSkillVersionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new version for an existing skill with optimistic concurrency check."""
    ensure_authenticated_non_guest(user)
    repo = SkillRepository(session)

    try:
        res = await repo.create_new_version(
            skill_id=skill_id,
            user_id=user.id,
            steps_json=payload.steps,
            preconditions=payload.preconditions,
            postconditions=payload.postconditions,
            change_summary=payload.change_summary,
            expected_version=payload.expected_version,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )

    skill, new_version = res
    return {
        "skill": skill.to_dict(),
        "version": new_version.to_dict(),
    }


@router.post("/{skill_id}/rollback")
async def rollback_skill_version(
    skill_id: uuid.UUID,
    payload: RollbackVersionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Roll back a skill to a prior version number by cloning its steps into a new incremented version."""
    ensure_authenticated_non_guest(user)
    repo = SkillRepository(session)

    try:
        skill = await repo.rollback_version(
            skill_id=skill_id,
            user_id=user.id,
            target_version_number=payload.target_version_number,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )

    return {
        "message": f"Successfully rolled back to contents of version {payload.target_version_number}.",
        "skill": skill.to_dict(),
    }


@router.post("/{skill_id}/health")
async def set_skill_health(
    skill_id: uuid.UUID,
    payload: SetHealthRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Manually update or reactivate a skill's health status."""
    ensure_authenticated_non_guest(user)
    valid_statuses = ("healthy", "degraded", "suspended")
    if payload.health_status.lower() not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid health status. Must be one of {valid_statuses}.",
        )

    repo = SkillRepository(session)
    skill = await repo.set_health_status(
        skill_id=skill_id,
        user_id=user.id,
        health_status=payload.health_status,
    )
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )

    return {"skill": skill.to_dict()}


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a skill and all its versions and execution history."""
    ensure_authenticated_non_guest(user)
    repo = SkillRepository(session)
    deleted = await repo.delete_skill(skill_id, user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found or access denied.",
        )

    return {"message": "Skill deleted successfully.", "skill_id": str(skill_id)}
