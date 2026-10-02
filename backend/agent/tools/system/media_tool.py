"""Media and music playback automation tools for NEXUS.
Supports:
1. Desktop Media Players: Spotify, VLC, Windows Media Player, iTunes, Apple Music, Foobar2000, AIMP, TIDAL, Amazon Music, PotPlayer, MPC, and Windows SMTC.
2. Web Players: Spotify Web, YouTube, YouTube Music, SoundCloud, Apple Music, and HTML5 audio/video.
3. Smart Music Search Resolution: Automatically resolves discovery queries (e.g. "top hindi music of 2025", "latest single by...") via live web search.
"""
from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
import re
import json
import urllib.parse
import subprocess
from typing import Optional, Dict, Any, List, Tuple

import httpx

from backend.agent.tools.base import NexusTool, ToolResult
from backend.connectors.credentials_store import credentials_store
from backend.core.policies import RiskLevel
from backend.agent.tools.web_automation.extension_bridge import extension_bridge
from backend.agent.tools.web.search import WebSearchTool

try:
    import pyautogui
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

logger = logging.getLogger("nexus.media_tool")

# Windows Virtual Keycodes for Media
VK_MEDIA_NEXT_TRACK = 0xB0  # 176
VK_MEDIA_PREV_TRACK = 0xB1  # 177
VK_MEDIA_STOP = 0xB2        # 178
VK_MEDIA_PLAY_PAUSE = 0xB3  # 179
VK_VOLUME_MUTE = 0xAD       # 173
VK_VOLUME_DOWN = 0xAE       # 174
VK_VOLUME_UP = 0xAF         # 175
VK_RETURN = 0x0D            # 13
VK_SPACE = 0x20             # 32
VK_TAB = 0x09               # 9
VK_DOWN = 0x28              # 40
VK_F6 = 0x75                # 117

KEYEVENTF_KEYUP = 0x0002

# Windows WM_APPCOMMAND Constants
WM_APPCOMMAND = 0x0319
APPCOMMAND_VOLUME_MUTE = 8
APPCOMMAND_VOLUME_DOWN = 9
APPCOMMAND_VOLUME_UP = 10
APPCOMMAND_MEDIA_NEXTTRACK = 11
APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
APPCOMMAND_MEDIA_STOP = 13
APPCOMMAND_MEDIA_PLAY_PAUSE = 14
APPCOMMAND_MEDIA_PLAY = 46
APPCOMMAND_MEDIA_PAUSE = 47

# Comprehensive Desktop Media Player Definitions
DESKTOP_MEDIA_PLAYERS = [
    {
        "id": "spotify",
        "name": "Spotify",
        "process_names": ["spotify.exe"],
        "class_names": ["Chrome_WidgetWin_0"],
    },
    {
        "id": "vlc",
        "name": "VLC Media Player",
        "process_names": ["vlc.exe"],
        "class_names": ["Qt5QWindowIcon", "Qt6QWindowIcon", "VLC media player"],
    },
    {
        "id": "wmplayer",
        "name": "Windows Media Player",
        "process_names": ["wmplayer.exe", "music.ui.exe", "video.ui.exe", "microsoft.media.player.exe"],
        "class_names": ["WMPlayerApp", "ApplicationFrameWindow"],
    },
    {
        "id": "itunes",
        "name": "iTunes",
        "process_names": ["itunes.exe"],
        "class_names": ["iTunes"],
    },
    {
        "id": "apple_music",
        "name": "Apple Music",
        "process_names": ["applemusic.exe"],
        "class_names": ["ApplicationFrameWindow"],
    },
    {
        "id": "foobar2000",
        "name": "foobar2000",
        "process_names": ["foobar2000.exe"],
        "class_names": ["{97E27FAA-C0B3-4b8e-A693-ED7881E99FC1}", "foobar2000"],
    },
    {
        "id": "aimp",
        "name": "AIMP",
        "process_names": ["aimp.exe"],
        "class_names": ["TAIMPMainForm"],
    },
    {
        "id": "tidal",
        "name": "TIDAL",
        "process_names": ["tidal.exe"],
        "class_names": ["Chrome_WidgetWin_1"],
    },
    {
        "id": "amazon_music",
        "name": "Amazon Music",
        "process_names": ["amazon music.exe"],
        "class_names": ["Chrome_WidgetWin_1"],
    },
    {
        "id": "potplayer",
        "name": "PotPlayer",
        "process_names": ["potplayer64.exe", "potplayer.exe"],
        "class_names": ["PotPlayer64", "PotPlayer"],
    },
    {
        "id": "mpc",
        "name": "MPC Media Player",
        "process_names": ["mpc-hc64.exe", "mpc-hc.exe", "mpc-be64.exe", "mpc-be.exe"],
        "class_names": ["MediaPlayerClassicW"],
    },
]


def _send_vk(vk_code: int, repeat: int = 1, delay: float = 0.05) -> None:
    """Send hardware virtual key event via Windows user32 API."""
    if sys.platform != "win32":
        return
    import ctypes
    for _ in range(repeat):
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.01)
        ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        if repeat > 1 and delay > 0:
            time.sleep(delay)


def _find_spotify_path() -> Optional[str]:
    """Locate Spotify desktop executable on Windows."""
    if sys.platform != "win32":
        return None

    candidates = [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Spotify\Spotify.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # Check registry HKCR\spotify\shell\open\command
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"spotify\shell\open\command") as key:
            val, _ = winreg.QueryValueEx(key, "")
            if val:
                import shlex
                parts = shlex.split(val)
                if parts and os.path.isfile(parts[0]):
                    return parts[0]
    except Exception:
        pass

    return None


async def _get_configured_spotify_token() -> Optional[str]:
    """Return the configured Spotify access token, refreshing it when expired."""
    from backend.connectors.manager import connector_manager

    adapter = connector_manager.get_adapter("spotify")
    if adapter and hasattr(adapter, "get_valid_spotify_token"):
        return await adapter.get_valid_spotify_token("default")
    for user_id in ("default", "local_default_user"):
        creds = credentials_store.get_credential(user_id, "spotify") or {}
        token = creds.get("access_token") or creds.get("token") or creds.get("api_key")
        if isinstance(token, str) and token.strip():
            return token.strip()
    return None


