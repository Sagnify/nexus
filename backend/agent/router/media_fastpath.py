"""Media and Music Fastpath Compiler for instant (<1ms) playback execution.
Supports Spotify Desktop, Spotify Web Player, YouTube, YouTube Music, and global system media controls.
"""
from __future__ import annotations
import re
from typing import Optional

# Media control keyword matchers
MEDIA_ACTIONS = {
    "pause": (
        r"\b(?:pause|pause\s+(?:the\s+)?(?:music|song|track|audio|playback|media|video)|stop\s+(?:the\s+)?(?:music|song|playback))\b"
    ),
    "resume": (
        r"\b(?:unpause|resume\s+(?:the\s+)?(?:music|song|track|audio|playback|media)|continue\s+(?:playing\s+)?(?:music|song))\b"
    ),
    "next": (
        r"\b(?:next\s+(?:song|track|music)|skip\s+(?:the\s+)?(?:song|track|music)?|skip\s+to\s+next\s+(?:song|track))\b"
    ),
    "previous": (
        r"\b(?:previous\s+(?:song|track|music)|prev\s+(?:song|track|music)|last\s+(?:song|track)|back\s+(?:a\s+)?(?:song|track)|restart\s+(?:the\s+)?song)\b"
    ),
    "volume_up": (
        r"\b(?:volume\s+up|turn\s+(?:the\s+)?volume\s+up|increase\s+(?:the\s+)?volume|louder|make\s+it\s+louder)\b"
    ),
    "volume_down": (
        r"\b(?:volume\s+down|turn\s+(?:the\s+)?volume\s+down|decrease\s+(?:the\s+)?volume|lower\s+(?:the\s+)?volume|quieter|make\s+it\s+quieter|turn\s+it\s+down)\b"
    ),
    "mute": (
        r"\b(?:mute|unmute)(?:\s+(?:the\s+)?(?:volume|audio|sound|speaker|speakers))?\b"
    ),
}


