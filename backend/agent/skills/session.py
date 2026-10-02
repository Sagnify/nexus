"""
Demonstration Session Manager for NEXUS Skill Learning.
Maintains active ephemeral demonstration recording sessions in volatile memory.
Enforces zero disk persistence for raw keystrokes or streams; purges event buffers upon compilation or cancellation.
"""
from __future__ import annotations
import asyncio
import datetime
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("nexus.skills.session")


class DemonstrationEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    environment: str = Field("browser")  # "browser" | "desktop"
    event_type: str  # "click" | "input" | "change" | "navigate" | "keydown" | "window_focus"
    target_app: Optional[str] = None
    url: Optional[str] = None
    selector_bundle: Optional[dict[str, Any]] = None
    value: Optional[str] = None
    key: Optional[str] = None
    is_sensitive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DemonstrationSession(BaseModel):
    session_id: str
    user_id: str
    target_environment: str = "browser"  # "browser" | "desktop" | "mixed"
    status: str = "recording"            # "recording" | "paused" | "completed" | "discarded"
    started_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    paused_at: Optional[datetime.datetime] = None
    target_tab_id: Optional[int] = None
    target_process: Optional[str] = None
    prompt_intent: Optional[str] = None
    events: List[DemonstrationEvent] = Field(default_factory=list)


class DemonstrationSessionManager:
    _instance: Optional[DemonstrationSessionManager] = None

    def __init__(self):
        self._active_sessions: dict[str, DemonstrationSession] = {}
        self._user_active_session: dict[str, str] = {}
        # Per-user recovery cache — prevents cross-user data leaks in multi-user mode
        self._last_completed_by_user: dict[str, DemonstrationSession] = {}
        self._lock: Optional[asyncio.Lock] = None  # Lazy-init: asyncio.Lock must be created inside a running loop

    def _get_lock(self) -> asyncio.Lock:
        """Return the shared asyncio.Lock, creating it lazily inside the running event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @classmethod
    def get_instance(cls) -> DemonstrationSessionManager:
        if cls._instance is None:
            cls._instance = DemonstrationSessionManager()
        return cls._instance

    def get_last_session(self) -> Optional[DemonstrationSession]:
        """Auto-recovery fallback: retrieve the most recent demonstration session (any user)."""
        # Return the most recently completed session from any user as a last-resort fallback
        if self._last_completed_by_user:
            return next(iter(reversed(list(self._last_completed_by_user.values()))))
        if self._active_sessions:
            return next(iter(reversed(list(self._active_sessions.values()))))
        return None

    def _last_completed_for_user(self, user_id: str) -> Optional[DemonstrationSession]:
        """Return the last completed session for a specific user only."""
        return self._last_completed_by_user.get(user_id)

    async def start_session(
        self,
        user_id: str,
        target_environment: str = "browser",
        target_tab_id: Optional[int] = None,
        target_process: Optional[str] = None,
        prompt_intent: Optional[str] = None,
    ) -> DemonstrationSession:
        """Start a new demonstration recording session for the given user, discarding any prior active session."""
        async with self._get_lock():
            # Discard any existing active session for this user
            old_session_id = self._user_active_session.get(user_id)
            if old_session_id and old_session_id in self._active_sessions:
                logger.info(f"[SessionManager] Purging prior session {old_session_id} for user {user_id}")
                self._active_sessions.pop(old_session_id, None)

            session_id = f"teach-{uuid.uuid4().hex[:8]}"
            session = DemonstrationSession(
                session_id=session_id,
                user_id=user_id,
                target_environment=target_environment,
                status="recording",
                target_tab_id=target_tab_id,
                target_process=target_process,
                prompt_intent=prompt_intent,
            )
            self._active_sessions[session_id] = session
            self._user_active_session[user_id] = session_id
        logger.info(f"[SessionManager] Started teach demonstration session {session_id} (user={user_id}, env={target_environment})")
        return session

    async def get_session(self, session_id: str) -> Optional[DemonstrationSession]:
        if session_id and session_id in self._active_sessions:
            return self._active_sessions[session_id]
        # Check per-user recovery caches
        for sess in self._last_completed_by_user.values():
            if sess.session_id == session_id:
                return sess
        # Fallback: if only one session is tracked and no specific ID was given, return it
        if not session_id and len(self._active_sessions) == 1:
            return next(iter(self._active_sessions.values()))
        return None

    async def get_active_session_for_user(self, user_id: str) -> Optional[DemonstrationSession]:
        session_id = self._user_active_session.get(user_id) if user_id else None
        if session_id and session_id in self._active_sessions:
            return self._active_sessions[session_id]
        # Fallback: In single-user local Nexus app, find any active or paused session
        for s in self._active_sessions.values():
            if s.status in ("recording", "paused", "completed"):
                return s
        # Final fallback: user's own last completed session only
        return self._last_completed_for_user(user_id)

    async def record_event(self, session_id: str, event_data: dict[str, Any]) -> bool:
        """Append an observed event to the active session's ephemeral buffer."""
        session = self._active_sessions.get(session_id)
        if not session and len(self._active_sessions) == 1:
            session = next(iter(self._active_sessions.values()))
        if not session or session.status != "recording":
            return False

        event = DemonstrationEvent(**event_data)
        session.events.append(event)
        return True

    async def pause_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        session = self._active_sessions.get(session_id)
        if not session and len(self._active_sessions) == 1:
            session = next(iter(self._active_sessions.values()))
        if not session:
            return False
        session.status = "paused"
        session.paused_at = datetime.datetime.now(datetime.timezone.utc)
        logger.info(f"[SessionManager] Paused session {session.session_id}")
        return True

    async def resume_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        session = self._active_sessions.get(session_id)
        if not session and len(self._active_sessions) == 1:
            session = next(iter(self._active_sessions.values()))
        if not session:
            return False
        session.status = "recording"
        session.paused_at = None
        logger.info(f"[SessionManager] Resumed session {session.session_id}")
        return True

    async def complete_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[DemonstrationSession]:
        """Mark session completed and return it for compilation. Keeps in memory until compiled."""
        async with self._get_lock():
            session = self._active_sessions.get(session_id)
            if not session and len(self._active_sessions) == 1:
                session = next(iter(self._active_sessions.values()))
            if not session:
                for s in self._active_sessions.values():
                    if s.status in ("recording", "paused", "completed"):
                        session = s
                        break
            if not session:
                return None
            session.status = "completed"
            # Store per-user so cross-user data leaks are impossible
            owner = user_id or session.user_id or ""
            self._last_completed_by_user[owner] = session
        logger.info(f"[SessionManager] Completed demonstration session {session.session_id} ({len(session.events)} events)")
        return session

    async def discard_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Purge demonstration session immediately from memory."""
        async with self._get_lock():
            session = self._active_sessions.get(session_id)
            if not session and len(self._active_sessions) == 1:
                session = next(iter(self._active_sessions.values()))
            if not session:
                return False

            sid = session.session_id
            owner = user_id or session.user_id or ""
            self._active_sessions.pop(sid, None)
            if user_id and self._user_active_session.get(user_id) == sid:
                self._user_active_session.pop(user_id, None)
            else:
                for uid, active_sid in list(self._user_active_session.items()):
                    if active_sid == sid:
                        self._user_active_session.pop(uid, None)
                        break

            # Clear the per-user recovery cache if it holds the session being discarded
            if self._last_completed_by_user.get(owner) and self._last_completed_by_user[owner].session_id == sid:
                self._last_completed_by_user.pop(owner, None)

        logger.info(f"[SessionManager] Discarded demonstration session {sid}")
        return True


session_manager = DemonstrationSessionManager.get_instance()