async def _spotify_token_is_valid(token: str) -> bool | None:
    """Return False only when Spotify explicitly rejects the saved token."""
    if not token or not token.strip():
        return False
    headers = {"Authorization": f"Bearer {token.strip()}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.spotify.com/v1/me", headers=headers)
            if resp.status_code == 200:
                return True
            if resp.status_code == 401:
                logger.warning("Spotify token rejected by API: %s", resp.text[:200])
                return False
            return None
    except Exception as exc:
        logger.warning("Spotify token validation request failed: %s", exc)
        return None


async def _play_spotify_via_api(query: str, token: str) -> ToolResult:
    """Use the connected Spotify API as the preferred playback path when a token exists."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    clean_query = (query or "top hits").strip()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            search_res = await client.get(
                "https://api.spotify.com/v1/search?q=" + urllib.parse.quote(clean_query) + "&type=track&limit=1",
                headers=headers,
            )
            if search_res.status_code != 200:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Spotify API search failed ({search_res.status_code}): {search_res.text}",
                )

            items = search_res.json().get("tracks", {}).get("items", [])
            if not items:
                return ToolResult(success=False, output="", error=f"No Spotify track matches '{clean_query}'.")

            track = items[0]
            uri = track.get("uri")
            if not uri:
                return ToolResult(success=False, output="", error="Spotify API returned a track without a playable URI.")

            track_name = track.get("name", "track")
            artist_names = ", ".join(a.get("name", "") for a in track.get("artists", []) if a.get("name"))
            play_payload = {"uris": [uri]}
            play_res = await client.put("https://api.spotify.com/v1/me/player/play", headers=headers, json=play_payload)
            if play_res.status_code in (200, 204):
                artist_desc = f" by {artist_names}" if artist_names else ""
                return ToolResult(
                    success=True,
                    output=f"Spotify API: Now playing '{track_name}'{artist_desc}.",
                    metadata={"service": "spotify_api", "query": clean_query, "track": track},
                )
            if play_res.status_code == 404:
                return ToolResult(
                    success=False,
                    output="",
                    error="No active Spotify device found. Start the Spotify desktop or web player first.",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Spotify API play failed ({play_res.status_code}): {play_res.text}",
            )
    except Exception as exc:
        logger.warning(f"Spotify API direct playback failed: {exc}")
        return ToolResult(success=False, output="", error=f"Spotify API direct playback error: {exc}")


def _get_smtc_media_info() -> Dict[str, Any]:
    """
    Query active media session from Windows System Media Transport Controls (SMTC).
    Returns dict: { success: bool, title: str, artist: str, album: str, app_id: str, status: str }
    """
    if sys.platform != "win32":
        return {"success": False, "title": "", "artist": "", "album": "", "app_id": "", "status": "Unknown"}

    ps_code = """
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | select -First 1

    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }

    [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime] | Out-Null
    $asyncOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
    $manager = Await $asyncOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])

    $session = $manager.GetCurrentSession()
    if ($session) {
        $mediaPropOp = $session.TryGetMediaPropertiesAsync()
        $media = Await $mediaPropOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $status = $session.GetPlaybackInfo().PlaybackStatus.ToString()

        [PSCustomObject]@{
            Success = $true
            Title = $media.Title
            Artist = $media.Artist
            AlbumTitle = $media.AlbumTitle
            AppId = $session.SourceAppUserModelId
            Status = $status
        } | ConvertTo-Json
    } else {
        [PSCustomObject]@{ Success = $false; Message = "No active media session" } | ConvertTo-Json
    }
} catch {
    [PSCustomObject]@{ Success = $false; Error = $_.Exception.Message } | ConvertTo-Json
}
"""
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True, text=True, timeout=3.0)
        data = json.loads(res.stdout.strip())
        return {
            "success": data.get("Success", False),
            "title": data.get("Title", "") or "",
            "artist": data.get("Artist", "") or "",
            "album": data.get("AlbumTitle", "") or "",
            "app_id": data.get("AppId", "") or "",
            "status": data.get("Status", "Unknown"),
        }
    except Exception as e:
        logger.debug(f"SMTC media state check error: {e}")
        return {"success": False, "title": "", "artist": "", "album": "", "app_id": "", "status": "Unknown", "error": str(e)}


def _detect_desktop_media_players() -> List[Dict[str, Any]]:
    """
    Detect all active desktop media players on Windows.
    Returns list of dicts: [{ id, name, hwnd, title, is_playing, proc_name }]
    """
    if sys.platform != "win32":
        return []

    results = []
    try:
        import win32gui
        import win32process
        import psutil

        found_windows = []

        def enum_cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    cls = win32gui.GetClassName(hwnd)
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    pname = (proc.name() or "").lower()
                    found_windows.append((hwnd, title, cls, pname, pid))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_cb, None)

        for player in DESKTOP_MEDIA_PLAYERS:
            p_ids = [p.lower() for p in player["process_names"]]
            c_names = [c.lower() for c in player["class_names"]]

            for hwnd, title, cls, pname, pid in found_windows:
                if pname in p_ids or cls.lower() in c_names:
                    # Determine playing status and track info from window title
                    title_clean = title.strip()
                    is_playing = False
                    is_idle_spotify = title_clean.lower() in ("spotify", "spotify free", "spotify premium")
                    
                    if player["id"] == "spotify":
                        is_playing = " - " in title_clean and not is_idle_spotify
                    elif player["id"] == "vlc":
                        is_playing = "vlc media player" in title_clean.lower() and len(title_clean) > len("vlc media player")
                    elif title_clean and not any(title_clean.lower() == k for k in (player["name"].lower(), "media player")):
                        is_playing = True

                    results.append({
                        "id": player["id"],
                        "name": player["name"],
                        "hwnd": hwnd,
                        "title": title_clean or player["name"],
                        "is_playing": is_playing,
                        "proc_name": pname,
                    })
                    break  # Found primary window for this player
    except Exception as e:
        logger.debug(f"Error detecting desktop media players: {e}")

    return results


def _get_spotify_window_info() -> Dict[str, Any]:
    """Compatibility helper for Spotify desktop detection."""
    players = _detect_desktop_media_players()
    spotify = next((p for p in players if p["id"] == "spotify"), None)
    if spotify:
        return {
            "running": True,
            "hwnd": spotify["hwnd"],
            "title": spotify["title"],
            "is_playing": spotify["is_playing"],
            "track_info": spotify["title"] if spotify["is_playing"] else "",
        }
    return {"running": False, "hwnd": None, "title": "", "is_playing": False, "track_info": ""}


def _activate_spotify_window() -> bool:
    """Attempt to bring Spotify window to foreground."""
    if sys.platform != "win32":
        return False
    try:
        info = _get_spotify_window_info()
        hwnd = info.get("hwnd")
        if hwnd:
            import win32gui
            import win32con
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _send_spotify_appcommand(cmd_code: int) -> bool:
    """Send Win32 WM_APPCOMMAND to Spotify or active media player."""
    if sys.platform != "win32":
        return False
    try:
        info = _get_spotify_window_info()
        hwnd = info.get("hwnd")
        if hwnd:
            import win32api
            win32api.SendMessage(hwnd, WM_APPCOMMAND, 0, cmd_code << 16)
            return True
    except Exception as e:
        logger.debug(f"Failed sending WM_APPCOMMAND: {e}")
    return False


async def _click_spotify_top_result_async(task_id: str | None = None) -> bool:
    """Visually ground the circular green play button using VLM + screenshot and click it."""
    if sys.platform != "win32" or not HAS_PYAUTOGUI:
        return False
    try:
        sw, sh = pyautogui.size()
        info = _get_spotify_window_info()
        hwnd = info.get("hwnd")
        left, top, w, h = 0, 0, sw, sh
        if hwnd:
            try:
                import win32gui
                rect = win32gui.GetWindowRect(hwnd)
                left, top = rect[0], rect[1]
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
            except Exception:
                pass

        card_hover_x = left + (260 if w >= 1600 else int(w * 0.15))
        card_hover_y = top + (380 if h >= 900 else int(h * 0.35))

        # 1. Hover briefly to ensure Spotify reveals any hover-only controls
        def _hover():
            pyautogui.moveTo(card_hover_x, card_hover_y, duration=0.2)
            time.sleep(0.08)
        await asyncio.to_thread(_hover)

        # 2. Visually ground circular green play button using VLM perception
        from backend.agent.tools.gui.screen import vlm_ground_target
        grounding = await vlm_ground_target("circular green play button on Spotify top result card or top song row")

        if grounding.get("found"):
            gx = grounding["x"]
            gy = grounding["y"]
            def _click_grounded():
                pyautogui.moveTo(gx, gy, duration=0.25)
                time.sleep(0.06)
                pyautogui.click(gx, gy)
                time.sleep(0.08)
                pyautogui.click(gx, gy)
            await asyncio.to_thread(_click_grounded)
            await asyncio.sleep(0.6)
        else:
            # Calibrated fallback click
            btn_x = left + 328 if w >= 1600 else left + int(w * 0.171)
            btn_y = top + 450 if h >= 900 else top + int(h * 0.417)
            def _click_fallback():
                pyautogui.moveTo(btn_x, btn_y, duration=0.2)
                pyautogui.click(btn_x, btn_y)
            await asyncio.to_thread(_click_fallback)
            await asyncio.sleep(0.6)

        # 3. Check SMTC playback
        smtc = _get_smtc_media_info()
        if smtc.get("status") != "Playing":
            first_row_x = left + (480 if w >= 1600 else int(w * 0.25))
            first_row_y = top + (265 if h >= 900 else int(h * 0.25))
            def _click_song_row():
                pyautogui.moveTo(first_row_x, first_row_y, duration=0.18)
                pyautogui.doubleClick(first_row_x, first_row_y)
                time.sleep(0.1)
                pyautogui.press('enter')
            await asyncio.to_thread(_click_song_row)
            await asyncio.sleep(0.6)
            smtc = _get_smtc_media_info()

        return smtc.get("status") == "Playing"
    except Exception as e:
        logger.debug(f"Failed clicking Spotify top result: {e}")
        return False


def _click_spotify_top_result() -> bool:
    """Synchronous wrapper for clicking Spotify top result."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _click_spotify_top_result_async()).result(timeout=10.0)
        else:
            return loop.run_until_complete(_click_spotify_top_result_async())
    except Exception:
        # Fallback to calibrated coords
        if sys.platform != "win32" or not HAS_PYAUTOGUI:
            return False
        try:
            sw, sh = pyautogui.size()
            info = _get_spotify_window_info()
            hwnd = info.get("hwnd")
            left, top, w, h = 0, 0, sw, sh
            if hwnd:
                try:
                    import win32gui
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top = rect[0], rect[1]
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                except Exception:
                    pass
            btn_x = left + 328 if w >= 1600 else left + int(w * 0.171)
            btn_y = top + 450 if h >= 900 else top + int(h * 0.417)
            pyautogui.moveTo(btn_x, btn_y, duration=0.2)
            pyautogui.click(btn_x, btn_y)
            return True
        except Exception:
            return False


