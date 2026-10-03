"""
Email Cache Service - Persistent fallback for Gmail connector failures.
Stores fetched emails locally and returns cached data when connector is unavailable.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("nexus.email_cache")


class EmailCacheService:
    """Manages persistent email cache with TTL and fallback logic."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            from backend.core.paths import get_nexus_data_dir
            cache_dir = get_nexus_data_dir() / "email_cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "emails.json"
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        self.cache_ttl_hours = 24

    def save_emails(self, user_id: str, emails: list[dict], metadata: Optional[dict] = None) -> bool:
        """Save fetched emails to cache with timestamp."""
        try:
            cache_data = self._load_cache()
            cache_data[user_id] = {
                "emails": emails,
                "timestamp": datetime.now().isoformat(),
                "count": len(emails),
                "metadata": metadata or {},
            }
            with open(self.cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"[EmailCache] Saved {len(emails)} emails for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"[EmailCache] Failed to save emails: {e}")
            return False

    def get_cached_emails(self, user_id: str, check_ttl: bool = True) -> Optional[list[dict]]:
        """Retrieve cached emails if available and not expired."""
        try:
            cache_data = self._load_cache()
            if user_id not in cache_data:
                logger.debug(f"[EmailCache] No cached emails for user {user_id}")
                return None

            entry = cache_data[user_id]
            timestamp_str = entry.get("timestamp")
            
            if check_ttl and timestamp_str:
                cached_time = datetime.fromisoformat(timestamp_str)
                age_hours = (datetime.now() - cached_time).total_seconds() / 3600
                
                if age_hours > self.cache_ttl_hours:
                    logger.info(f"[EmailCache] Cache expired for user {user_id} (age: {age_hours:.1f}h)")
                    return None
                
                logger.debug(f"[EmailCache] Using cached emails for user {user_id} (age: {age_hours:.1f}h)")
            
            return entry.get("emails", [])
        except Exception as e:
            logger.error(f"[EmailCache] Failed to retrieve cached emails: {e}")
            return None

    def get_cache_metadata(self, user_id: str) -> Optional[dict]:
        """Get cache metadata including timestamp and count."""
        try:
            cache_data = self._load_cache()
            if user_id in cache_data:
                entry = cache_data[user_id]
                return {
                    "timestamp": entry.get("timestamp"),
                    "count": entry.get("count", 0),
                    "metadata": entry.get("metadata", {}),
                    "is_stale": self._is_cache_stale(entry.get("timestamp")),
                }
            return None
        except Exception as e:
            logger.error(f"[EmailCache] Failed to get cache metadata: {e}")
            return None

    def clear_cache(self, user_id: Optional[str] = None) -> bool:
        """Clear cache for specific user or all users."""
        try:
            if user_id:
                cache_data = self._load_cache()
                if user_id in cache_data:
                    del cache_data[user_id]
                    with open(self.cache_file, "w") as f:
                        json.dump(cache_data, f, indent=2)
                    logger.info(f"[EmailCache] Cleared cache for user {user_id}")
            else:
                self.cache_file.unlink(missing_ok=True)
                logger.info("[EmailCache] Cleared all email cache")
            return True
        except Exception as e:
            logger.error(f"[EmailCache] Failed to clear cache: {e}")
            return False

    def _load_cache(self) -> dict:
        """Load cache from disk, return empty dict if not found."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[EmailCache] Failed to load cache file: {e}")
        return {}

    def _is_cache_stale(self, timestamp_str: Optional[str]) -> bool:
        """Check if cache entry is older than TTL."""
        if not timestamp_str:
            return True
        try:
            cached_time = datetime.fromisoformat(timestamp_str)
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            return age_hours > self.cache_ttl_hours
        except Exception:
            return True


# Global singleton instance
_email_cache_service: Optional[EmailCacheService] = None


def get_email_cache_service() -> EmailCacheService:
    """Get or create the global email cache service."""
    global _email_cache_service
    if _email_cache_service is None:
        _email_cache_service = EmailCacheService()
    return _email_cache_service