def extract_media_intent(goal: str) -> Optional[dict]:
    """
    Analyzes user goal for media controls or music playback.
    Returns structured intent dict or None.
    """
    if not goal:
        return None

    raw = goal.strip()
    lower = raw.lower()

    # Strip conversational prefixes and trailing punctuation
    lower = re.sub(r'^(?:(?:hey|hi|hello|ok|okay)\s+)?(?:nexus[\s,:-]*)+', '', lower).strip()
    lower = re.sub(r'^(?:please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+(?:it\s+)?to\s+|i\s+would\s+like\s+to\s+)+', '', lower).strip()
    lower = re.sub(r'^[\s,:-]+', '', lower).strip()
    lower = re.sub(r'[.!?,\s;:]+$', '', lower).strip()

    # 1. Check Media Control actions first (pause, skip, volume, etc.)
    for action, pattern in MEDIA_ACTIONS.items():
        if re.search(pattern, lower):
            # Check if specific target is mentioned in control query
            target = "auto"
            if re.search(r'\b(?:spotify\s+app|desktop\s+spotify|spotify\s+desktop)\b', lower):
                target = "spotify"
            elif re.search(r'\b(?:spotify\s+web|web\s+player|web\s+spotify|browser|chrome|edge)\b', lower):
                target = "web"
            elif re.search(r'\b(?:spotify)\b', lower):
                target = "spotify"
            elif re.search(r'\b(?:vlc(?:\s+media\s+player)?)\b', lower):
                target = "vlc"
            elif re.search(r'\b(?:windows\s+media\s+player|media\s+player|wmplayer)\b', lower):
                target = "wmplayer"
            elif re.search(r'\b(?:itunes)\b', lower):
                target = "itunes"
            elif re.search(r'\b(?:apple\s+music)\b', lower):
                target = "apple_music"
            elif re.search(r'\b(?:foobar2000|foobar)\b', lower):
                target = "foobar2000"
            elif re.search(r'\b(?:aimp)\b', lower):
                target = "aimp"
            elif re.search(r'\b(?:potplayer)\b', lower):
                target = "potplayer"
            elif re.search(r'\b(?:tidal)\b', lower):
                target = "tidal"
            elif re.search(r'\b(?:amazon\s+music)\b', lower):
                target = "amazon_music"
            elif re.search(r'\b(?:youtube|yt)\b', lower):
                target = "youtube"

            return {
                "type": "control",
                "action": action,
                "target": target,
            }

    # 2. Check for explicit Web vs Desktop mentions
    is_explicit_web = bool(re.search(r'\b(?:web|browser|chrome|edge|online|spotify\s+web|web\s+player|from\s+web)\b', lower))
    is_explicit_desktop = bool(re.search(r'\b(?:app|desktop|desktop\s+app|spotify\s+app)\b', lower))
    prefer_desktop = not is_explicit_web if is_explicit_web else True

    has_spotify = bool(re.search(r'\b(?:spotify|open\.spotify\.com)\b', lower)) or bool(re.search(r'\bform\s+spotify\b', lower))
    has_ytm = bool(re.search(r'\b(?:youtube\s+music|yt\s+music|ytm)\b', lower))
    has_youtube = bool(re.search(r'\b(?:youtube|yt)\b', lower)) and not has_ytm
    has_soundcloud = bool(re.search(r'\b(?:soundcloud|sc)\b', lower))

    # Pattern: YouTube Music
    if has_ytm:
        m = re.search(r'^(?:play|listen\s+to|stream)\s+(?:(?:some|the)\s+)?(.+?)\s+(?:on|from|in|via)\s+(?:youtube\s+music|yt\s+music|ytm)$', lower)
        q = m.group(1).strip() if m else ""
        if not q:
            m2 = re.search(r'(?:youtube\s+music|yt\s+music|ytm)\s+(?:and\s+)?(?:play|search(?:\s+for)?)\s*(.*)', lower)
            q = m2.group(1).strip() if m2 else ""
        return {
            "type": "play",
            "service": "youtube_music",
            "query": q,
            "prefer_desktop": False,
        }

    # Pattern: "open spotify and play <query>" or "launch spotify and play <query>"
    m = re.search(r'^(?:open|launch|start)\s+spotify(?:\s+(?:app|desktop|web))?\s+(?:and\s+)?(?:play|search(?:\s+for)?)\s*(.*)', lower)
    if m:
        query = m.group(1).strip()
        query = re.sub(r'^(?:some\s+)?(?:music|songs?)\b', '', query).strip()
        return {
            "type": "play",
            "service": "spotify",
            "query": query,
            "prefer_desktop": prefer_desktop,
        }

    # Pattern: "in/on spotify play <query>" or "spotify play <query>"
    m = re.search(r'^(?:in|on|from)\s+spotify(?:\s+(?:app|desktop|web))?\s+(?:please\s+)?(?:play|search(?:\s+for)?)\s*(.*)', lower)
    if not m:
        m = re.search(r'^spotify(?:\s+(?:app|desktop|web))?\s+(?:please\s+)?(?:play|search(?:\s+for)?)\s*(.*)', lower)
    if m:
        query = m.group(1).strip()
        query = re.sub(r'^(?:some\s+)?(?:music|songs?)\b', '', query).strip()
        return {
            "type": "play",
            "service": "spotify",
            "query": query,
            "prefer_desktop": prefer_desktop,
        }

    # Pattern: "search for <query> on/in spotify" or "find <query> on spotify"
    m = re.search(r'^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)\s+(?:on|from|in|via)\s+spotify(?:\s+(?:app|desktop|web|browser))?$', lower)
    if m:
        return {
            "type": "play",
            "service": "spotify",
            "query": m.group(1).strip(),
            "prefer_desktop": prefer_desktop,
            "auto_play": False,
        }

    # Pattern: "play <query> on/from spotify [web/app]" or "listen to <query> on/from spotify"
    m = re.search(r'^(?:play|listen\s+to|stream)\s+(?:(?:some|the)\s+)?(.+?)\s+(?:on|from|in|via|form)\s+spotify(?:\s+(?:app|desktop|web|browser))?(?:\s+and\s+stuff.*)?$', lower)
    if m:
        q = m.group(1).strip()
        clean_m = re.sub(r'[\W_]+', ' ', q).strip()
        if clean_m in ("music", "some music", "a song", "songs", "tracks", "stuff", "media", "media like play music", "play music", "m edia like play music"):
            q = ""
        return {
            "type": "play",
            "service": "spotify",
            "query": q,
            "prefer_desktop": prefer_desktop,
            "auto_play": True,
        }

    # Pattern: "play music from spotify and stuff or things" or "play music on spotify"
    if has_spotify and any(w in lower for w in ("play", "listen", "start", "stream", "music")):
        m = re.search(r'(?:play|listen\s+to|stream)\s+(?:some\s+)?(?:music|songs?|jazz|rock|pop|lofi|tracks?)?(?:\s+(?:from|on|in|form)\s+spotify(?:\s+(?:app|web|desktop))?)?(?:\s+(?:for|like)\s+(.+))?', lower)
        extracted_query = m.group(1).strip() if (m and m.group(1)) else ""
        extracted_query = re.sub(r'\s+(?:and\s+stuff|or\s+things).*$', '', extracted_query).strip()
        return {
            "type": "play",
            "service": "spotify",
            "query": extracted_query,
            "prefer_desktop": prefer_desktop,
        }

    # Pattern: "play <query> on youtube"
    if has_youtube:
        m = re.search(r'^(?:play|listen\s+to|watch)\s+(?:(?:some|the)\s+)?(.+?)\s+(?:on|from|in|via)\s+youtube$', lower)
        q = m.group(1).strip() if m else ""
        return {
            "type": "play",
            "service": "youtube",
            "query": q,
            "prefer_desktop": False,
        }

    # Pattern: "play <query> on soundcloud"
    if has_soundcloud:
        m = re.search(r'^(?:play|listen\s+to|stream)\s+(?:(?:some|the)\s+)?(.+?)\s+(?:on|from|in|via)\s+soundcloud$', lower)
        q = m.group(1).strip() if m else ""
        return {
            "type": "play",
            "service": "soundcloud",
            "query": q,
            "prefer_desktop": False,
        }

    # Pattern: Generic "play <query> from web" or "play <query> in browser"
    if is_explicit_web and any(w in lower for w in ("play", "stream", "listen")):
        m = re.search(r'^(?:play|stream|listen\s+to)\s+(?:(?:some|the)\s+)?(.+?)(?:\s+(?:from|on|in)\s+(?:the\s+)?(?:web|browser|chrome|online))?$', lower)
        q = m.group(1).strip() if m else ""
        if q in ("music", "something", "some tunes", "a song", "web", "browser"):
            q = ""
        return {
            "type": "play",
            "service": "spotify",
            "query": q,
            "prefer_desktop": False,
        }

    # Pattern: "play <query>" where query is clearly music/song (e.g. "play bohemian rhapsody", "play the weeknd", "play some jazz", "play starboy")
    m = re.search(r'^(?:play|stream)\s+(?:(?:some|the)\s+)?(.+)', lower)
    if m:
        candidate = m.group(1).strip()
        # Filter out non-music verbs/phrases e.g. "play chess", "play a game", "play video 1"
        non_music = ("chess", "game", "minecraft", "counter strike", "fortnite", "roblox", "card", "poker", "video 1", "video 2", "audio file")
        if not any(candidate.startswith(nm) for nm in non_music):
            if candidate in ("music", "something", "some tunes", "a song"):
                candidate = ""
            return {
                "type": "play",
                "service": "spotify",
                "query": candidate,
                "prefer_desktop": prefer_desktop,
            }

    return None


