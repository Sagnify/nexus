"""
Connectors API Router for NEXUS.
Provides endpoints for connector discovery, connection, disconnection, health checks,
and Google OAuth authorization.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from backend.connectors.adapters.google import GoogleAPIAdapter
from backend.connectors.adapters.direct_api import DirectAPIAdapter
from backend.connectors.manager import connector_manager
from backend.core.firebase_auth import get_current_user_optional

logger = logging.getLogger("nexus.api.connectors")

router = APIRouter()
_spotify_oauth_sessions: Dict[str, Dict[str, Any]] = {}
SPOTIFY_REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8000/api/connectors/spotify/callback",
)


class ConnectPayload(BaseModel):
    model_config = {"extra": "allow"}
    token: Optional[str] = None
    access_token: Optional[str] = None
    tokens: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    code: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    extra: Optional[Dict[str, Any]] = None


def _extract_user_id(current_user: Any) -> str:
    if not current_user:
        return "default"
    if isinstance(current_user, dict):
        return current_user.get("uid") or current_user.get("id") or "default"
    return str(getattr(current_user, "firebase_uid", None) or getattr(current_user, "id", "default"))


@router.get("")
async def list_connectors(current_user: Optional[Any] = Depends(get_current_user_optional)):
    """List all connectors with connection status and capabilities."""
    user_id = _extract_user_id(current_user)
    await connector_manager.initialize_connected_tools(user_id)
    connectors = await connector_manager.list_connectors(user_id)
    return {"connectors": [c.model_dump() for c in connectors]}


@router.get("/google/auth-url")
async def get_google_auth_url(
    connector_id: str = Query("gmail", description="gmail or google_calendar"),
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    """Generate scoped Google OAuth consent URL for Gmail or Google Calendar."""
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter(connector_id)
    if not isinstance(adapter, GoogleAPIAdapter):
        raise HTTPException(status_code=400, detail=f"Connector '{connector_id}' is not a Google API connector.")

    url = adapter.get_auth_url(user_id)
    return {"url": url, "connector_id": connector_id}


@router.get("/spotify/auth-url")
async def get_spotify_auth_url(current_user: Optional[Any] = Depends(get_current_user_optional)):
    """Create a short-lived PKCE session and return Spotify's authorization URL."""
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter("spotify")
    if not isinstance(adapter, DirectAPIAdapter):
        raise HTTPException(status_code=500, detail="Spotify connector is unavailable.")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    now = time.time()
    for old_state, session in list(_spotify_oauth_sessions.items()):
        if session["expires_at"] <= now:
            _spotify_oauth_sessions.pop(old_state, None)
    _spotify_oauth_sessions[state] = {
        "user_id": user_id,
        "verifier": verifier,
        "expires_at": now + 600,
    }
    try:
        return {"url": adapter.get_spotify_auth_url(state, challenge, SPOTIFY_REDIRECT_URI)}
    except ValueError as exc:
        _spotify_oauth_sessions.pop(state, None)
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/spotify/callback", response_class=HTMLResponse)
async def handle_spotify_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Validate the one-time PKCE state, exchange Spotify's code, and store refresh credentials."""
    session = _spotify_oauth_sessions.pop(state, None) if state else None
    if not session or session["expires_at"] <= time.time():
        return HTMLResponse("Spotify authorization expired or state was invalid. Return to NEXUS and try again.", status_code=400)
    if error or not code:
        return HTMLResponse("Spotify authorization was cancelled. Return to NEXUS to try again.", status_code=400)

    adapter = connector_manager.get_adapter("spotify")
    if not isinstance(adapter, DirectAPIAdapter):
        return HTMLResponse("Spotify connector is unavailable. Return to NEXUS and try again.", status_code=500)
    try:
        tokens = await adapter.exchange_spotify_code(code, session["verifier"], SPOTIFY_REDIRECT_URI)
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            raise RuntimeError("Spotify did not return renewable OAuth credentials.")
        await connector_manager.connect(
            "spotify",
            {
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "expires_in": tokens.get("expires_in", 3600),
                "scope": tokens.get("scope", ""),
            },
            session["user_id"],
        )
    except Exception as exc:
        logger.warning("Spotify OAuth callback failed: %s", exc)
        return HTMLResponse("Spotify could not authorize NEXUS. Check the app settings and try again.", status_code=400)

    return HTMLResponse(
        "<!doctype html><html><body style='font-family:system-ui;background:#121212;color:white;display:grid;place-items:center;height:100vh'>"
        "<main><h2>Spotify connected</h2><p>Return to NEXUS. Your access will renew automatically.</p></main></body></html>"
    )