async def _ensure_spotify_playback_with_replanning(
    effective_query: str,
    note_prefix: str = "",
    max_replan_attempts: int = 4
) -> tuple[bool, str, dict]:
    """
    Checks whether the requested song is playing via Windows SMTC.
    If not playing, adaptively replans: takes fresh snapshots, uses VLM perception,
    and executes corrective actions until playback is verified or attempts are exhausted.
    Every single micro-step (taking snapshot, locating buttons with VLM, clicking,
    verifying via SMTC, rethinking plan) is emitted in real time to the automation pill.
    """
    from backend.agent.tools.gui.screen import vlm_ground_target
    from backend.api.nexus import push_event, pause_task
    import datetime

    # Clean query and extract keywords (excluding stop words)
    q_words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", effective_query) if len(w) > 2]
    stop_words = {"song", "track", "music", "play", "from", "the", "and", "audio", "listen", "hits", "single"}
    q_tokens = [w for w in q_words if w not in stop_words]
    if not q_tokens:
        q_tokens = q_words

    def _is_target_song_playing() -> tuple[bool, dict]:
        info = _get_smtc_media_info()
        st = info.get("status")
        ttl = (info.get("title") or "").lower()
        art = (info.get("artist") or "").lower()
        alb = (info.get("album") or "").lower()
        playing = (st == "Playing")
        # Match either title, artist, or album
        matches = any(tok in ttl or tok in art or tok in alb for tok in q_tokens) if q_tokens else True
        return (playing and matches), info

    # Step 0: Check current playback status
    try:
        await push_event(None, "status", {"status": "executing", "message": f"Checking Spotify playback for '{effective_query}'..."})
    except Exception:
        pass

    is_ok, smtc = await asyncio.to_thread(_is_target_song_playing)
    if is_ok:
        msg = f"{note_prefix}Now playing '{smtc.get('title')}' by {smtc.get('artist')} on Spotify Desktop (Verified)."
        try:
            await push_event(None, "status", {"status": "completed", "message": f"Playing '{smtc.get('title')}' by {smtc.get('artist')}"})
        except Exception:
            pass
        return True, msg, smtc

    # If an old/stale track is currently playing, announce the mismatch
    cur_title = smtc.get("title", "")
    if cur_title:
        try:
            await push_event(None, "status", {
                "status": "executing",
                "message": f"Currently playing '{cur_title}' (mismatch). Replanning for '{effective_query}'..."
            })
            await asyncio.sleep(0.5)
        except Exception:
            pass

    last_detected_coords = None

    # Replan Loop: Check -> Snapshot -> VLM -> Action -> Verify
    for attempt in range(1, max_replan_attempts + 1):
        logger.info(f"[Spotify Replan {attempt}/{max_replan_attempts}] Song '{effective_query}' not playing yet. Taking snapshot and replanning...")

        # Bring window to foreground
        try:
            await push_event(None, "status", {"status": "executing", "message": f"[Step {attempt}] Activating Spotify & taking screen snapshot..."})
        except Exception:
            pass

        await asyncio.to_thread(_activate_spotify_window)
        await asyncio.sleep(0.3)

        info = _get_spotify_window_info()
        hwnd = info.get("hwnd")
        sw, sh = pyautogui.size() if HAS_PYAUTOGUI else (1920, 1080)
        left, top, w, h = 0, 0, sw, sh
        if hwnd:
            try:
                import win32gui
                rect = win32gui.GetWindowRect(hwnd)
                left, top = rect[0], rect[1]
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
            except Exception:
                pass

        if attempt == 1:
            # Action 1: Hover over card area, ground circular green play button with VLM, and click
            try:
                await push_event(None, "status", {"status": "executing", "message": "Locating green play button with VLM perception..."})
            except Exception:
                pass

            card_hover_x = left + (260 if w >= 1600 else int(w * 0.15))
            card_hover_y = top + (380 if h >= 900 else int(h * 0.35))
            def _hover_card():
                if HAS_PYAUTOGUI:
                    pyautogui.moveTo(card_hover_x, card_hover_y, duration=0.18)
                    time.sleep(0.08)
            await asyncio.to_thread(_hover_card)

            grounding = await vlm_ground_target("circular green play button on Spotify")
            if grounding.get("found") and HAS_PYAUTOGUI:
                gx, gy = grounding["x"], grounding["y"]
                last_detected_coords = (gx, gy)
                try:
                    await push_event(None, "status", {"status": "executing", "message": f"Clicking green play button at ({gx}, {gy})..."})
                except Exception:
                    pass
                def _click_btn():
                    pyautogui.moveTo(gx, gy, duration=0.2)
                    time.sleep(0.06)
                    pyautogui.click(gx, gy)
                    time.sleep(0.08)
                    pyautogui.click(gx, gy)
                await asyncio.to_thread(_click_btn)
            else:
                btn_x = left + 328 if w >= 1600 else left + int(w * 0.171)
                btn_y = top + 450 if h >= 900 else top + int(h * 0.417)
                try:
                    await push_event(None, "status", {"status": "executing", "message": f"Clicking play button at calibrated coordinates ({btn_x}, {btn_y})..."})
                except Exception:
                    pass
                def _click_calibrated():
                    if HAS_PYAUTOGUI:
                        pyautogui.moveTo(btn_x, btn_y, duration=0.2)
                        pyautogui.click(btn_x, btn_y)
                await asyncio.to_thread(_click_calibrated)

        elif attempt == 2:
            # Action 2: Play button failed — target top track row (Album Track List or Search List)
            try:
                await push_event(None, "status", {"status": "executing", "message": f"Play button did not start track. Replanning: targeting song row..."})
                await asyncio.sleep(0.4)
                await push_event(None, "status", {"status": "executing", "message": f"Locating track row for '{effective_query}' with VLM perception..."})
            except Exception:
                pass

            grounding = await vlm_ground_target(f"first track row or title for '{effective_query}' in Spotify")
            is_album_view = last_detected_coords and (last_detected_coords[0] < left + int(w * 0.22) or last_detected_coords[1] > top + int(h * 0.42))
            
            if grounding.get("found") and HAS_PYAUTOGUI:
                gx, gy = grounding["x"], grounding["y"]
            elif is_album_view:
                # In album / single view (like Gehra Hua), track 1 row is under the # Title header
                gx = left + (480 if w >= 1600 else int(w * 0.28))
                gy = top + (630 if h >= 900 else int(h * 0.58))
            else:
                # In search results view, track 1 is under 'Songs' header
                gx = left + (480 if w >= 1600 else int(w * 0.25))
                gy = top + (265 if h >= 900 else int(h * 0.25))

            try:
                await push_event(None, "status", {"status": "executing", "message": f"Double-clicking track row at ({gx}, {gy})..."})
            except Exception:
                pass

            def _click_song_row():
                if HAS_PYAUTOGUI:
                    pyautogui.moveTo(gx, gy, duration=0.2)
                    time.sleep(0.06)
                    pyautogui.doubleClick(gx, gy)
                    time.sleep(0.08)
                    pyautogui.press('enter')
            await asyncio.to_thread(_click_song_row)

        elif attempt == 3:
            # Action 3: Focus Spotify main canvas, send Space and hardware play command
            try:
                await push_event(None, "status", {"status": "executing", "message": "Rethinking plan: focusing Spotify canvas and dispatching play commands..."})
            except Exception:
                pass

            def _press_keys():
                if HAS_PYAUTOGUI:
                    focus_x = left + int(w * 0.3)
                    focus_y = top + int(h * 0.3)
                    pyautogui.click(focus_x, focus_y)
                    time.sleep(0.05)
                    pyautogui.press('space')
                    time.sleep(0.08)
                    pyautogui.press('enter')
                _send_spotify_appcommand(APPCOMMAND_MEDIA_PLAY_PAUSE)
                _send_vk(VK_MEDIA_PLAY_PAUSE)
            await asyncio.to_thread(_press_keys)

        # Allow audio stream to initialize and SMTC to update
        try:
            await push_event(None, "status", {"status": "executing", "message": f"Verifying track playback via Windows SMTC..."})
        except Exception:
            pass

        await asyncio.sleep(1.2)

        # Check SMTC after action
        is_ok, smtc = await asyncio.to_thread(_is_target_song_playing)
        if is_ok:
            logger.info(f"Playback successfully verified on replan attempt {attempt}: '{smtc.get('title')}' by {smtc.get('artist')}")
            try:
                await push_event(None, "status", {"status": "completed", "message": f"Playing '{smtc.get('title')}' by {smtc.get('artist')}"})
            except Exception:
                pass
            return True, f"{note_prefix}Now playing '{smtc.get('title')}' by {smtc.get('artist')} on Spotify Desktop (Verified).", smtc

    # Strict final check: never declare success if the requested song did NOT start playing
    is_ok, final_info = await asyncio.to_thread(_is_target_song_playing)
    if is_ok:
        try:
            await push_event(None, "status", {"status": "completed", "message": f"Playing '{final_info.get('title')}' by {final_info.get('artist')}"})
        except Exception:
            pass
        return True, f"{note_prefix}Now playing '{final_info.get('title')}' by {final_info.get('artist')} on Spotify Desktop (Verified).", final_info

    # Requested song did NOT play — pause automation and register issue
    cur_title = final_info.get("title", "")
    cur_desc = f"'{cur_title}' by {final_info.get('artist', '')}" if cur_title else "none"
    err_msg = f"Requested song '{effective_query}' is not playing on Spotify (currently playing: {cur_desc}). Automation paused."
    try:
        await push_event(None, "status", {"status": "paused", "message": err_msg})
        await push_event(None, "issue", {
            "type": "playback_not_verified",
            "message": err_msg,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
        })
        await pause_task()
    except Exception as e:
        logger.debug(f"Failed to pause task: {e}")

    return False, err_msg, final_info




