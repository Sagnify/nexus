"""
Recommendation Data Foundation API.
Exposes activity summaries and usage metrics for the authenticated user.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.firebase_auth import get_current_user
from backend.database.models import User
from backend.database.session import get_db_session
from backend.database.repositories.recommendation_repo import RecommendationRepository
from backend.services.safety_filter import filter_safe_recommendations

router = APIRouter()


@router.get("/activity-summary")
async def get_activity_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return aggregated activity patterns and suggestions for the authenticated user."""
    repo = RecommendationRepository(session)
    summary = await repo.get_activity_summary(user.id)
    if "suggested_reruns" in summary and isinstance(summary["suggested_reruns"], list):
        summary["suggested_reruns"] = filter_safe_recommendations(summary["suggested_reruns"], query_key="prompt")
    return {
        "user_id": str(user.id),
        "summary": summary,
    }


@router.get("/patterns")
async def get_user_patterns(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return verified successful query patterns for personalized Spotlight autocomplete."""
    repo = RecommendationRepository(session)
    recent_successful = await repo.get_recent_successful_tasks(user.id, limit=30)
    safe_successful = filter_safe_recommendations(recent_successful, query_key="prompt")
    top_apps = await repo.get_frequent_applications(user.id, limit=10)
    return {
        "user_id": str(user.id),
        "successful_prompts": safe_successful,
        "frequent_apps": top_apps,
    }

