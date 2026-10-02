"""
Desktop Demonstration Observer for Windows.
Monitors foreground window focus and user interactions for desktop applications (Word, Excel, etc.).
Enforces process/window scoping, sensitive credential dialog masking, and filters out-of-scope interactions.
"""
from __future__ import annotations
import asyncio
import logging
import sys
import time
from typing import Any, Dict, Optional

from backend.agent.skills.session import session_manager

logger = logging.getLogger("nexus.skills.desktop_observer")

# Sensitive desktop window patterns to avoid capturing
SENSITIVE_WINDOW_KEYWORDS = (
    "credential", "security", "uac", "user account control", 
    "windows security", "password", "sign in", "pin"
)


class DesktopDemonstrationObserver:
    _instance: Optional[DesktopDemonstrationObserver] = None

    def __init__(self):
        self._active_session_id: Optional[str] = None
        self._target_process: Optional[str] = None
        self._target_hwnd: Optional[int] = None
        self._is_observing: bool = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_window_title: str = ""

    @classmethod
    def get_instance(cls) -> DesktopDemonstrationObserver:
        if cls._instance is None:
            cls._instance = DesktopDemonstrationObserver()
        return cls._instance

    def is_observing(self) -> bool:
        return self._is_observing

    def _get_active_window_info(self) -> tuple[Optional[int], str, str]:
        """Returns (hwnd, window_title, process_name) for current foreground window."""
        if sys.platform != "win32":
            return None, "non-windows", "unknown"

        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None, "", ""

            # Window text
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value

            # Process Name
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            import psutil
            try:
                proc = psutil.Process(pid.value)
                pname = proc.name()
            except Exception:
                pname = "unknown"

            return hwnd, title, pname
        except Exception as e:
            logger.debug(f"[DesktopObserver] Error inspecting active window: {e}")
            return None, "", ""

    def is_sensitive_window(self, title: str) -> bool:
        t_lower = title.lower()
        return any(kw in t_lower for kw in SENSITIVE_WINDOW_KEYWORDS)

    async def _poll_loop(self):
        """Poll foreground window changes and record focus transitions within scope."""
        logger.info(f"[DesktopObserver] Started polling for target process: {self._target_process}")
        while self._is_observing:
            try:
                hwnd, title, pname = self._get_active_window_info()
                if hwnd and title:
                    # Sensitive window check
                    if self.is_sensitive_window(title):
                        # Suppress event capture for security dialogs
                        await asyncio.sleep(0.3)
                        continue

                    # Process scope check: if target_process is defined, ignore events from other applications
                    if self._target_process and self._target_process.lower() not in pname.lower():
                        await asyncio.sleep(0.3)
                        continue

                    # If window changed within scope, record window focus event
                    if title != self._last_window_title:
                        self._last_window_title = title
                        if self._active_session_id:
                            await session_manager.record_event(
                                self._active_session_id,
                                {
                                    "environment": "desktop",
                                    "event_type": "window_focus",
                                    "target_app": pname,
                                    "value": title,
                                    "metadata": {
                                        "hwnd": hwnd,
                                        "process_name": pname,
                                        "window_title": title,
                                    },
                                }
                            )
            except Exception as e:
                logger.debug(f"[DesktopObserver] Polling iteration error: {e}")

            await asyncio.sleep(0.25)

    async def start_observing(self, session_id: str, target_process: Optional[str] = None) -> bool:
        """Start tracking desktop window activity for the target session."""
        if self._is_observing:
            await self.stop_observing()

        self._active_session_id = session_id
        self._target_process = target_process
        self._is_observing = True
        self._last_window_title = ""

        # Capture initial foreground window
        hwnd, title, pname = self._get_active_window_info()
        self._target_hwnd = hwnd

        loop = asyncio.get_running_loop()
        self._poll_task = loop.create_task(self._poll_loop())
        return True

    async def stop_observing(self) -> bool:
        """Stop tracking desktop window activity."""
        self._is_observing = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            self._poll_task = None

        self._active_session_id = None
        self._target_process = None
        self._target_hwnd = None
        logger.info("[DesktopObserver] Stopped desktop demonstration observer.")
        return True


desktop_observer = DesktopDemonstrationObserver.get_instance()