async def _resolve_music_query(query: str) -> Tuple[str, str]:
    """
    Intelligently resolves discovery / descriptive queries
    (e.g., 'top hindi music of 2025', 'latest single by...', 'trending pop hits 2024')
    to concrete track names or curated playlist keywords via live web search.
    """
    if not query:
        return "", ""

    q_clean = query.strip()
    q_lower = q_clean.lower()

    # Identify if query is a discovery / trend / relative search
    discovery_indicators = [
        r"\btop\s+", r"\blatest\b", r"\bnew\b", r"\bnewest\b", r"\bpopular\b",
        r"\btrending\b", r"\bviral\b", r"\bhit\b", r"\bhits\b", r"\bchart\b",
        r"\bbest\s+", r"\bgrammy\b", r"\boscar\b", r"\bbillboard\b",
        r"\b202[0-9]\b", r"\b90s\b", r"\b80s\b", r"\b2000s\b",
        r"\bthe\s+song\s+(?:from|in|by|that)\b",
    ]

    is_discovery = any(re.search(pat, q_lower) for pat in discovery_indicators)
    if not is_discovery:
        return q_clean, ""

    try:
        tool = WebSearchTool()
        search_res = await tool.execute(query=f"{q_clean} song track title artist name", max_results=3)
        results = search_res.metadata.get("results", [])

        candidates = []
        for r in results:
            snippet = r.get("snippet", "")
            title = r.get("title", "")
            combined = f"{title}. {snippet}"

            # 1. Look for quoted song titles
            quotes = re.findall(r'["“\']([^"”\']{2,40})["”\']', combined)
            for q in quotes:
                q_strip = q.strip()
                if not any(w in q_strip.lower() for w in ["playlist", "music", "song", "spotify", "youtube", "gaana", "album", "chart", "mp3", "http"]):
                    candidates.append(q_strip)

            # 2. Look for numbered list patterns (e.g., 1. Song - Artist)
            list_matches = re.findall(r'(?:\d+[\.\)]\s*)([A-Za-z0-9\s\'\-_]+?)(?:\s*[-–—]\s*|\s+by\s+)([A-Za-z0-9\s]+)', combined)
            for s_name, a_name in list_matches:
                s_clean = s_name.strip()
                if 2 < len(s_clean) < 40 and not any(w in s_clean.lower() for w in ["track", "song", "listen"]):
                    candidates.append(f"{s_clean} - {a_name.strip()}")

        if candidates:
            best = candidates[0]
            return f"{best}", f"Resolved '{q_clean}' to top hit: '{best}'"
        else:
            return f"{q_clean} Hits", f"Curated discovery query: '{q_clean} Hits'"
    except Exception as e:
        logger.debug(f"Music discovery resolution failed: {e}")
        return q_clean, ""


