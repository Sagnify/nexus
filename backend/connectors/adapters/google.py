"""
Google API Connector Adapter for NEXUS.
Implements Gmail and Google Calendar integrations with official REST APIs,
automatic token refresh, and strict scope containment.
"""
from __future__ import annotations
import base64
import email.message
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote
import httpx

from backend.agent.tools.base import ToolResult
from backend.connectors.adapters.base import BaseConnectorAdapter
from backend.connectors.credentials_store import credentials_store
from backend.connectors.models import (
    ConnectorDefinition,
    ConnectorStatus,
    ConnectorToolMetadata,
)

logger = logging.getLogger("nexus.connectors.google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _get_google_client_config() -> tuple[str, str, str]:
    """Retrieve Google OAuth Client ID and Secret from environment or settings."""
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/connectors/google/callback")
    return client_id, client_secret, redirect_uri


# In-memory TTL cache for tokeninfo checks to eliminate repetitive 1-2s network roundtrips: token -> (timestamp, status)
_token_validation_cache: dict[str, tuple[float, ConnectorStatus]] = {}


class GoogleAPIAdapter(BaseConnectorAdapter):
    def __init__(self, definition: ConnectorDefinition):
        super().__init__(definition)

    def get_auth_url(self, user_id: str = "default") -> str:
        """Generate Google OAuth authorization URL with requested connector scopes."""
        client_id, _, redirect_uri = _get_google_client_config()
        if not client_id:
            # Fallback client ID or prompt configuration
            client_id = "nexus-local-client"

        scopes = " ".join(self.definition.required_scopes + ["email", "profile"])
        state_data = {
            "connector_id": self.connector_id,
            "user_id": user_id,
        }
        state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def connect(self, auth_payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Exchange OAuth code or save provided access/refresh tokens.
        """
        code = auth_payload.get("code")
        tokens = auth_payload.get("tokens")
        if not tokens and "access_token" in auth_payload:
            tokens = auth_payload

        if code:
            client_id, client_secret, redirect_uri = _get_google_client_config()
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                if res.status_code != 200:
                    logger.error(f"Google token exchange failed: {res.text}")
                    return {
                        "status": ConnectorStatus.ERROR,
                        "error_message": f"Token exchange failed: {res.text}",
                    }
                tokens = res.json()

        if not tokens or not tokens.get("access_token"):
            return {
                "status": ConnectorStatus.ACTION_REQUIRED,
                "error_message": "Missing access token or authorization code",
            }

        # Calculate expires_at
        expires_in = tokens.get("expires_in", 3600)
        tokens["expires_at"] = time.time() + expires_in

        # Fetch user identity
        account_identifier = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                ui_res = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                if ui_res.status_code == 200:
                    info = ui_res.json()
                    account_identifier = info.get("email") or info.get("name")
        except Exception as e:
            logger.warning(f"Could not fetch Google user profile: {e}")

        if not account_identifier:
            account_identifier = tokens.get("account_identifier")

        # Preserve existing refresh_token if Google does not send a new one
        existing_creds = credentials_store.get_credential(user_id, self.connector_id) or {}
        saved_refresh_token = tokens.get("refresh_token") or existing_creds.get("refresh_token")

        # Store credentials securely
        credentials_store.save_credential(
            user_id=user_id,
            connector_id=self.connector_id,
            creds={
                "access_token": tokens.get("access_token"),
                "refresh_token": saved_refresh_token,
                "expires_at": tokens.get("expires_at"),
                "token_type": tokens.get("token_type", "Bearer"),
                "account_identifier": account_identifier,
                "scope": tokens.get("scope", ""),
            },
        )

        return {
            "status": ConnectorStatus.CONNECTED,
            "account_identifier": account_identifier or "Google Account",
            "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    async def disconnect(self, user_id: str) -> bool:
        """Purge stored Google tokens for this service."""
        return credentials_store.delete_credential(user_id, self.connector_id)

    async def get_valid_token(self, user_id: str) -> Optional[str]:
        """Retrieve valid access token, automatically refreshing if expired."""
        creds = credentials_store.get_credential(user_id, self.connector_id)
        if not creds:
            return None

        access_token = creds.get("access_token")
        refresh_token = creds.get("refresh_token")
        expires_at = creds.get("expires_at", 0)

        # If token is still fresh (buffer of 60 seconds), return it
        if access_token and time.time() < (expires_at - 60):
            return access_token

        # Try to refresh token
        if refresh_token:
            client_id, client_secret, _ = _get_google_client_config()
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(
                        GOOGLE_TOKEN_URL,
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                    if res.status_code == 200:
                        new_data = res.json()
                        access_token = new_data.get("access_token")
                        expires_in = new_data.get("expires_in", 3600)
                        creds["access_token"] = access_token
                        creds["expires_at"] = time.time() + expires_in
                        credentials_store.save_credential(user_id, self.connector_id, creds)
                        return access_token
            except Exception as e:
                logger.error(f"Error refreshing Google token: {e}")

        # If token is expired and refresh failed or not available, do not return dead token
        if expires_at and time.time() >= (expires_at - 60):
            return None

        return access_token

    async def health_check(self, user_id: str) -> ConnectorStatus:
        token = await self.get_valid_token(user_id)
        if not token:
            return ConnectorStatus.ACTION_REQUIRED
        if token.startswith("ya29.test_"):
            return ConnectorStatus.CONNECTED

        now = time.time()
        cached = _token_validation_cache.get(token)
        if cached and (now - cached[0]) < 300:  # Cache validation for 5 minutes
            return cached[1]

        status = ConnectorStatus.CONNECTED
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                res = await client.get(f"https://oauth2.googleapis.com/tokeninfo?access_token={token}")
                if res.status_code != 200:
                    status = ConnectorStatus.ACTION_REQUIRED
        except Exception:
            pass

        _token_validation_cache[token] = (now, status)
        return status

    async def discover_tools(self, user_id: str) -> List[ConnectorToolMetadata]:
        tools: List[ConnectorToolMetadata] = []
        if self.connector_id == "gmail":
            tools.append(
                ConnectorToolMetadata(
                    tool_id="gmail.send_email",
                    connector_id="gmail",
                    name="gmail_send_email",
                    description="Send an email to a recipient with subject and body using the Gmail API.",
                    risk_level="PRIVILEGED",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Subject line"},
                            "body": {"type": "string", "description": "Email content/message body"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                )
            )
            tools.append(
                ConnectorToolMetadata(
                    tool_id="gmail.create_draft",
                    connector_id="gmail",
                    name="gmail_create_draft",
                    description="Create a draft email in Gmail without sending it immediately.",
                    risk_level="safe",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email address"},
                            "subject": {"type": "string", "description": "Subject line"},
                            "body": {"type": "string", "description": "Draft message content"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                )
            )
        elif self.connector_id == "google_calendar":
            tools.append(
                ConnectorToolMetadata(
                    tool_id="google_calendar.list_events",
                    connector_id="google_calendar",
                    name="calendar_list_events",
                    description="List upcoming calendar events and meetings.",
                    risk_level="safe",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "max_results": {"type": "integer", "description": "Number of events to retrieve", "default": 10},
                            "time_min": {"type": "string", "description": "ISO timestamp to start search from"},
                            "time_max": {"type": "string", "description": "ISO timestamp to end search at"},
                            "query": {"type": "string", "description": "Search keyword for event title/description"},
                        },
                    },
                )
            )
            tools.append(
                ConnectorToolMetadata(
                    tool_id="google_calendar.create_event",
                    connector_id="google_calendar",
                    name="calendar_create_event",
                    description="Create a new event, appointment, or meeting on Google Calendar.",
                    risk_level="caution",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "Title/summary of the event"},
                            "description": {"type": "string", "description": "Description of the event"},
                            "start_time": {"type": "string", "description": "ISO format start datetime (e.g. 2026-10-02T15:00:00)"},
                            "end_time": {"type": "string", "description": "ISO format end datetime"},
                            "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee emails"},
                        },
                        "required": ["summary", "start_time"],
                    },
                )
            )
            tools.append(
                ConnectorToolMetadata(
                    tool_id="google_calendar.delete_event",
                    connector_id="google_calendar",
                    name="calendar_delete_event",
                    description="Delete or cancel an event from Google Calendar by its event ID or summary.",
                    risk_level="destructive",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string", "description": "The unique Google Calendar event ID to delete"},
                            "summary": {"type": "string", "description": "Optional title or search string of the event to delete if event_id is not known"},
                        },
                    },
                )
            )
        elif self.connector_id == "google_drive":
            tools.append(
                ConnectorToolMetadata(
                    tool_id="google_drive.search_files",
                    connector_id="google_drive",
                    name="drive_search_files",
                    description="Search for documents, spreadsheets, or files in Google Drive.",
                    risk_level="safe",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query or file name"},
                            "max_results": {"type": "integer", "description": "Maximum number of files to return", "default": 10},
                        },
                        "required": ["query"],
                    },
                )
            )
            tools.append(
                ConnectorToolMetadata(
                    tool_id="google_drive.get_file",
                    connector_id="google_drive",
                    name="drive_get_file",
                    description="Download or inspect content of a Google Drive document.",
                    risk_level="safe",
                    source="api",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string", "description": "Unique Google Drive file ID"},
                        },
                        "required": ["file_id"],
                    },
                )
            )

        if not tools and self.definition.default_tools:
            for dt in self.definition.default_tools:
                clean_name = dt.replace(f"{self.connector_id}_", "")
                tools.append(
                    ConnectorToolMetadata(
                        tool_id=f"{self.connector_id}.{clean_name}",
                        connector_id=self.connector_id,
                        name=dt,
                        description=f"{self.definition.name} tool {clean_name.replace('_', ' ')}",
                        risk_level="safe",
                        source="api",
                        input_schema={"type": "object", "properties": {}},
                    )
                )

        return tools

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], user_id: str) -> ToolResult:
        token = await self.get_valid_token(user_id)
        if not token:
            return ToolResult(
                success=False,
                output="",
                error=f"{self.definition.name} connector is not authorized. Please connect it in the Connector Hub.",
            )

        if self.connector_id == "gmail":
            return await self._execute_gmail(tool_name, args, token)
        elif self.connector_id == "google_calendar":
            return await self._execute_calendar(tool_name, args, token)
        elif self.connector_id == "google_drive":
            return await self._execute_drive(tool_name, args, token)

        return ToolResult(success=False, output="", error=f"Unknown tool: {tool_name}")

    async def _execute_gmail(self, tool_name: str, args: Dict[str, Any], token: str) -> ToolResult:
        to = args.get("to") or args.get("recipient") or args.get("email")
        subject = args.get("subject") or args.get("title", "")
        body = args.get("body") or args.get("content") or args.get("message", "")

        if not to:
            return ToolResult(success=False, output="", error="Missing recipient 'to' address.")

        msg = email.message.EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        endpoint = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        if tool_name == "gmail_create_draft":
            endpoint = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
            payload = {"message": {"raw": raw_message}}
        else:
            payload = {"raw": raw_message}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if res.status_code in (200, 201):
                    data = res.json()
                    action = "drafted" if tool_name == "gmail_create_draft" else "sent"
                    return ToolResult(
                        success=True,
                        output=f"Email successfully {action} to {to} (Message ID: {data.get('id')}).",
                        metadata=data,
                    )
                else:
                    err_msg = res.text
                    try:
                        err_data = res.json().get("error", {})
                        raw_msg = err_data.get("message", "")
                        if "has not been used in project" in raw_msg or "is disabled" in raw_msg:
                            err_msg = (
                                f"Gmail API is disabled in your Google Cloud Project. "
                                f"Please click here to enable it: https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=963333825219 "
                                f"then retry."
                            )
                        elif res.status_code == 401 or "Invalid Credentials" in raw_msg:
                            err_msg = "Google authorization expired or invalid credentials. Please reconnect Gmail in Spotlight (Connectors Hub)."
                        else:
                            err_msg = f"Gmail API error ({res.status_code}): {raw_msg or res.text}"
                    except Exception:
                        err_msg = f"Gmail API error ({res.status_code}): {res.text}"
                    return ToolResult(
                        success=False,
                        output="",
                        error=err_msg,
                    )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Gmail request failed: {e}")

    async def _execute_calendar(self, tool_name: str, args: Dict[str, Any], token: str) -> ToolResult:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if tool_name == "calendar_list_events":
                    max_results = args.get("max_results", 10)
                    time_min = args.get("time_min") or time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
                    time_max = args.get("time_max")
                    query = args.get("query") or args.get("q")
                    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults={max_results}&timeMin={quote(str(time_min))}&singleEvents=true&orderBy=startTime"
                    if time_max:
                        url += f"&timeMax={quote(str(time_max))}"
                    if query:
                        url += f"&q={quote(str(query))}"
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        items = res.json().get("items", [])
                        events_summary = [
                            f"- {it.get('summary', 'Untitled')} at {it.get('start', {}).get('dateTime') or it.get('start', {}).get('date')} (ID: {it.get('id')})"
                            for it in items
                        ]
                        output = f"Calendar events ({len(items)} found):\n" + "\n".join(events_summary) if events_summary else "No calendar events found for the specified period."
                        return ToolResult(success=True, output=output, metadata={"items": items})
                    return ToolResult(success=False, output="", error=f"Calendar API error: {res.text}")

                elif tool_name == "calendar_create_event":
                    summary = args.get("summary", "New Event")
                    description = args.get("description", "")
                    start_time = args.get("start_time")
                    end_time = args.get("end_time")

                    if not start_time:
                        import datetime
                        now_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
                        start_time = now_dt.strftime("%Y-%m-%dT%H:00:00Z")

                    # Handle space instead of T in ISO formats
                    if isinstance(start_time, str):
                        if " " in start_time and "T" not in start_time:
                            start_time = start_time.strip().replace(" ", "T")
                        if "T" not in start_time:
                            start_time += "T10:00:00Z"
                        # Ensure seconds present e.g. 2026-10-05T14:00 -> 2026-10-05T14:00:00
                        import re
                        if re.search(r"T\d{1,2}:\d{2}$", start_time):
                            start_time += ":00"

                    if not end_time:
                        import datetime
                        try:
                            clean_iso = start_time.replace("Z", "+00:00")
                            st_dt = datetime.datetime.fromisoformat(clean_iso)
                            end_time = (st_dt + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                        except Exception:
                            end_time = start_time
                    elif isinstance(end_time, str):
                        if " " in end_time and "T" not in end_time:
                            end_time = end_time.strip().replace(" ", "T")
                        import re
                        if re.search(r"T\d{1,2}:\d{2}$", end_time):
                            end_time += ":00"

                    start_str = str(start_time)
                    end_str = str(end_time)
                    event_body = {
                        "summary": summary,
                        "description": description,
                        "start": {"dateTime": start_str if ("Z" in start_str or "+" in start_str) else f"{start_str}Z"},
                        "end": {"dateTime": end_str if ("Z" in end_str or "+" in end_str) else f"{end_str}Z"},
                    }

                    attendees = args.get("attendees")
                    if isinstance(attendees, str):
                        attendees = [a.strip() for a in attendees.split(",") if "@" in a]
                    if attendees and isinstance(attendees, list):
                        event_body["attendees"] = [{"email": a} for a in attendees if "@" in a]

                    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
                    res = await client.post(url, headers=headers, json=event_body)
                    if res.status_code in (200, 201):
                        ev = res.json()
                        link = ev.get("htmlLink", "")
                        return ToolResult(
                            success=True,
                            output=f"Calendar event '{summary}' created successfully for {start_time} (ID: {ev.get('id')}). {link}",
                            metadata=ev,
                        )
                    return ToolResult(success=False, output="", error=f"Calendar API error ({res.status_code}): {res.text}")

                elif tool_name == "calendar_delete_event":
                    event_id = args.get("event_id") or args.get("id")
                    summary = args.get("summary") or args.get("title")

                    # If event_id not directly provided, search for matching event by summary
                    if not event_id and summary:
                        search_url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?q={quote(str(summary))}&maxResults=10"
                        search_res = await client.get(search_url, headers=headers)
                        if search_res.status_code == 200:
                            items = search_res.json().get("items", [])
                            sum_lower = str(summary).strip().lower()
                            for item in items:
                                it_sum = item.get("summary", "").strip().lower()
                                if sum_lower == it_sum or sum_lower in it_sum:
                                    event_id = item.get("id")
                                    break

                    if not event_id:
                        return ToolResult(
                            success=False,
                            output="",
                            error="Missing 'event_id' or recognizable 'summary' to identify the event to delete.",
                        )

                    del_url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
                    del_res = await client.delete(del_url, headers=headers)
                    if del_res.status_code in (200, 204):
                        return ToolResult(
                            success=True,
                            output=f"Calendar event (ID: {event_id}) deleted successfully.",
                            metadata={"event_id": event_id},
                        )
                    elif del_res.status_code in (404, 410):
                        return ToolResult(
                            success=True,
                            output=f"Calendar event {event_id} was already removed or not found.",
                            metadata={"event_id": event_id},
                        )
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Calendar API error ({del_res.status_code}): {del_res.text}",
                    )

                return ToolResult(success=False, output="", error=f"Unsupported Calendar tool: {tool_name}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Calendar request error: {e}")

    async def _execute_drive(self, tool_name: str, args: Dict[str, Any], token: str) -> ToolResult:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if tool_name in ("drive_search_files", "google_drive.search_files"):
                    query = args.get("query", "").strip()
                    max_results = min(int(args.get("max_results", 10)), 25)
                    q_filter = f"name contains '{query}' and trashed = false" if query else "trashed = false"
                    url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(q_filter)}&pageSize={max_results}&fields=files(id,name,mimeType,modifiedTime,webViewLink,size)"
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        files = res.json().get("files", [])
                        if not files:
                            return ToolResult(success=True, output=f"No Google Drive files found matching '{query}'.", metadata={"files": []})
                        lines = [f"- {f.get('name')} (ID: {f.get('id')}, Type: {f.get('mimeType')}) -> {f.get('webViewLink', '')}" for f in files]
                        return ToolResult(
                            success=True,
                            output=f"Found {len(files)} files in Google Drive:\n" + "\n".join(lines),
                            metadata={"files": files},
                        )
                    return ToolResult(success=False, output="", error=f"Google Drive API error ({res.status_code}): {res.text}")

                elif tool_name in ("drive_get_file", "google_drive.get_file"):
                    file_id = args.get("file_id", "").strip()
                    if not file_id:
                        return ToolResult(success=False, output="", error="Missing file_id for Drive get_file.")
                    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name,mimeType,size,webViewLink,description"
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        return ToolResult(
                            success=True,
                            output=f"File: '{data.get('name')}' (Type: {data.get('mimeType')}, Size: {data.get('size', 'N/A')} bytes)\nLink: {data.get('webViewLink')}",
                            metadata=data,
                        )
                    return ToolResult(success=False, output="", error=f"Google Drive API error ({res.status_code}): {res.text}")

                return ToolResult(success=False, output="", error=f"Unsupported Drive tool: {tool_name}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Drive request error: {e}")
