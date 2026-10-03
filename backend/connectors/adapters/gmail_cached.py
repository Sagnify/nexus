"""
Gmail Connector with Automatic Caching & Fallback.
Wraps the standard Gmail connector to cache emails and provide fallback when unavailable.
"""
import logging
from typing import Optional, Any

from backend.services.email_cache_service import get_email_cache_service
from backend.connectors.adapters.google import GoogleConnector

logger = logging.getLogger("nexus.gmail_cached")


class CachedGmailConnector(GoogleConnector):
    """Gmail connector with automatic email caching and fallback support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_service = get_email_cache_service()

    async def list_messages(
        self,
        user_id: str,
        query: str = "is:unread",
        max_results: int = 10,
        use_cache_fallback: bool = True,
    ) -> dict[str, Any]:
        """
        List Gmail messages with automatic caching and fallback.
        
        Args:
            user_id: Gmail user ID
            query: Gmail search query
            max_results: Max messages to fetch
            use_cache_fallback: If True, use cached emails when connector fails
            
        Returns:
            Dict with messages list and cache status
        """
        try:
            # Try to fetch fresh emails from Gmail API
            result = await super().list_messages(user_id, query, max_results)
            messages = result.get("messages", [])
            
            # Cache successful fetch
            if messages:
                self.cache_service.save_emails(
                    user_id=user_id,
                    emails=messages,
                    metadata={"query": query, "max_results": max_results}
                )
                logger.info(f"[GmailCached] Cached {len(messages)} emails for user {user_id}")
            
            return {
                **result,
                "from_cache": False,
                "cache_status": "fresh",
            }
        
        except Exception as e:
            logger.warning(f"[GmailCached] Failed to fetch emails: {e}")
            
            if not use_cache_fallback:
                raise
            
            # Try to use cached emails as fallback
            cached_emails = self.cache_service.get_cached_emails(user_id, check_ttl=False)
            if cached_emails:
                cache_meta = self.cache_service.get_cache_metadata(user_id)
                logger.info(f"[GmailCached] Using {len(cached_emails)} cached emails for user {user_id}")
                return {
                    "messages": cached_emails,
                    "from_cache": True,
                    "cache_status": "stale" if cache_meta and cache_meta.get("is_stale") else "valid",
                    "cache_timestamp": cache_meta.get("timestamp") if cache_meta else None,
                    "error": f"Gmail connector unavailable, showing cached emails: {str(e)}",
                }
            
            # No cache available, re-raise original error
            logger.error(f"[GmailCached] No cached emails available, connector failed: {e}")
            raise

    async def get_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        """Get a specific message with cache support."""
        try:
            return await super().get_message(user_id, message_id)
        except Exception as e:
            logger.warning(f"[GmailCached] Failed to fetch message {message_id}: {e}")
            raise

    async def send_message(self, user_id: str, message: dict) -> dict[str, Any]:
        """Send a message (no caching needed for sends)."""
        return await super().send_message(user_id, message)

    def clear_cache(self, user_id: Optional[str] = None) -> bool:
        """Clear email cache for user or all users."""
        return self.cache_service.clear_cache(user_id)

    def get_cache_info(self, user_id: str) -> Optional[dict]:
        """Get cache metadata for debugging."""
        return self.cache_service.get_cache_metadata(user_id)
