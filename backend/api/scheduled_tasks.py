"""
Scheduled Task API Router.
Endpoints for managing scheduled reminders and automated tasks, natural language parsing,
and run history execution tracking.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.firebase_auth import get_current_user
from backend.database.models import User
from backend.database.session import get_db_session
from backend.database.repositories.scheduled_task_repo import ScheduledTaskRepository
from backend.services.schedule_parser import schedule_parser, calculate_next_run
from backend.services.scheduler_service import scheduler_service
from backend.core.device_identity import get_device_id

logger = logging.getLogger("nexus.api.scheduled_tasks")
router = APIRouter()


class CreateScheduledTaskRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    prompt: str = Field(..., min_length=1)
    task_type: str = Field("reminder", pattern="^(reminder|automation)$")
    schedule_type: str = Field("one_time", pattern="^(one_time|recurring)$")
    schedule_definition: dict[str, Any] = Field(default_factory=dict)
    timezone: str = "Asia/Kolkata"
    missed_policy: str = Field("skip", pattern="^(skip|run_once)$")
    description: Optional[str] = None
    normalized_intent: Optional[dict[str, Any]] = None
    execution_config: Optional[dict[str, Any]] = None


class UpdateScheduledTaskRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_definition: Optional[dict[str, Any]] = None
    timezone: Optional[str] = None
    missed_policy: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    normalized_intent: Optional[dict[str, Any]] = None
    execution_config: Optional[dict[str, Any]] = None


class ParseScheduleRequest(BaseModel):
    text: str = Field(..., min_length=1)
    timezone: Optional[str] = "Asia/Kolkata"


@router.get("", response_model=List[dict])
async def list_scheduled_tasks(
    task_type: Optional[str] = Query(None, pattern="^(reminder|automation)$"),
    enabled: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List scheduled tasks belonging to the current user."""
    repo = ScheduledTaskRepository(session)
    tasks = await repo.list_user_tasks(
        user_id=user.id,
        task_type=task_type,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return [t.to_dict() for t in tasks]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_scheduled_task(
    req: CreateScheduledTaskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create and persist a new scheduled task."""
    repo = ScheduledTaskRepository(session)
    next_run = calculate_next_run(req.schedule_type, req.schedule_definition, req.timezone)

    norm_intent = req.normalized_intent
    exec_cfg = req.execution_config
    if not norm_intent or not exec_cfg:
        _, inferred_intent, inferred_cfg = schedule_parser._extract_automation_metadata(
            req.prompt, req.prompt, is_explicit_reminder=(req.task_type == "reminder")
        )
        norm_intent = norm_intent or inferred_intent
        exec_cfg = exec_cfg or inferred_cfg

    task = await repo.create_scheduled_task(
        user_id=user.id,
        name=req.name,
        prompt=req.prompt,
        task_type=req.task_type,
        schedule_type=req.schedule_type,
        schedule_definition=req.schedule_definition,
        timezone=req.timezone,
        next_run_at=next_run,
        description=req.description,
        missed_policy=req.missed_policy,
        normalized_intent=norm_intent,
        execution_config=exec_cfg,
    )
    await session.commit()
    return task.to_dict()


@router.post("/parse")
async def parse_schedule_text(
    req: ParseScheduleRequest,
    user: User = Depends(get_current_user),
):
    """Parse natural language schedule and detect ambiguities."""
    result = await schedule_parser.parse(req.text, req.timezone)
    return result.model_dump()


@router.post("/create-from-text", status_code=status.HTTP_201_CREATED)
async def create_from_natural_language(
    req: ParseScheduleRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Parse natural language and create task directly if unambiguous."""
    result = await schedule_parser.parse(req.text, req.timezone)
    if not result.is_schedule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not detect a scheduling intent in the provided text.",
        )
    if result.is_ambiguous:
        return {
            "created": False,
            "is_ambiguous": True,
            "clarification_question": result.clarification_question,
            "parsed": result.model_dump(),
        }

    repo = ScheduledTaskRepository(session)
    task = await repo.create_scheduled_task(
        user_id=user.id,
        name=result.name or "Scheduled Task",
        prompt=result.prompt or req.text,
        task_type=result.task_type,
        schedule_type=result.schedule_type,
        schedule_definition=result.schedule_definition,
        timezone=result.timezone,
        next_run_at=result.next_run_at,
        normalized_intent=result.normalized_intent,
        execution_config=result.execution_config,
    )
    await session.commit()
    return {
        "created": True,
        "is_ambiguous": False,
        "task": task.to_dict(),
    }


@router.get("/device-id")
async def get_local_device_id(user: User = Depends(get_current_user)):
    """Return this installation's opaque ID for labeling/assigning user schedules."""
    return {"device_id": get_device_id()}


@router.get("/{task_id}")
async def get_scheduled_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get scheduled task details."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")
    return task.to_dict()


