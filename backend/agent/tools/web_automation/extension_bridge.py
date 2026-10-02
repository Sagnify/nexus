"""Fast WebSocket bridge connecting NEXUS agent to the NEXUS Chrome Companion Extension."""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional
from fastapi import WebSocket

logger = logging.getLogger("nexus.extension_bridge")


class ExtensionBridge:
    """Manages active WebSocket connections to the NEXUS Chrome Companion Extension."""
    _instance: Optional[ExtensionBridge] = None

    def __init__(self):
        self._active_socket: Optional[WebSocket] = None
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> ExtensionBridge:
        if cls._instance is None:
            cls._instance = ExtensionBridge()
        return cls._instance

    def is_connected(self) -> bool:
        return self._active_socket is not None

    async def wait_for_connection(self, timeout_seconds: float = 3.5) -> bool:
        """Wait up to timeout_seconds for the extension to establish a WebSocket connection."""
        if self.is_connected():
            return True
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout_seconds:
            await asyncio.sleep(0.15)
            if self.is_connected():
                return True
        return False

    async def register_socket(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._active_socket = websocket
            logger.info("🟢 NEXUS Chrome Companion Extension connected to bridge.")

    async def unregister_socket(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self._active_socket == websocket:
                self._active_socket = None
                # Cancel pending futures
                for fut in self._pending_requests.values():
                    if not fut.done():
                        fut.cancel()
                self._pending_requests.clear()
                logger.info("🔴 NEXUS Chrome Companion Extension disconnected from bridge.")

    def handle_incoming_message(self, message_str: str) -> None:
        try:
            data = json.loads(message_str)
            msg_type = data.get("type")
            if msg_type and msg_type in ("ping", "cancel", "pause", "resume", "input", "user_input", "teach_event", "teach_action", "register"):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop:
                    if msg_type == "ping":
                        async def _reply_pong():
                            try:
                                if self._active_socket:
                                    await self._active_socket.send_text(json.dumps({"type": "pong", "time": time.time()}))
                            except Exception:
                                pass
                        loop.create_task(_reply_pong())
                    elif msg_type == "cancel":
                        from backend.api.nexus import cancel_task
                        loop.create_task(cancel_task())
                    elif msg_type == "pause":
                        from backend.api.nexus import pause_task
                        loop.create_task(pause_task())
                    elif msg_type == "resume":
                        from backend.api.nexus import resume_task
                        loop.create_task(resume_task())
                    elif msg_type in ("input", "user_input"):
                        from backend.api.nexus import submit_user_input, UserInputSubmission
                        val = data.get("value", "")
                        tid = data.get("task_id")
                        loop.create_task(submit_user_input(UserInputSubmission(value=val, task_id=tid)))
                    elif msg_type == "teach_event":
                        from backend.agent.skills.session import session_manager
                        sid = data.get("session_id")
                        event_payload = data.get("event")
                        if event_payload:
                            async def _record_safe(s_id: Optional[str], ev: dict):
                                sess = await session_manager.get_session(s_id) if s_id else None
                                if not sess:
                                    sess = await session_manager.get_active_session_for_user("")
                                if sess:
                                    await session_manager.record_event(sess.session_id, ev)
                            loop.create_task(_record_safe(sid, event_payload))
                    elif msg_type == "teach_action":
                        action = data.get("action")
                        sid = data.get("session_id")
                        from backend.agent.skills.session import session_manager

                        async def _handle_teach_action(s_id: Optional[str], act: str):
                            sess = await session_manager.get_session(s_id) if s_id else None
                            if not sess:
                                sess = await session_manager.get_active_session_for_user("")
                            if not sess:
                                logger.warning(f"Could not find teach session {s_id} for action {act}")
                                return
                            u_id = sess.user_id
                            resolved_sid = sess.session_id
                            if act == "finish":
                                await session_manager.complete_session(resolved_sid, u_id)
                            elif act == "discard":
                                await session_manager.discard_session(resolved_sid, u_id)
                            elif act == "pause":
                                await session_manager.pause_session(resolved_sid, u_id)
                            elif act == "resume":
                                await session_manager.resume_session(resolved_sid, u_id)

                        if action:
                            loop.create_task(_handle_teach_action(sid, action))
                    elif msg_type == "register":
                        from backend.agent.skills.session import session_manager

                        async def _sync_active_teach():
                            try:
                                active_list = list(session_manager._active_sessions.values())
                                for s in active_list:
                                    if s.status == "recording" and s.target_environment in ("browser", "mixed"):
                                        await self.send_command("start_teach_mode", {
                                            "session_id": s.session_id,
                                            "prompt": s.prompt_intent or "",
                                        }, timeout=6.0)
                                        logger.info(f"Auto-synced active teach session {s.session_id} to newly connected Chrome extension.")
                                        break
                            except Exception as e:
                                logger.debug(f"Could not auto-sync teach session to registered extension: {e}")

                        loop.create_task(_sync_active_teach())
                return

            msg_id = data.get("id")
            if msg_id and msg_id in self._pending_requests:
                fut = self._pending_requests.pop(msg_id)
                if not fut.done():
                    if data.get("success", False):
                        fut.set_result(data.get("data", {}))
                    else:
                        fut.set_exception(RuntimeError(data.get("error", "Extension error")))
        except Exception as e:
            logger.debug(f"Error parsing incoming extension message: {e}")

    async def send_command(self, action: str, payload: dict | None = None, timeout: float = 8.0) -> dict:
        if not self._active_socket:
            raise RuntimeError("NEXUS Chrome Extension is not currently connected.")

        msg_id = str(uuid.uuid4())
        msg = {
            "id": msg_id,
            "action": action,
            "payload": payload or {}
        }

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_requests[msg_id] = fut

        try:
            await self._active_socket.send_text(json.dumps(msg))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise TimeoutError(f"Extension command '{action}' timed out after {timeout}s.")
        except Exception:
            self._pending_requests.pop(msg_id, None)
            raise


extension_bridge = ExtensionBridge.get_instance()
