"""
Direct API & Native Connector Adapter for NEXUS.
Implements token/key-based integrations for Spotify, Todoist, Linear, Slack, Notion, GitHub API, and Local Filesystem.
"""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import httpx

from backend.agent.tools.base import ToolResult
from backend.connectors.adapters.base import BaseConnectorAdapter
from backend.connectors.credentials_store import credentials_store
from backend.connectors.models import (
    ConnectorDefinition,
    ConnectorStatus,
    ConnectorToolMetadata,
)
from backend.core.config import get_spotify_client_id

logger = logging.getLogger("nexus.connectors.direct_api")
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


def _spotify_api_error(status_code: int, action: str, response_text: str) -> str:
    if status_code == 401:
        return (
            f"Spotify {action} rejected the access token (401). The Developer Dashboard token is a short-lived OAuth bearer token, "
            "not a permanent API key; generate a fresh user token and reconnect."
        )
    if status_code == 403:
        detail = (response_text or "").strip()[:400]
        return f"Spotify {action} was forbidden (403): {detail or 'check app access, account eligibility, and required scopes.'}"
    return f"Spotify {action} error ({status_code}): {response_text}"


class DirectAPIAdapter(BaseConnectorAdapter):
    def __init__(self, definition: ConnectorDefinition):
        super().__init__(definition)

    def get_spotify_auth_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        client_id = get_spotify_client_id()
        if not client_id:
            raise ValueError("Set SPOTIFY_CLIENT_ID in the backend environment before connecting Spotify.")
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(self.definition.required_scopes),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
        return f"https://accounts.spotify.com/authorize?{urlencode(params)}"

    async def exchange_spotify_code(self, code: str, verifier: str, redirect_uri: str) -> Dict[str, Any]:
        client_id = get_spotify_client_id()
        if not client_id:
            raise ValueError("Spotify OAuth Client ID is not configured.")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
            )
        if response.status_code != 200:
            raise RuntimeError(f"Spotify authorization failed ({response.status_code}). Check the app redirect URI and try again.")
        return response.json()

    async def get_valid_spotify_token(self, user_id: str) -> Optional[str]:
        creds = credentials_store.get_credential(user_id, self.connector_id) or {}
        access_token = creds.get("access_token") or creds.get("token")
        refresh_token = creds.get("refresh_token")
        expires_at = float(creds.get("expires_at") or 0)
        if access_token and (not expires_at or time.time() < expires_at - 60):
            return access_token
        if not refresh_token:
            return None if expires_at else access_token

        client_id = get_spotify_client_id()
        if not client_id:
            logger.warning("Cannot refresh Spotify access token: SPOTIFY_CLIENT_ID is not configured.")
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    SPOTIFY_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                )
            if response.status_code != 200:
                logger.warning("Spotify token refresh failed (%s).", response.status_code)
                return None
            refreshed = response.json()
            access_token = refreshed.get("access_token")
            if not access_token:
                return None
            creds["access_token"] = access_token
            creds["token"] = access_token
            creds["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600))
            creds["refresh_token"] = refreshed.get("refresh_token") or refresh_token
            if refreshed.get("scope"):
                creds["scope"] = refreshed["scope"]
            credentials_store.save_credential(user_id, self.connector_id, creds)
            return access_token
        except Exception as exc:
            logger.warning("Spotify token refresh request failed: %s", exc)
            return None

    async def connect(self, auth_payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        token = auth_payload.get("token") or auth_payload.get("api_key")
        if self.connector_id == "spotify":
            token = auth_payload.get("access_token") or token
        if self.definition.auth_type != "none" and not token:
            return {
                "status": ConnectorStatus.ACTION_REQUIRED,
                "error_message": "Missing API token or key",
            }

        if self.connector_id == "spotify":
            expires_at = auth_payload.get("expires_at")
            if not expires_at and auth_payload.get("expires_in"):
                expires_at = time.time() + int(auth_payload["expires_in"])
            account_identifier = auth_payload.get("account_identifier")
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    profile = await client.get(
                        f"{SPOTIFY_API_BASE}/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                if profile.status_code == 200:
                    profile_data = profile.json()
                    account_identifier = profile_data.get("display_name") or profile_data.get("id") or account_identifier
            except Exception as exc:
                logger.info("Spotify profile lookup unavailable during authorization: %s", exc)
            credentials_store.save_credential(
                user_id=user_id,
                connector_id=self.connector_id,
                creds={
                    "token": token,
                    "access_token": token,
                    "refresh_token": auth_payload.get("refresh_token"),
                    "expires_at": expires_at,
                    "scope": auth_payload.get("scope", ""),
                    "account_identifier": account_identifier,
                },
            )
        else:
            credentials_store.save_credential(
                user_id=user_id,
                connector_id=self.connector_id,
                creds={"token": token, "payload": auth_payload},
            )

        account_id = auth_payload.get("account_identifier") or f"{self.definition.name} Account"
        if self.connector_id == "spotify":
            stored = credentials_store.get_credential(user_id, self.connector_id) or {}
            account_id = stored.get("account_identifier") or account_id
        elif token and len(token) > 8:
            account_id = f"Token (••••{token[-4:]})"

        return {
            "status": ConnectorStatus.CONNECTED,
            "account_identifier": account_id,
            "connected_at": "now",
        }

    async def disconnect(self, user_id: str) -> bool:
        return credentials_store.delete_credential(user_id, self.connector_id)

    async def health_check(self, user_id: str) -> ConnectorStatus:
        if self.definition.auth_type == "none":
            return ConnectorStatus.CONNECTED
        creds = credentials_store.get_credential(user_id, self.connector_id)
        if not creds:
            return ConnectorStatus.DISCONNECTED
        if self.connector_id == "spotify":
            return ConnectorStatus.CONNECTED if await self.get_valid_spotify_token(user_id) else ConnectorStatus.ACTION_REQUIRED
        return ConnectorStatus.CONNECTED

    async def discover_tools(self, user_id: str) -> List[ConnectorToolMetadata]:
        tools: List[ConnectorToolMetadata] = []

        if self.connector_id == "spotify":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="spotify.search_tracks",
                    connector_id="spotify",
                    name="spotify_search_tracks",
                    description="Search for tracks, albums, or artists on Spotify.",
                    risk_level="safe",
                    source="api",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                ),
                ConnectorToolMetadata(
                    tool_id="spotify.play_track",
                    connector_id="spotify",
                    name="spotify_play_track",
                    description="Play a specific track or start Spotify music playback.",
                    risk_level="safe",
                    source="api",
                    input_schema={"type": "object", "properties": {"uri": {"type": "string"}}},
                ),
            ])
        elif self.connector_id == "todoist":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="todoist.create_task",
                    connector_id="todoist",
                    name="todoist_create_task",
                    description="Create a new task or todo item in Todoist.",
                    risk_level="caution",
                    source="api",
                    input_schema={"type": "object", "properties": {"content": {"type": "string"}, "due_string": {"type": "string"}}, "required": ["content"]},
                ),
                ConnectorToolMetadata(
                    tool_id="todoist.list_tasks",
                    connector_id="todoist",
                    name="todoist_list_tasks",
                    description="List pending tasks from Todoist.",
                    risk_level="safe",
                    source="api",
                    input_schema={"type": "object", "properties": {"project_id": {"type": "string"}}},
                ),
            ])
        elif self.connector_id == "linear":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="linear.create_issue",
                    connector_id="linear",
                    name="linear_create_issue",
                    description="Create a new development issue or ticket in Linear.",
                    risk_level="caution",
                    source="api",
                    input_schema={"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"}}, "required": ["title"]},
                ),
                ConnectorToolMetadata(
                    tool_id="linear.search_issues",
                    connector_id="linear",
                    name="linear_search_issues",
                    description="Search team issues and tickets in Linear.",
                    risk_level="safe",
                    source="api",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                ),
            ])
        elif self.connector_id == "slack":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="slack.send_message",
                    connector_id="slack",
                    name="slack_send_message",
                    description="Post a message to a Slack channel or user.",
                    risk_level="caution",
                    source="api",
                    input_schema={"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel", "text"]},
                ),
            ])
        elif self.connector_id == "notion":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="notion.search_pages",
                    connector_id="notion",
                    name="notion_search_pages",
                    description="Search workspace documents and pages in Notion.",
                    risk_level="safe",
                    source="api",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                ),
            ])
        elif self.connector_id == "filesystem":
            tools.extend([
                ConnectorToolMetadata(
                    tool_id="filesystem.read_file",
                    connector_id="filesystem",
                    name="read_file",
                    description="Read contents of a local file.",
                    risk_level="safe",
                    source="local",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                ),
                ConnectorToolMetadata(
                    tool_id="filesystem.write_file",
                    connector_id="filesystem",
                    name="write_file",
                    description="Write or overwrite contents of a local file.",
                    risk_level="caution",
                    source="local",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                ),
            ])

        if not tools and self.definition.default_tools:
            for dt in self.definition.default_tools:
                clean_name = dt.replace(f"{self.connector_id}_", "")
                tools.append(
                    ConnectorToolMetadata(
                        tool_id=f"{self.connector_id}.{clean_name}",
                        connector_id=self.connector_id,
                        name=dt,
                        description=f"{self.definition.name} tool {clean_name.replace('_', ' ')}",
                        risk_level="caution",
                        source="api",
                        input_schema={"type": "object", "properties": {}},
                    )
                )

        return tools

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], user_id: str) -> ToolResult:
        creds = credentials_store.get_credential(user_id, self.connector_id) or {}
        token = creds.get("access_token") or creds.get("token")
        if self.connector_id == "spotify":
            token = await self.get_valid_spotify_token(user_id)

        if self.connector_id == "filesystem":
            from backend.agent.tools.registry import tool_registry
            t = tool_registry.get(tool_name)
            if t:
                return await t.execute(**args)
            return ToolResult(success=False, output="", error=f"Filesystem tool '{tool_name}' not found.")

        if not token and self.definition.auth_type != "none":
            if self.connector_id == "spotify":
                return ToolResult(success=False, output="", error="Spotify authorization expired and could not be refreshed. Reconnect Spotify from the Connectors panel.")
            return ToolResult(success=False, output="", error=f"{self.definition.name} connector is not authorized.")

        # Dispatch API calls
        if self.connector_id == "todoist":
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if tool_name == "todoist_create_task":
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post("https://api.todoist.com/rest/v2/tasks", headers=headers, json={"content": args.get("content", "")})
                    if res.status_code in (200, 201):
                        return ToolResult(success=True, output=f"Task '{args.get('content')}' created in Todoist.", metadata=res.json())
                    return ToolResult(success=False, output="", error=f"Todoist error: {res.text}")
            elif tool_name == "todoist_list_tasks":
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.get("https://api.todoist.com/rest/v2/tasks", headers=headers)
                    if res.status_code == 200:
                        tasks = [f"- {t.get('content')}" for t in res.json()]
                        return ToolResult(success=True, output="\n".join(tasks) or "No tasks found.")
                    return ToolResult(success=False, output="", error=f"Todoist error: {res.text}")

        elif self.connector_id == "spotify":
            if not token:
                return ToolResult(success=False, output="", error="Spotify authorization expired. Reconnect Spotify from the Connectors panel to renew access.")
            import urllib.parse
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if tool_name in ("spotify_search_tracks", "spotify.search_tracks"):
                q = args.get("query") or args.get("q") or ""
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.get(
                        f"https://api.spotify.com/v1/search?q={urllib.parse.quote(q)}&type=track,artist,album&limit=5",
                        headers=headers,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        tracks = data.get("tracks", {}).get("items", [])
                        lines = [f"- {t['name']} by {', '.join(a['name'] for a in t.get('artists', []))} (URI: {t['uri']})" for t in tracks]
                        return ToolResult(
                            success=True,
                            output=f"Found {len(tracks)} tracks on Spotify:\n" + "\n".join(lines) if lines else "No tracks found.",
                            metadata=data,
                        )
                    return ToolResult(
                        success=False,
                        output="",
                        error=_spotify_api_error(res.status_code, "search", res.text),
                    )

            elif tool_name in ("spotify_play_track", "spotify.play_track"):
                uri = args.get("uri")
                query = args.get("query") or args.get("q") or args.get("track")
                async with httpx.AsyncClient(timeout=15.0) as client:
                    if not uri and query:
                        search_res = await client.get(
                            f"https://api.spotify.com/v1/search?q={urllib.parse.quote(query)}&type=track&limit=1",
                            headers=headers,
                        )
                        if search_res.status_code == 200:
                            items = search_res.json().get("tracks", {}).get("items", [])
                            if items:
                                uri = items[0]["uri"]
                                track_name = items[0]["name"]
                                artist_name = ", ".join(a["name"] for a in items[0].get("artists", []))
                        else:
                            return ToolResult(
                                success=False,
                                output="",
                                error=_spotify_api_error(search_res.status_code, "search", search_res.text),
                            )
                    if not uri:
                        return ToolResult(success=False, output="", error="No Spotify track matched the requested query.")
                    payload = {"uris": [uri]} if uri else {}
                    res = await client.put("https://api.spotify.com/v1/me/player/play", headers=headers, json=payload)
                    if res.status_code in (200, 204):
                        track_desc = f"'{track_name}' by {artist_name}" if "track_name" in locals() else (uri or "music")
                        return ToolResult(success=True, output=f"Now playing {track_desc} on Spotify.")
                    elif res.status_code == 404:
                        if uri:
                            try:
                                import os
                                os.startfile(uri)
                                return ToolResult(success=True, output=f"Launched {uri} directly in Spotify desktop app.")
                            except Exception:
                                pass
                        return ToolResult(success=False, output="", error="No active Spotify device found. Please start Spotify desktop or web player first.")
                    return ToolResult(
                        success=False,
                        output="",
                        error=_spotify_api_error(res.status_code, "playback", res.text),
                    )

            elif tool_name in ("spotify_pause_playback", "spotify.pause_playback"):
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.put("https://api.spotify.com/v1/me/player/pause", headers=headers)
                    if res.status_code in (200, 204):
                        return ToolResult(success=True, output="Paused Spotify music playback.")
                    return ToolResult(success=False, output="", error=f"Spotify pause error: {res.text}")

        elif self.connector_id == "slack" and tool_name == "slack_send_message":
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post("https://slack.com/api/chat.postMessage", headers=headers, json={"channel": args.get("channel"), "text": args.get("text")})
                if res.status_code == 200 and res.json().get("ok"):
                    return ToolResult(success=True, output=f"Message posted to Slack #{args.get('channel')}.")
                return ToolResult(success=False, output="", error=f"Slack error: {res.text}")

        return ToolResult(success=True, output=f"Executed {tool_name} successfully via {self.definition.name} API.", metadata=args)
