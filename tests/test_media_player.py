"""Unit tests for robust media and music playback automation (Desktop Spotify, VLC, Windows Media, Web Players & Smart Query Resolution)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from backend.agent.router.media_fastpath import extract_media_intent, build_media_plan
from backend.agent.tools.system.media_tool import MediaControlTool, PlayMusicTool, _resolve_music_query
from backend.agent.tools.web.search import WebSearchTool
from backend.agent.tools.base import ToolResult


class TestMediaFastpath(unittest.TestCase):
    def test_extract_media_controls(self):
        # Pause
        intent = extract_media_intent("pause the music")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["type"], "control")
        self.assertEqual(intent["action"], "pause")
        self.assertEqual(intent["target"], "auto")

        # Specific targets
        intent_sp = extract_media_intent("pause spotify")
        self.assertEqual(intent_sp["target"], "spotify")

        intent_vlc = extract_media_intent("pause vlc")
        self.assertEqual(intent_vlc["target"], "vlc")

        intent_wmp = extract_media_intent("pause windows media player")
        self.assertEqual(intent_wmp["target"], "wmplayer")

        intent_web = extract_media_intent("pause web player")
        self.assertEqual(intent_web["target"], "web")

        intent_yt = extract_media_intent("pause youtube")
        self.assertEqual(intent_yt["target"], "youtube")

        # Next / Skip
        intent_next = extract_media_intent("skip to next track")
        self.assertEqual(intent_next["action"], "next")

        # Volume
        intent_vol = extract_media_intent("turn the volume up")
        self.assertEqual(intent_vol["action"], "volume_up")

        # Mute
        intent_mute = extract_media_intent("mute the speakers")
        self.assertEqual(intent_mute["action"], "mute")

    def test_extract_music_playback_spotify(self):
        # Desktop Spotify
        intent = extract_media_intent("play bohemian rhapsody on spotify app")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["type"], "play")
        self.assertEqual(intent["service"], "spotify")
        self.assertTrue(intent["prefer_desktop"])
        self.assertIn("bohemian rhapsody", intent["query"])

        # Web Spotify
        intent_web = extract_media_intent("play lo-fi on spotify web")
        self.assertIsNotNone(intent_web)
        self.assertEqual(intent_web["service"], "spotify")
        self.assertFalse(intent_web["prefer_desktop"])
        self.assertIn("lo-fi", intent_web["query"])

        # Desktop Spotify with punctuation
        intent_hindi = extract_media_intent("Play Hindi music in Spotify.")
        self.assertIsNotNone(intent_hindi)
        self.assertEqual(intent_hindi["type"], "play")
        self.assertEqual(intent_hindi["service"], "spotify")
        self.assertEqual(intent_hindi["query"], "hindi music")

        # In Spotify play query
        intent_in = extract_media_intent("in spotify play arjit singh songs")
        self.assertIsNotNone(intent_in)
        self.assertEqual(intent_in["service"], "spotify")
        self.assertIn("arjit singh", intent_in["query"])

        # Search only on Spotify
        intent_search = extract_media_intent("search for Bohemian Rhapsody on Spotify")
        self.assertIsNotNone(intent_search)
        self.assertEqual(intent_search["type"], "play")
        self.assertEqual(intent_search["service"], "spotify")
        self.assertEqual(intent_search["query"].lower(), "bohemian rhapsody")
        self.assertFalse(intent_search["auto_play"])

        # Play specific track on Spotify
        intent_play = extract_media_intent("Play Back in Black from Spotify.")
        self.assertIsNotNone(intent_play)
        self.assertEqual(intent_play["type"], "play")
        self.assertEqual(intent_play["service"], "spotify")
        self.assertEqual(intent_play["query"].lower(), "back in black")
        self.assertTrue(intent_play["auto_play"])

        # Play from web
        intent_from_web = extract_media_intent("play starboy from web")
        self.assertIsNotNone(intent_from_web)
        self.assertFalse(intent_from_web["prefer_desktop"])

    def test_extract_music_playback_youtube(self):
        # YouTube
        intent_yt = extract_media_intent("play coldplay on youtube")
        self.assertIsNotNone(intent_yt)
        self.assertEqual(intent_yt["service"], "youtube")
        self.assertEqual(intent_yt["query"], "coldplay")

        # YouTube Music
        intent_ytm = extract_media_intent("play daft punk on youtube music")
        self.assertIsNotNone(intent_ytm)
        self.assertEqual(intent_ytm["service"], "youtube_music")
        self.assertEqual(intent_ytm["query"], "daft punk")

    def test_build_media_plan(self):
        plan = build_media_plan("pause the music")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["tool"], "media_control")
        self.assertEqual(plan[0]["args"]["action"], "pause")

        plan_play = build_media_plan("play starboy on spotify")
        self.assertIsNotNone(plan_play)
        self.assertIn(plan_play[0]["tool"], ("play_music", "spotify_play_track"))
        self.assertEqual(plan_play[0]["args"]["query"], "starboy")


class TestMediaControlTool(unittest.IsolatedAsyncioTestCase):
    async def test_media_control_desktop_spotify(self):
        tool = MediaControlTool()
        mock_players = [{
            "id": "spotify",
            "name": "Spotify",
            "hwnd": 12345,
            "title": "Starboy - The Weeknd",
            "is_playing": True,
            "proc_name": "spotify.exe",
        }]

        with patch("backend.agent.tools.system.media_tool._detect_desktop_media_players", return_value=mock_players), \
             patch("backend.agent.tools.system.media_tool._send_vk"):
            res = await tool.execute(action="pause", target="spotify")
            self.assertTrue(res.success)
            self.assertIn("Spotify", res.output)

    async def test_media_control_vlc(self):
        tool = MediaControlTool()
        mock_players = [{
            "id": "vlc",
            "name": "VLC Media Player",
            "hwnd": 99999,
            "title": "Interstellar.mp4 - VLC media player",
            "is_playing": True,
            "proc_name": "vlc.exe",
        }]

        with patch("backend.agent.tools.system.media_tool._detect_desktop_media_players", return_value=mock_players), \
             patch("backend.agent.tools.system.media_tool._send_vk"):
            res = await tool.execute(action="pause", target="vlc")
            self.assertTrue(res.success)
            self.assertIn("VLC Media Player", res.output)

    async def test_media_control_web_player(self):
        tool = MediaControlTool()
        mock_bridge = MagicMock()
        mock_bridge.is_connected.return_value = True
        mock_bridge.send_command = AsyncMock(return_value={"tab_title": "YouTube - Lo-Fi Beats", "success": True})

        with patch("backend.agent.tools.system.media_tool.extension_bridge", mock_bridge), \
             patch("backend.agent.tools.system.media_tool._detect_desktop_media_players", return_value=[]), \
             patch("backend.agent.tools.system.media_tool._send_vk"):
            res = await tool.execute(action="pause", target="web")
            self.assertTrue(res.success)
            self.assertIn("Web Player", res.output)

    async def test_media_control_auto_arbitration(self):
        tool = MediaControlTool()
        mock_players = [{
            "id": "spotify",
            "name": "Spotify",
            "hwnd": 12345,
            "title": "Spotify Free",
            "is_playing": False,
            "proc_name": "spotify.exe",
        }]

        with patch("backend.agent.tools.system.media_tool._detect_desktop_media_players", return_value=mock_players), \
             patch("backend.agent.tools.system.media_tool._send_vk"):
            res = await tool.execute(action="play_pause", target="auto")
            self.assertTrue(res.success)


class TestPlayMusicTool(unittest.IsolatedAsyncioTestCase):
    async def test_play_music_spotify_desktop(self):
        tool = PlayMusicTool()
        with patch("backend.agent.tools.system.media_tool._find_spotify_path", return_value=r"C:\Spotify\Spotify.exe"), \
             patch("os.startfile"), \
             patch("backend.agent.tools.system.media_tool._activate_spotify_window", return_value=True), \
             patch("backend.agent.tools.system.media_tool._send_vk"), \
             patch("backend.agent.tools.system.media_tool._send_spotify_appcommand"), \
             patch("backend.agent.tools.system.media_tool._ensure_spotify_playback_with_replanning", AsyncMock(return_value=(True, "Opened Spotify desktop and verified playback.", {"status": "Playing", "title": "Bohemian Rhapsody"}))):
            res = await tool.execute(query="Bohemian Rhapsody", service="spotify", prefer_desktop=True, resolve_query=False)
            self.assertTrue(res.success)
            self.assertIn("Spotify desktop", res.output)

    async def test_play_music_prefers_connected_spotify_api(self):
        tool = PlayMusicTool()
        mock_search_resp = MagicMock(status_code=200)
        mock_search_resp.json.return_value = {
            "tracks": {
                "items": [{
                    "uri": "spotify:track:abc123",
                    "name": "Bohemian Rhapsody",
                    "artists": [{"name": "Queen"}],
                }]
            }
        }
        mock_play_resp = MagicMock(status_code=204)

        with patch("backend.agent.tools.system.media_tool.credentials_store.get_credential", return_value={"token": "abc123"}), \
             patch("backend.agent.tools.system.media_tool.httpx.AsyncClient") as mock_async_client, \
             patch("backend.agent.tools.system.media_tool.extension_bridge.is_connected", return_value=False):
            client = mock_async_client.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=mock_search_resp)
            client.put = AsyncMock(return_value=mock_play_resp)

            res = await tool.execute(query="Bohemian Rhapsody", service="spotify", prefer_desktop=True, resolve_query=False)

            self.assertTrue(res.success)
            self.assertIn("Spotify API", res.output)
            self.assertIn("Bohemian Rhapsody", res.output)

    async def test_play_music_rejects_invalid_spotify_token(self):
        tool = PlayMusicTool()
        mock_search_resp = MagicMock(status_code=401)
        mock_search_resp.text = '{"error":{"status":401,"message":"Invalid access token"}}'

        with patch("backend.agent.tools.system.media_tool.credentials_store.get_credential", return_value={"token": "expired-token"}), \
             patch("backend.agent.tools.system.media_tool.httpx.AsyncClient") as mock_async_client, \
             patch("backend.agent.tools.system.media_tool._find_spotify_path", return_value=None), \
             patch("backend.agent.tools.system.media_tool.extension_bridge.is_connected", return_value=False), \
             patch("webbrowser.open"):
            client = mock_async_client.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=mock_search_resp)

            res = await tool.execute(query="Bohemian Rhapsody", service="spotify", prefer_desktop=True, resolve_query=False)

            self.assertFalse(res.success)
            self.assertIn("expired", res.error.lower())
            self.assertIn("spotify", res.error.lower())

    async def test_play_music_smart_discovery_resolution(self):
        tool = PlayMusicTool()
        mock_search_result = ToolResult(
            success=True,
            output="Found hits",
            metadata={
                "results": [
                    {
                        "title": "Top Hindi Songs of 2025 - Trending Bollywood Hits",
                        "snippet": "The biggest tracks of 2025 include 'Tauba Tauba' and 'Chuttamalle' by top artists.",
                    }
                ]
            }
        )

        with patch.object(WebSearchTool, "execute", AsyncMock(return_value=mock_search_result)), \
             patch("backend.agent.tools.system.media_tool._find_spotify_path", return_value=r"C:\Spotify\Spotify.exe"), \
             patch("os.startfile"), \
             patch("backend.agent.tools.system.media_tool._activate_spotify_window", return_value=True), \
             patch("backend.agent.tools.system.media_tool._send_vk"), \
             patch("backend.agent.tools.system.media_tool._send_spotify_appcommand"), \
             patch("backend.agent.tools.system.media_tool._ensure_spotify_playback_with_replanning", AsyncMock(return_value=(True, "[Discovery: Tauba Tauba] Opened Spotify desktop and verified playback.", {"status": "Playing", "title": "Tauba Tauba"}))):
            res = await tool.execute(query="top hindi music of 2025", service="spotify", prefer_desktop=True, resolve_query=True)
            self.assertTrue(res.success)
            self.assertIn("Tauba Tauba", res.output)

    async def test_play_music_spotify_web_extension(self):
        tool = PlayMusicTool()
        mock_bridge = MagicMock()
        mock_bridge.is_connected.return_value = True
        mock_bridge.send_command = AsyncMock(return_value={"url": "https://open.spotify.com/search/starboy", "success": True})

        with patch("backend.agent.tools.system.media_tool.extension_bridge", mock_bridge):
            res = await tool.execute(query="starboy", service="spotify_web", prefer_desktop=False, resolve_query=False)
            self.assertTrue(res.success)
            self.assertIn("Spotify Web Player", res.output)

    async def test_strict_song_verification_rejects_wrong_song(self):
        from backend.agent.tools.system.media_tool import _ensure_spotify_playback_with_replanning
        
        # When old song "Kichui Jabe Na Sathe" is playing, but user requested "Gehra Hua"
        wrong_smtc = {
            "success": True,
            "status": "Playing",
            "title": "Kichui Jabe Na Sathe",
            "artist": "Barnali Kar",
            "album": "Single"
        }

        with patch("backend.agent.tools.system.media_tool._get_smtc_media_info", return_value=wrong_smtc), \
             patch("backend.agent.tools.system.media_tool._activate_spotify_window", return_value=True), \
             patch("backend.agent.tools.gui.screen.vlm_ground_target", AsyncMock(return_value={"found": False})), \
             patch("backend.api.nexus.push_event", AsyncMock()), \
             patch("backend.api.nexus.pause_task", AsyncMock()):
            
            success, msg, media_info = await _ensure_spotify_playback_with_replanning(
                effective_query="Gehra Hua",
                max_replan_attempts=1
            )
            # Must strictly reject the wrong song!
            self.assertFalse(success)
            self.assertIn("not playing on Spotify", msg)
            self.assertIn("Kichui Jabe Na Sathe", msg)

    async def test_strict_song_verification_accepts_matching_song(self):
        from backend.agent.tools.system.media_tool import _ensure_spotify_playback_with_replanning

        matching_smtc = {
            "success": True,
            "status": "Playing",
            "title": "Gehra Hua (From \"Dhurandhar\")",
            "artist": "Shashwat Sachdev, Arijit Singh",
            "album": "Dhurandhar"
        }

        with patch("backend.agent.tools.system.media_tool._get_smtc_media_info", return_value=matching_smtc), \
             patch("backend.api.nexus.push_event", AsyncMock()):
            
            success, msg, media_info = await _ensure_spotify_playback_with_replanning(
                effective_query="Gehra Hua",
                max_replan_attempts=1
            )
            # Must accept matching song
            self.assertTrue(success)
            self.assertIn("Now playing", msg)
            self.assertIn("Gehra Hua", msg)


if __name__ == "__main__":
    unittest.main()

