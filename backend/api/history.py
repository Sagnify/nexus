"""
User Task & Execution History API endpoints.
Provides cloud history retrieval, synchronization from local storage, and task deletion.
Enforces strict user ownership on every operation.
"""
from __future__ import annotations
import datetime
import uuid
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.firebase_auth import get_current_user
from backend.database.models import User
from backend.database.session import get_db_session
from backend.database.repositories.task_repo import TaskRepository
from backend.core.privacy import normalize_task_category
from backend.services.safety_filter import classify_query_safety

router = APIRouter()


class LocalHistorySyncItem(BaseModel):
    id: str
    timestamp: int
    prompt: str
    mode: Optional[str] = "all"
    status: Optional[str] = "completed"
    finalResponse: Optional[str] = None
    error: Optional[str] = None
    stepCount: Optional[int] = 0


class SyncHistoryRequest(BaseModel):
    items: List[LocalHistorySyncItem]


@router.get("")
async def list_history(
    status_filter: Optional[str] = Query(None, alias="status"),
    category_filter: Optional[str] = Query(None, alias="category"),
    include_sensitive: bool = Query(False, alias="include_sensitive"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List authenticated user's task history from PostgreSQL (excluding sensitive queries by default)."""
    if session is None:
        return {"tasks": [], "count": 0, "limit": limit, "offset": offset}
    try:
        repo = TaskRepository(session)
        tasks = await repo.list_user_tasks(
            user_id=user.id,
            status=status_filter,
            task_type=category_filter,
            limit=limit,
            offset=offset,
        )
        if not include_sensitive:
            tasks = [t for t in tasks if not classify_query_safety(t.user_prompt or "").is_sensitive]

        return {
            "tasks": [t.to_dict() for t in tasks],
            "count": len(tasks),
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.warning(f"[History] Database query failed (offline/sleeping DB): {exc}")
        return {
            "tasks": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
        }


@router.get("/{task_id}")
async def get_task_details(
    task_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieve full execution trajectory for a task belonging to current user."""
    repo = TaskRepository(session)
    task = await repo.get_by_task_id(task_id, user.id)
    if not task:
        # Check UUID format as fallback
        try:
            u_id = uuid.UUID(task_id)
            task = await repo.get_by_id(u_id, user.id)
        except ValueError:
            pass

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_dict = task.to_dict()
    task_dict["events"] = [e.to_dict() for e in (task.events or [])]
    return task_dict


@router.post("/sync")
async def sync_local_history(
    payload: SyncHistoryRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Backfill or synchronize local browser tasks into PostgreSQL.
    Idempotently skips or updates existing items without duplicating.
    """
    repo = TaskRepository(session)
    synced_count = 0

    for item in payload.items:
        started_time = datetime.datetime.fromtimestamp(
            item.timestamp / 1000.0, tz=datetime.timezone.utc
        ) if item.timestamp else None

        cat = normalize_task_category(item.mode, item.prompt)
        task = await repo.upsert_task(
            task_id_str=item.id,
            user_id=user.id,
            user_prompt=item.prompt,
            task_type=cat,
            status=item.status or "completed",
            started_at=started_time,
        )
        await repo.update_task_completion(
            task_id_str=item.id,
            user_id=user.id,
            status=item.status or "completed",
            final_response=item.finalResponse,
            error=item.error,
            step_count=item.stepCount,
        )
        synced_count += 1

    return {
        "success": True,
        "synced": synced_count,
    }


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete a task and its execution events, enforcing ownership."""
    repo = TaskRepository(session)
    deleted = await repo.delete_task(task_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found or not owned by user")
    return {"success": True, "deleted_task_id": task_id}