@router.patch("/{task_id}")
async def update_scheduled_task(
    task_id: uuid.UUID,
    req: UpdateScheduledTaskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a scheduled task and recalculate next_run_at if schedule altered."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")

    update_data = req.model_dump(exclude_unset=True)

    # If schedule or timezone changed, recalculate next_run_at
    if "schedule_definition" in update_data or "timezone" in update_data or "schedule_type" in update_data:
        sched_type = update_data.get("schedule_type", task.schedule_type)
        sched_def = update_data.get("schedule_definition", task.schedule_definition)
        tz_str = update_data.get("timezone", task.timezone)
        update_data["next_run_at"] = calculate_next_run(sched_type, sched_def, tz_str)

    updated = await repo.update_scheduled_task(task_id, user_id=user.id, **update_data)
    await session.commit()
    return updated.to_dict()


@router.delete("/{task_id}")
async def delete_scheduled_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete a scheduled task."""
    repo = ScheduledTaskRepository(session)
    success = await repo.delete_scheduled_task(task_id, user_id=user.id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")
    await session.commit()
    return {"status": "deleted", "id": str(task_id)}


@router.post("/{task_id}/pause")
async def pause_scheduled_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Pause an active scheduled task."""
    repo = ScheduledTaskRepository(session)
    task = await repo.toggle_enabled(task_id, user_id=user.id, enabled=False)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")
    await session.commit()
    return task.to_dict()


@router.post("/{task_id}/resume")
async def resume_scheduled_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Resume a paused scheduled task and recalculate next_run_at."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")
    if task.device_id != get_device_id():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This schedule belongs to another device. Move it to this device before resuming.",
        )

    next_run = calculate_next_run(task.schedule_type, task.schedule_definition, task.timezone)
    task.enabled = True
    task.next_run_at = next_run
    await session.commit()
    return task.to_dict()


@router.post("/{task_id}/move-to-this-device")
async def move_scheduled_task_to_this_device(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Explicitly transfer a user's schedule to the device making this request."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")

    device_id = get_device_id()
    next_run = calculate_next_run(task.schedule_type, task.schedule_definition, task.timezone)
    metadata = dict(task.metadata_json or {})
    metadata.pop("device_binding_required", None)
    updated = await repo.update_scheduled_task(
        task_id,
        user_id=user.id,
        device_id=device_id,
        enabled=True,
        next_run_at=next_run,
        metadata_json=metadata,
    )
    await session.commit()
    return updated.to_dict()


@router.post("/{task_id}/run-now")
async def run_scheduled_task_now(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Immediately trigger a scheduled task ad-hoc."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")
    if task.device_id != get_device_id():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This schedule belongs to another device. Move it here before running it.",
        )

    run = await scheduler_service.trigger_run_now(task.id, user.id)
    if not run:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to trigger task run.")
    return {"status": "triggered", "run_id": str(run.id), "scheduled_task_id": str(task.id)}


@router.get("/{task_id}/runs")
async def list_scheduled_task_runs(
    task_id: uuid.UUID,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List execution history and logs for a scheduled task."""
    repo = ScheduledTaskRepository(session)
    task = await repo.get_by_id(task_id, user_id=user.id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found.")

    runs = await repo.list_task_runs(scheduled_task_id=task.id, user_id=user.id, limit=limit)
    return [r.to_dict() for r in runs]