class MediaControlTool(NexusTool):
    name = "media_control"
    description = (
        "Control media playback seamlessly across all Desktop apps (Spotify, VLC, Windows Media Player, iTunes, Apple Music, Foobar2000, AIMP, Tidal, PotPlayer, MPC) "
        "and Web Players (YouTube, Spotify Web, SoundCloud, Apple Music) on Windows. "
        "Supports action: 'play', 'pause', 'play_pause', 'toggle', 'resume', 'next', 'previous', 'stop', 'volume_up', 'volume_down', 'mute', 'unmute'. "
        "Target can be 'auto', 'spotify', 'vlc', 'wmplayer', 'itunes', 'web', 'youtube', or 'system'."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        action: str,
        target: str = "auto",
        repeat: int = 1,
        **_
    ) -> ToolResult:
        act = (action or "").lower().strip().replace(" ", "_").replace("-", "_")
        tgt = (target or "auto").lower().strip()

        # Action code mapping for hardware keys
        vk_map = {
            "play": (VK_MEDIA_PLAY_PAUSE, 1, "Resumed media playback"),
            "pause": (VK_MEDIA_PLAY_PAUSE, 1, "Paused media playback"),
            "play_pause": (VK_MEDIA_PLAY_PAUSE, 1, "Toggled media playback"),
            "toggle": (VK_MEDIA_PLAY_PAUSE, 1, "Toggled media playback"),
            "resume": (VK_MEDIA_PLAY_PAUSE, 1, "Resumed media playback"),
            "next": (VK_MEDIA_NEXT_TRACK, 1, "Skipped to next track"),
            "next_track": (VK_MEDIA_NEXT_TRACK, 1, "Skipped to next track"),
            "skip": (VK_MEDIA_NEXT_TRACK, 1, "Skipped to next track"),
            "previous": (VK_MEDIA_PREV_TRACK, 1, "Went back to previous track"),
            "prev_track": (VK_MEDIA_PREV_TRACK, 1, "Went back to previous track"),
            "prev": (VK_MEDIA_PREV_TRACK, 1, "Went back to previous track"),
            "stop": (VK_MEDIA_STOP, 1, "Stopped media playback"),
            "volume_up": (VK_VOLUME_UP, max(repeat, 5), f"Increased volume (+{max(repeat, 5) * 2}%)"),
            "volume_down": (VK_VOLUME_DOWN, max(repeat, 5), f"Decreased volume (-{max(repeat, 5) * 2}%)"),
            "mute": (VK_VOLUME_MUTE, 1, "Toggled volume mute"),
            "unmute": (VK_VOLUME_MUTE, 1, "Toggled volume mute"),
        }

        # AppCommand mapping for Win32 desktop apps
        appcmd_map = {
            "play": APPCOMMAND_MEDIA_PLAY,
            "pause": APPCOMMAND_MEDIA_PAUSE,
            "play_pause": APPCOMMAND_MEDIA_PLAY_PAUSE,
            "toggle": APPCOMMAND_MEDIA_PLAY_PAUSE,
            "resume": APPCOMMAND_MEDIA_PLAY,
            "next": APPCOMMAND_MEDIA_NEXTTRACK,
            "next_track": APPCOMMAND_MEDIA_NEXTTRACK,
            "skip": APPCOMMAND_MEDIA_NEXTTRACK,
            "previous": APPCOMMAND_MEDIA_PREVIOUSTRACK,
            "prev_track": APPCOMMAND_MEDIA_PREVIOUSTRACK,
            "prev": APPCOMMAND_MEDIA_PREVIOUSTRACK,
            "stop": APPCOMMAND_MEDIA_STOP,
            "volume_up": APPCOMMAND_VOLUME_UP,
            "volume_down": APPCOMMAND_VOLUME_DOWN,
            "mute": APPCOMMAND_VOLUME_MUTE,
            "unmute": APPCOMMAND_VOLUME_MUTE,
        }

        if act not in vk_map:
            return ToolResult(
                success=False,
                error=f"Unknown media action: '{action}'. Valid actions: {list(vk_map.keys())}",
                output="",
            )

        vk, count, msg = vk_map[act]
        appcmd = appcmd_map.get(act, APPCOMMAND_MEDIA_PLAY_PAUSE)

        # 1. Scan for running Desktop Media Players & Web Media State
        desktop_players = await asyncio.to_thread(_detect_desktop_media_players)
        web_media_state = None
        has_web_playing = False

        if extension_bridge.is_connected():
            try:
                web_media_state = await extension_bridge.send_command("get_media_state", {}, timeout=2.0)
                if web_media_state and isinstance(web_media_state, dict):
                    has_web_playing = web_media_state.get("has_active_media", False)
            except Exception:
                pass

        results_log = []

        # 2. Decision Logic based on target & detected state
        # Case A: Specific desktop media player targeted (e.g. spotify, vlc, wmplayer, itunes)
        target_player = next((p for p in desktop_players if p["id"] == tgt or tgt in p["name"].lower()), None)
        if target_player:
            hwnd = target_player["hwnd"]
            if sys.platform == "win32" and hwnd:
                try:
                    import win32api
                    win32api.SendMessage(hwnd, WM_APPCOMMAND, 0, appcmd << 16)
                except Exception:
                    pass
            _send_vk(vk, repeat=count)
            p_name = target_player["name"]
            p_title = target_player["title"]
            return ToolResult(
                success=True,
                output=f"Controlled {p_name} ({p_title}): {msg}",
                metadata={"target": target_player["id"], "action": act, "title": p_title},
            )

        # Case B: Specific Web / Browser / YouTube target requested
        elif tgt in ("web", "youtube", "browser", "spotify_web", "youtube_music"):
            if extension_bridge.is_connected():
                try:
                    res = await extension_bridge.send_command(
                        "media_control",
                        {"action": act, "service": tgt if tgt != "web" else ""},
                        timeout=4.0
                    )
                    tab_title = res.get("tab_title", "Browser Tab")
                    return ToolResult(
                        success=True,
                        output=f"Controlled Web Player ({tab_title}): {msg}",
                        metadata={"target": "web_extension", "action": act, "tab": tab_title},
                    )
                except Exception as e:
                    logger.debug(f"Web media control via extension failed: {e}")

            # Fallback to virtual key
            await asyncio.to_thread(_send_vk, vk, repeat=count)
            return ToolResult(
                success=True,
                output=f"Dispatched web media control ({msg}).",
                metadata={"target": "web_fallback", "action": act},
            )

        # Case C: Auto-arbitration (Intelligent auto-detection between all Desktop Apps & Web Players)
        else:
            controlled = False

            # If Web is actively playing audio, prioritize Web
            if has_web_playing and extension_bridge.is_connected():
                try:
                    res = await extension_bridge.send_command(
                        "media_control",
                        {"action": act},
                        timeout=3.0
                    )
                    tab_title = res.get("tab_title", "Web Player")
                    results_log.append(f"Web Player ({tab_title})")
                    controlled = True
                except Exception:
                    pass

            # Check if any desktop media player is running / playing
            for dp in desktop_players:
                hwnd = dp["hwnd"]
                if sys.platform == "win32" and hwnd:
                    try:
                        import win32api
                        win32api.SendMessage(hwnd, WM_APPCOMMAND, 0, appcmd << 16)
                    except Exception:
                        pass
                results_log.append(f"{dp['name']} ({dp['title']})")
                controlled = True

            # Always dispatch hardware virtual keys as universal Windows baseline
            await asyncio.to_thread(_send_vk, vk, repeat=count)

            if controlled:
                targets_str = ", ".join(results_log)
                return ToolResult(
                    success=True,
                    output=f"Applied media control to {targets_str}: {msg}",
                    metadata={"targets": results_log, "action": act},
                )
            else:
                return ToolResult(
                    success=True,
                    output=f"Sent global Windows media signal: {msg}",
                    metadata={"target": "global_system", "action": act},
                )


