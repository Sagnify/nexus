"""
Email API Endpoints with Caching & Fallback Support.
Provides email operations with automatic fallback to cached data.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.core.firebase_auth import get_current_user_optional
from backend.database.models import User
from backend.services.email_cache_service import get_email_cache_service

router = APIRouter(prefix="/api/email", tags=["email"])


class ListEmailsRequest(BaseModel):
    query: str = "is:unread"
    max_results: int = 10
    use_cache_fallback: bool = True


class EmailCacheInfo(BaseModel):
    has_cache: bool
    timestamp: Optional[str] = None
    count: int = 0
    is_stale: bool = False


@router.get("/cache-info")
async def get_email_cache_info(user: Optional[User] = Depends(get_current_user_optional)) -> EmailCacheInfo:
    """Get email cache status for current user."""
    if not user:
        return EmailCacheInfo(has_cache=False)
    
    cache_service = get_email_cache_service()
    meta = cache_service.get_cache_metadata(str(user.id))
    
    if not meta:
        return EmailCacheInfo(has_cache=False)
    
    return EmailCacheInfo(
        has_cache=True,
        timestamp=meta.get("timestamp"),
        count=meta.get("count", 0),
        is_stale=meta.get("is_stale", False),
    )


@router.post("/list")
async def list_emails(
    req: ListEmailsRequest,
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    List emails with automatic fallback to cache.
    
    Returns:
        - messages: List of email messages
        - from_cache: Boolean indicating if data is from cache
        - cache_status: 'fresh', 'stale', or 'error'
        - error: Error message if connector failed but cache was used
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    cache_service = get_email_cache_service()
    
    try:
        # Try to get cached emails first
        cached_emails = cache_service.get_cached_emails(str(user.id), check_ttl=True)
        if cached_emails:
            cache_meta = cache_service.get_cache_metadata(str(user.id))
            return {
                "messages": cached_emails,
                "from_cache": True,
                "cache_status": "fresh" if not cache_meta.get("is_stale") else "stale",
                "cache_timestamp": cache_meta.get("timestamp"),
            }
        
        # No cache available
        return {
            "messages": [],
            "from_cache": False,
            "cache_status": "none",
            "error": "No cached emails available. Gmail connector may be unavailable.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {str(e)}")


@router.post("/clear-cache")
async def clear_email_cache(user: Optional[User] = Depends(get_current_user_optional)) -> dict:
    """Clear email cache for current user."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    cache_service = get_email_cache_service()
    success = cache_service.clear_cache(str(user.id))
    
    return {
        "success": success,
        "message": "Email cache cleared" if success else "Failed to clear cache",
    }


@router.get("/cache-status")
async def get_cache_status(user: Optional[User] = Depends(get_current_user_optional)) -> dict:
    """Get detailed cache status for debugging."""
    if not user:
        return {"authenticated": False}
    
    cache_service = get_email_cache_service()
    meta = cache_service.get_cache_metadata(str(user.id))
    
    return {
        "authenticated": True,
        "user_id": str(user.id),
        "cache_available": meta is not None,
        "cache_metadata": meta,
    }