@router.get("/google/callback", response_class=HTMLResponse)
async def handle_google_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Browser landing endpoint after Google OAuth consent."""
    if error or not code:
        err_msg = error or "Authorization code missing"
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>NEXUS - Authorization Failed</title>
            <style>
              body {{ background: #0a0b0f; color: #f87171; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
              .card {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(239,68,68,0.3); border-radius: 16px; padding: 36px 48px; text-align: center; max-width: 440px; }}
            </style></head>
            <body>
              <div class="card">
                <h2>Authorization Cancelled or Failed</h2>
                <p style="color:rgba(255,255,255,0.6);">{err_msg}</p>
                <p style="font-size:12px;color:rgba(255,255,255,0.4);margin-top:24px;">You can close this tab and return to NEXUS.</p>
              </div>
            </body>
            </html>
            """,
            status_code=400,
        )

    # Decode state
    connector_id = "gmail"
    user_id = "default"
    if state:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(state).decode())
            connector_id = decoded.get("connector_id", "gmail")
            user_id = decoded.get("user_id", "default")
        except Exception:
            pass

    # Perform token exchange
    try:
        res = await connector_manager.connect(
            connector_id=connector_id,
            auth_payload={"code": code},
            user_id=user_id,
        )
        service_name = res.name
    except Exception as exc:
        logger.error(f"Error during OAuth callback exchange: {exc}")
        service_name = "Google Service"

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
          <title>NEXUS - Connected</title>
          <style>
            body {{ background: #0a0b0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
            .card {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(56,189,248,0.3); border-radius: 16px; padding: 40px 52px; text-align: center; max-width: 460px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); }}
            .icon {{ width: 48px; height: 48px; border-radius: 50%; background: rgba(52,211,153,0.15); color: #34d399; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px; font-size: 24px; }}
            h2 {{ margin: 0 0 8px; font-size: 20px; font-weight: 600; color: #fff; }}
            p {{ color: rgba(255,255,255,0.65); font-size: 13.5px; line-height: 1.5; margin: 0 0 20px; }}
            .hint {{ font-size: 11.5px; color: rgba(255,255,255,0.35); }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="icon">✓</div>
            <h2>{service_name} Connected</h2>
            <p>NEXUS has been successfully authorized with official Google APIs.</p>
            <div class="hint">You can close this window now. Return to NEXUS to start using your connector.</div>
          </div>
        </body>
        </html>
        """
    )


class CreateCalendarEventPayload(BaseModel):
    summary: str
    description: Optional[str] = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    attendees: Optional[Any] = None


@router.get("/calendar/events")
async def list_calendar_events(
    max_results: int = Query(20, ge=1, le=100),
    query: Optional[str] = Query(None),
    time_min: Optional[str] = Query(None),
    time_max: Optional[str] = Query(None),
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    """Retrieve upcoming events from Google Calendar connector with optional date window filtering."""
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter("google_calendar")
    if not adapter or not isinstance(adapter, GoogleAPIAdapter):
        return {"connected": False, "events": [], "message": "Google Calendar adapter unavailable"}

    token = await adapter.get_valid_token(user_id)
    if not token and user_id != "local_default_user":
        token = await adapter.get_valid_token("local_default_user") or await adapter.get_valid_token("default")
        if token:
            user_id = "local_default_user"

    if not token:
        return {"connected": False, "events": [], "message": "Google Calendar not authorized"}

    args: dict[str, Any] = {"max_results": max_results}
    if query:
        args["query"] = query
    if time_min:
        args["time_min"] = time_min
    if time_max:
        args["time_max"] = time_max
    res = await adapter.execute_tool("calendar_list_events", args, user_id)
    if res.success:
        items = res.metadata.get("items", []) if res.metadata else []
        return {
            "connected": True,
            "events": items,
            "summary": res.output,
        }
    return {
        "connected": True,
        "events": [],
        "error": res.error or "Failed to list events",
    }


@router.post("/calendar/events")
async def create_calendar_event(
    payload: CreateCalendarEventPayload,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    """Create a new event on Google Calendar."""
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter("google_calendar")
    if not adapter or not isinstance(adapter, GoogleAPIAdapter):
        raise HTTPException(status_code=503, detail="Google Calendar adapter unavailable")

    token = await adapter.get_valid_token(user_id)
    if not token and user_id != "local_default_user":
        token = await adapter.get_valid_token("local_default_user") or await adapter.get_valid_token("default")
        if token:
            user_id = "local_default_user"

    if not token:
        raise HTTPException(status_code=401, detail="Google Calendar not authorized")

    args = payload.model_dump(exclude_none=True)
    res = await adapter.execute_tool("calendar_create_event", args, user_id)
    if res.success:
        return {"status": "success", "event": res.metadata, "message": res.output}
    raise HTTPException(status_code=400, detail=res.error or "Failed to create event")


@router.delete("/calendar/events/{event_id}")
async def delete_calendar_event(
    event_id: str,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    """Delete an event on Google Calendar."""
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter("google_calendar")
    if not adapter or not isinstance(adapter, GoogleAPIAdapter):
        raise HTTPException(status_code=503, detail="Google Calendar adapter unavailable")

    token = await adapter.get_valid_token(user_id)
    if not token and user_id != "local_default_user":
        token = await adapter.get_valid_token("local_default_user") or await adapter.get_valid_token("default")
        if token:
            user_id = "local_default_user"

    if not token:
        raise HTTPException(status_code=401, detail="Google Calendar not authorized")

    res = await adapter.execute_tool("calendar_delete_event", {"event_id": event_id}, user_id)
    if res.success:
        return {"status": "success", "event_id": event_id, "message": res.output}
    raise HTTPException(status_code=400, detail=res.error or "Failed to delete event")


@router.get("/{connector_id}")
async def get_connector_detail(
    connector_id: str,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    user_id = _extract_user_id(current_user)
    try:
        state = await connector_manager.get_connector_state(connector_id, user_id)
        return {"connector": state.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{connector_id}/connect")
async def connect_connector(
    connector_id: str,
    payload: ConnectPayload,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    user_id = _extract_user_id(current_user)
    auth_data = payload.model_dump(exclude_unset=True)
    try:
        state = await connector_manager.connect(connector_id, auth_data, user_id)
        return {"status": "success", "connector": state.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error connecting {connector_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connector_id}/disconnect")
async def disconnect_connector(
    connector_id: str,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    user_id = _extract_user_id(current_user)
    try:
        state = await connector_manager.disconnect(connector_id, user_id)
        return {"status": "success", "connector": state.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{connector_id}/health")
async def check_connector_health(
    connector_id: str,
    current_user: Optional[Any] = Depends(get_current_user_optional),
):
    user_id = _extract_user_id(current_user)
    adapter = connector_manager.get_adapter(connector_id)
    if not adapter:
        raise HTTPException(status_code=404, detail="Connector not found")
    status = await adapter.health_check(user_id)
    return {"connector_id": connector_id, "status": status.value}