def build_media_plan(goal: str) -> Optional[list[dict]]:
    """
    Deterministic <1ms plan compiler for media & music goals.
    """
    intent = extract_media_intent(goal)
    if not intent:
        return None

    if intent["type"] == "control":
        action = intent["action"]
        target = intent.get("target", "auto")
        readable_action = action.replace("_", " ").title()
        target_display = f" ({target.title()})" if target != "auto" else ""
        return [
            {
                "title": f"Media Control: {readable_action}{target_display}",
                "description": f"Send {readable_action} signal to active media player (Desktop / Web)",
                "tool": "media_control",
                "args": {"action": action, "target": target},
            }
        ]

    elif intent["type"] == "play":
        query = intent.get("query", "").strip()
        service = intent.get("service", "spotify")
        prefer_desktop = intent.get("prefer_desktop", True)
        auto_play = intent.get("auto_play", True)

        if service == "spotify":
            from backend.agent.tools.registry import tool_registry
            from backend.connectors.credentials_store import credentials_store
            spotify_creds = credentials_store.get_credential("default", "spotify") or {}
            has_spotify_api = bool(spotify_creds.get("token") or spotify_creds.get("access_token"))
            if has_spotify_api and tool_registry.has("spotify_play_track"):
                return [
                    {
                        "title": f"Play '{query}' on Spotify",
                        "description": f"Stream '{query}' directly via connected Spotify Web API",
                        "tool": "spotify_play_track",
                        "args": {"query": query},
                    }
                ]

            mode_str = "Desktop App" if prefer_desktop else "Web Player"
            verb = "Play" if auto_play else "Search"
            display_target = f"'{query}' on Spotify ({mode_str})" if query else f"Music on Spotify ({mode_str})"
            return [
                {
                    "title": f"{verb} {display_target}",
                    "description": f"Launch Spotify ({mode_str}) and {'initiate playback for' if auto_play else 'display search results for'} {display_target}",
                    "tool": "play_music",
                    "args": {
                        "query": query,
                        "service": "spotify",
                        "prefer_desktop": prefer_desktop,
                        "auto_play": auto_play,
                    },
                }
            ]
        elif service == "youtube_music":
            return [
                {
                    "title": f"Play '{query}' on YouTube Music",
                    "description": f"Search and play '{query}' on YouTube Music",
                    "tool": "play_music",
                    "args": {
                        "query": query,
                        "service": "youtube_music",
                        "auto_play": True,
                    },
                }
            ]
        elif service == "youtube":
            return [
                {
                    "title": f"Play '{query}' on YouTube",
                    "description": f"Search and play '{query}' on YouTube",
                    "tool": "play_music",
                    "args": {
                        "query": query,
                        "service": "youtube",
                        "auto_play": True,
                    },
                }
            ]
        elif service == "soundcloud":
            return [
                {
                    "title": f"Play '{query}' on SoundCloud",
                    "description": f"Search and play '{query}' on SoundCloud",
                    "tool": "play_music",
                    "args": {
                        "query": query,
                        "service": "soundcloud",
                        "auto_play": True,
                    },
                }
            ]

    return None