class PlayMusicTool(NexusTool):
    name = "play_music"
    description = (
        "Search and play music, songs, artists, playlists, or discovery queries (e.g. 'top hindi music of 2025') "
        "seamlessly across Desktop Apps (Spotify, etc.) and Web Players (Spotify Web, YouTube, YouTube Music, SoundCloud). "
        "Includes smart query resolution via live web search."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        query: str = "",
        service: str = "spotify",
        prefer_desktop: bool = True,
        auto_play: bool = True,
        resolve_query: bool = True,
        **_
    ) -> ToolResult:
        clean_query = query.strip()
        # Clean quotes and redundant prefixes like song '...' or track "..."
        clean_query = re.sub(r"^['\"`]+|['\"`]+$", "", clean_query).strip()
        clean_query = re.sub(r"^(?:song|track|music|audio)\s+['\"`]?", "", clean_query, flags=re.IGNORECASE).strip()
        clean_query = re.sub(r"['\"`]+$", "", clean_query).strip()

        svc = (service or "spotify").lower().strip()

        # Normalize service names
        if svc in ("spotify_desktop", "desktop_spotify", "app"):
            svc = "spotify"
            prefer_desktop = True
        elif svc in ("spotify_web", "web_spotify", "web"):
            svc = "spotify"
            prefer_desktop = False

        # Smart discovery query resolution (e.g. "top hindi music of 2025" -> "Tauba Tauba" / "Top Hindi Songs 2025")
        resolution_note = ""
        effective_query = clean_query
        if resolve_query and clean_query:
            resolved_q, note = await _resolve_music_query(clean_query)
            if resolved_q:
                effective_query = resolved_q
                resolution_note = note

        is_generic_music = effective_query.lower() in (
            "", "music", "some music", "songs", "spotify", "play music", "play something", "tune", "tunes"
        )

        note_prefix = f"[{resolution_note}] " if resolution_note else ""

        # ── 1. SPOTIFY PLAYBACK (API first, then Desktop or Web Player) ───────
        if svc in ("spotify", "auto"):
            spotify_token = await _get_configured_spotify_token()
            token_valid = False
            if spotify_token:
                token_valid = await _spotify_token_is_valid(spotify_token)
                if token_valid is False:
                    logger.warning("Spotify connector token is invalid or expired; asking user to reconnect before retrying API playback.")
                    api_result = ToolResult(
                        success=False,
                        output="",
                        error="Spotify connector is connected but the saved Spotify access token is invalid or expired. Please reconnect the Spotify connector or refresh the token and retry.",
                    )
                else:
                    api_result = await _play_spotify_via_api(effective_query or clean_query, spotify_token)
                if api_result.success:
                    return api_result
                logger.warning(f"Spotify API playback failed, falling back to automation: {api_result.error}")

            spotify_exe = await asyncio.to_thread(_find_spotify_path)
            if spotify_token and token_valid is False and not spotify_exe and not extension_bridge.is_connected():
                if "api_result" in locals() and "invalid or expired" in (api_result.error or "").lower():
                    return ToolResult(
                        success=False,
                        output="",
                        error="Spotify connector is configured but the saved token is invalid or expired. Please reconnect Spotify and try again.",
                    )
            if prefer_desktop and spotify_exe:
                if is_generic_music:
                    def _play_generic():
                        try:
                            os.startfile("spotify:")
                        except Exception:
                            subprocess.Popen([spotify_exe])
                        time.sleep(0.8)
                        _activate_spotify_window()
                        _send_spotify_appcommand(APPCOMMAND_MEDIA_PLAY_PAUSE)
                        _send_vk(VK_MEDIA_PLAY_PAUSE)
                        smtc = _get_smtc_media_info()
                        track_desc = f"'{smtc['title']}' by {smtc['artist']}" if smtc.get("title") else "music playback"
                        return True, f"{note_prefix}Opened Spotify desktop app and resumed {track_desc}.", smtc
                    success, msg, media_info = await asyncio.to_thread(_play_generic)
                else:
                    encoded = urllib.parse.quote(effective_query)
                    uri = f"spotify:search:{encoded}"
                    def _launch():
                        try:
                            os.startfile(uri)
                        except Exception:
                            subprocess.Popen([spotify_exe, f"--protocol-uri={uri}"])
                    await asyncio.to_thread(_launch)
                    await asyncio.sleep(0.9)
                    await asyncio.to_thread(_activate_spotify_window)

                    if auto_play:
                        # Allow time for Spotify to render search results from cloud
                        await asyncio.sleep(1.2)
                        await asyncio.to_thread(_activate_spotify_window)

                        # Check if requested song is playing; if not, replan, take snapshots, and act
                        success, msg, media_info = await _ensure_spotify_playback_with_replanning(
                            effective_query=effective_query,
                            note_prefix=note_prefix,
                            max_replan_attempts=4
                        )
                    else:
                        success, msg, media_info = True, f"{note_prefix}Opened Spotify desktop and searched for '{effective_query}'.", {}


                # Fallback to Web Player with virtual cursor if desktop playback did not start or song was unverified
                if auto_play and not success and extension_bridge.is_connected():
                    logger.info("Spotify Desktop did not confirm playback of requested song; initiating Web Player fallback.")
                    try:
                        res = await extension_bridge.send_command(
                            "play_web_music",
                            {"service": "spotify", "query": effective_query, "auto_play": True},
                            timeout=8.0
                        )
                        target_url = res.get("url", "https://open.spotify.com")
                        return ToolResult(
                            success=True,
                            output=f"{note_prefix}Playing '{effective_query}' via Spotify Web Player with automated top-result click.",
                            metadata={"service": "spotify_web", "url": target_url, "query": effective_query, "fallback": True},
                        )
                    except Exception as e:
                        logger.debug(f"Web fallback failed: {e}")

                return ToolResult(
                    success=success,
                    output=msg,
                    metadata={"service": "spotify_desktop", "query": effective_query, "auto_play": auto_play, "media_state": media_info},
                )

            else:
                # Spotify Web Player path
                if extension_bridge.is_connected():
                    try:
                        res = await extension_bridge.send_command(
                            "play_web_music",
                            {"service": "spotify", "query": effective_query, "auto_play": auto_play},
                            timeout=8.0
                        )
                        target_url = res.get("url", "https://open.spotify.com")
                        return ToolResult(
                            success=True,
                            output=f"{note_prefix}Opened Spotify Web Player for '{effective_query or 'music'}' at {target_url}. Playback initiated.",
                            metadata={"service": "spotify_web", "url": target_url, "query": effective_query},
                        )
                    except Exception as e:
                        logger.debug(f"Extension play_web_music failed: {e}")

                import webbrowser
                if is_generic_music:
                    url = "https://open.spotify.com"
                else:
                    encoded = urllib.parse.quote_plus(effective_query)
                    url = f"https://open.spotify.com/search/{encoded}"
                webbrowser.open(url)
                return ToolResult(
                    success=True,
                    output=f"{note_prefix}Opened Spotify Web Player for '{effective_query or 'music'}' at {url}.",
                    metadata={"service": "spotify_web", "url": url, "query": effective_query},
                )

        # ── 2. YOUTUBE & YOUTUBE MUSIC PLAYBACK ─────────────────────────────────
        elif svc in ("youtube", "youtube_music", "yt", "ytm"):
            is_ytm = svc in ("youtube_music", "ytm")
            svc_name = "youtube_music" if is_ytm else "youtube"

            if extension_bridge.is_connected():
                try:
                    res = await extension_bridge.send_command(
                        "play_web_music",
                        {"service": svc_name, "query": effective_query, "auto_play": auto_play},
                        timeout=8.0
                    )
                    target_url = res.get("url", "")
                    display_name = "YouTube Music" if is_ytm else "YouTube"
                    return ToolResult(
                        success=True,
                        output=f"{note_prefix}Opened {display_name} for '{effective_query}' and started playback at {target_url}.",
                        metadata={"service": svc_name, "url": target_url, "query": effective_query},
                    )
                except Exception as e:
                    logger.debug(f"Extension play_web_music for YouTube failed: {e}")

            import webbrowser
            encoded = urllib.parse.quote_plus(effective_query or "music")
            if is_ytm:
                url = f"https://music.youtube.com/search?q={encoded}"
                display_name = "YouTube Music"
            else:
                url = f"https://www.youtube.com/results?search_query={encoded}"
                display_name = "YouTube"
            webbrowser.open(url)
            return ToolResult(
                success=True,
                output=f"{note_prefix}Opened {display_name} search for '{effective_query}' at {url}.",
                metadata={"service": svc_name, "url": url, "query": effective_query},
            )

        # ── 3. SOUNDCLOUD PLAYBACK ──────────────────────────────────────────────
        elif svc in ("soundcloud", "sc"):
            if extension_bridge.is_connected():
                try:
                    res = await extension_bridge.send_command(
                        "play_web_music",
                        {"service": "soundcloud", "query": effective_query, "auto_play": auto_play},
                        timeout=8.0
                    )
                    return ToolResult(
                        success=True,
                        output=f"{note_prefix}Opened SoundCloud for '{effective_query}' at {res.get('url', '')}.",
                        metadata={"service": "soundcloud", "query": effective_query},
                    )
                except Exception:
                    pass

            import webbrowser
            encoded = urllib.parse.quote_plus(effective_query or "music")
            url = f"https://soundcloud.com/search?q={encoded}"
            webbrowser.open(url)
            return ToolResult(
                success=True,
                output=f"{note_prefix}Opened SoundCloud search for '{effective_query}' at {url}.",
                metadata={"service": "soundcloud", "url": url, "query": effective_query},
            )

        else:
            return ToolResult(
                success=False,
                error=f"Unsupported music service: '{service}'. Supported services: spotify, spotify_web, youtube, youtube_music, soundcloud.",
                output="",
            )
