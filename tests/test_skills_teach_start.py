import datetime
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend.api import skills
from backend.agent.skills.session import DemonstrationSessionManager
from backend.agent.tools.web_automation.extension_bridge import ExtensionBridge


class FakeSessionManager:
    def __init__(self):
        self.discarded = []

    async def start_session(self, user_id, target_environment, prompt_intent):
        return SimpleNamespace(
            session_id="teach-test-session",
            status="recording",
            target_environment=target_environment,
            started_at=datetime.datetime.now(datetime.timezone.utc),
            prompt_intent=prompt_intent,
        )

    async def discard_session(self, session_id, user_id):
        self.discarded.append((session_id, user_id))


class FakeExtensionBridge:
    def __init__(self, connected=True, command_result=None):
        self.connected = connected
        self.command_result = command_result or {"success": True}
        self.commands = []

    def is_connected(self):
        return self.connected

    async def wait_for_connection(self, timeout_seconds):
        return self.connected

    async def send_command(self, action, payload, timeout):
        self.commands.append((action, payload, timeout))
        return self.command_result


class TestBrowserTeachStart(unittest.IsolatedAsyncioTestCase):
    async def test_browser_start_waits_for_extension_acknowledgement(self):
        session_manager = FakeSessionManager()
        extension_bridge = FakeExtensionBridge()
        user = SimpleNamespace(id="user-1", firebase_uid="firebase-user", email="user@example.com")

        with (
            patch("backend.agent.skills.session.session_manager", session_manager),
            patch("backend.agent.tools.web_automation.extension_bridge.extension_bridge", extension_bridge),
        ):
            response = await skills.start_teach_session(
                skills.StartTeachRequest(prompt="Search a site", target_environment="browser"),
                user,
            )

        self.assertEqual(response["status"], "recording")
        self.assertTrue(response["extension_connected"])
        self.assertEqual(extension_bridge.commands[0][0], "start_teach_mode")
        self.assertEqual(extension_bridge.commands[0][1]["session_id"], response["session_id"])

    async def test_browser_start_fails_and_discards_session_without_extension(self):
        session_manager = FakeSessionManager()
        extension_bridge = FakeExtensionBridge(connected=False)
        user = SimpleNamespace(id="user-1", firebase_uid="firebase-user", email="user@example.com")

        with (
            patch("backend.agent.skills.session.session_manager", session_manager),
            patch("backend.agent.tools.web_automation.extension_bridge.extension_bridge", extension_bridge),
        ):
            with self.assertRaises(HTTPException) as raised:
                await skills.start_teach_session(
                    skills.StartTeachRequest(prompt="Search a site", target_environment="browser"),
                    user,
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(session_manager.discarded, [("teach-test-session", "user-1")])
        self.assertEqual(extension_bridge.commands, [])

    async def test_browser_start_with_fallback_switches_to_desktop_when_extension_offline(self):
        session_manager = FakeSessionManager()
        extension_bridge = FakeExtensionBridge(connected=False)
        user = SimpleNamespace(id="user-1", firebase_uid="firebase-user", email="user@example.com")

        with (
            patch("backend.agent.skills.session.session_manager", session_manager),
            patch("backend.agent.tools.web_automation.extension_bridge.extension_bridge", extension_bridge),
        ):
            response = await skills.start_teach_session(
                skills.StartTeachRequest(prompt="Search a site", target_environment="browser", allow_desktop_fallback=True),
                user,
            )

        self.assertEqual(response["status"], "recording")
        self.assertEqual(response["target_environment"], "desktop")
        self.assertFalse(response["extension_connected"])
        self.assertEqual(session_manager.discarded, [])

    async def test_extension_teach_event_reaches_session_buffer(self):
        session_manager = DemonstrationSessionManager()
        session = await session_manager.start_session(
            user_id="user-1",
            target_environment="browser",
            prompt_intent="Search a site",
        )
        bridge = ExtensionBridge()
        event = {
            "environment": "browser",
            "event_type": "click",
            "url": "https://example.com",
            "selector_bundle": {"ariaLabel": "Search"},
        }

        with patch("backend.agent.skills.session.session_manager", session_manager):
            bridge.handle_incoming_message(json.dumps({
                "type": "teach_event",
                "session_id": session.session_id,
                "event": event,
            }))
            await asyncio.sleep(0)

        active_session = await session_manager.get_session(session.session_id)
        self.assertEqual(len(active_session.events), 1)
        self.assertEqual(active_session.events[0].event_type, "click")

    async def test_skill_owner_id_rejects_missing_or_invalid_identity(self):
        from backend.api.skills import _skill_owner_uuid

        account_id = "d66bb2a7-3b7b-4314-a23f-257892c72d0f"
        self.assertEqual(str(_skill_owner_uuid(account_id)), account_id)
        for invalid_id in ("", "not-a-uuid"):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ValueError):
                    _skill_owner_uuid(invalid_id)


if __name__ == "__main__":
    unittest.main()