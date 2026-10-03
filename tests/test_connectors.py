"""
Unit tests for the NEXUS Connectors System.
Tests catalog, credentials store, connector manager, tool registry integration,
adapters, and API endpoints.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from backend.main import app
from backend.connectors.catalog import CONNECTOR_CATALOG, get_catalog_entry, list_all_definitions
from backend.connectors.credentials_store import CredentialsStore
from backend.connectors.models import ConnectorType, ConnectorStatus, AuthType
from backend.connectors.manager import ConnectorManager
from backend.agent.tools.registry import ToolRegistry
from backend.core.permissions import permission_engine
from backend.connectors.adapters.google import GoogleAPIAdapter


def test_connector_catalog():
    """Verify that catalog defines all required connectors with proper metadata."""
    defs = list_all_definitions()
    ids = [d.id for d in defs]
    assert "gmail" in ids
    assert "google_calendar" in ids
    assert "github" in ids
    assert "spotify" in ids
    assert "filesystem" in ids

    gmail = get_catalog_entry("gmail")
    assert gmail is not None
    assert gmail.type == ConnectorType.API
    assert "https://www.googleapis.com/auth/gmail.send" in gmail.required_scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in gmail.required_scopes
    assert "gmail_list_messages" in gmail.default_tools

    github = get_catalog_entry("github")
    assert github is not None
    assert github.type == ConnectorType.MCP


def test_credentials_store(tmp_path):
    """Ensure credentials store securely stores and deletes credentials."""
    cred_file = tmp_path / "test_creds.json"
    store = CredentialsStore(file_path=cred_file)

    store.save_credential(
        "test_user",
        "github",
        {"access_token": "ghp_secret_token_12345", "account": "octocat"},
    )

    # Retrieval of full credentials
    full = store.get_credential("test_user", "github")
    assert full is not None
    assert full["access_token"] == "ghp_secret_token_12345"

    # Delete
    assert store.delete_credential("test_user", "github") is True
    assert store.get_credential("test_user", "github") is None


@pytest.mark.asyncio
async def test_connector_manager_filesystem_tools():
    """Test connector manager initializes filesystem and registers tools in registry."""
    mgr = ConnectorManager()
    await mgr.initialize("test_user")

    connectors = await mgr.list_connectors("test_user")
    fs = next((c for c in connectors if c.id == "filesystem"), None)
    assert fs is not None
    assert fs.status == ConnectorStatus.CONNECTED
    assert len(fs.discovered_tools) >= 2

    # Check planner prompt additions
    prompt_additions = mgr.get_tool_prompt_additions()
    assert "filesystem" in prompt_additions
    assert "read_file" in prompt_additions


def test_connectors_api_endpoints():
    """Test /api/connectors FastAPI endpoints."""
    client = TestClient(app)

    # List connectors
    res = client.get("/api/connectors")
    assert res.status_code == 200
    data = res.json()
    assert "connectors" in data
    c_ids = [c["id"] for c in data["connectors"]]
    assert "gmail" in c_ids
    assert "github" in c_ids
    assert "filesystem" in c_ids

    # Detail
    res_fs = client.get("/api/connectors/filesystem")
    assert res_fs.status_code == 200
    assert res_fs.json()["connector"]["id"] == "filesystem"

    # Google Auth URL
    res_url = client.get("/api/connectors/google/auth-url?connector_id=gmail")
    assert res_url.status_code == 200
    auth_data = res_url.json()
    assert "url" in auth_data
    assert "accounts.google.com" in auth_data["url"]
    assert "gmail.send" in auth_data["url"]


@pytest.mark.asyncio
async def test_gmail_list_messages_reads_metadata_without_sending(monkeypatch):
    adapter = GoogleAPIAdapter(get_catalog_entry("gmail"))
    calls = []

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append((url, params))
            if url.endswith("/messages"):
                return FakeResponse({"messages": [{"id": "message-1"}]})
            return FakeResponse({
                "id": "message-1",
                "snippet": "A recent inbox message",
                "payload": {"headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Project update"},
                    {"name": "Date", "value": "Sat, 03 Oct 2026 10:00:00 +0000"},
                ]},
            })

        async def post(self, *args, **kwargs):
            raise AssertionError("Reading Gmail must not issue a POST request")

    monkeypatch.setattr("backend.connectors.adapters.google.httpx.AsyncClient", lambda **kwargs: FakeClient())
    result = await adapter._execute_gmail("gmail_list_messages", {"max_results": 1}, "test-token")

    assert result.success is True
    assert result.metadata["count"] == 1
    assert result.metadata["messages"][0]["subject"] == "Project update"
    assert calls[0][1] == {"q": "in:inbox", "maxResults": 1}
    assert calls[1][1][0] == ("format", "metadata")


@pytest.mark.asyncio
async def test_gmail_brief_uses_metadata_and_builds_a_compact_read_only_list(monkeypatch):
    adapter = GoogleAPIAdapter(get_catalog_entry("gmail"))
    calls = []

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append((url, params))
            if url.endswith("/messages"):
                return FakeResponse({"messages": [{"id": "message-2"}], "resultSizeEstimate": 1})
            return FakeResponse({
                "id": "message-2",
                "snippet": "Meeting moved to Friday. https://calendar.example.com/event/42",
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": "TWVldGluZyBtb3ZlZCB0byBGcmlkYXku"},
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Schedule change"},
                        {"name": "Date", "value": "Sat, 03 Oct 2026 10:00:00 +0000"},
                    ],
                },
            })

        async def post(self, *args, **kwargs):
            raise AssertionError("Summarizing Gmail must not issue a POST request")

    monkeypatch.setattr("backend.connectors.adapters.google.httpx.AsyncClient", lambda **kwargs: FakeClient())

    result = await adapter._execute_gmail("gmail_brief_messages", {"max_results": 1}, "test-token")

    assert result.success is True
    assert "## New email brief" in result.output
    assert "Schedule change" in result.output
    assert "ID: `message-2`" in result.output
    assert "[Open in Gmail](https://mail.google.com/mail/u/0/#all/message-2)" in result.output
    assert "[Open link](https://calendar.example.com/event/42)" in result.output
    assert calls[0][1]["q"] == "-from:me"
    assert calls[1][1] == [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")]


def test_permission_gate_integration():
    """Verify that permission engine properly evaluates connector tools."""
    risk, requires_approval = permission_engine.evaluate_step(
        "filesystem.read_file", {"path": "test.txt"}
    )
    # Read files is classified as safe / read_only
    assert not requires_approval

    risk_write, requires_approval_write = permission_engine.evaluate_step(
        "filesystem.write_file", {"path": "test.txt", "content": "hello"}
    )
    # Modifying files evaluates according to permission policies
    assert risk_write is not None


def test_google_connect_with_token(tmp_path, monkeypatch):
    """Verify that token payload from browser OAuth connects Google service without touching real creds."""
    from backend.connectors.credentials_store import CredentialsStore
    test_store = CredentialsStore(file_path=tmp_path / "isolated_creds.json")
    monkeypatch.setattr("backend.connectors.credentials_store.credentials_store", test_store)
    monkeypatch.setattr("backend.connectors.manager.credentials_store", test_store)
    monkeypatch.setattr("backend.connectors.adapters.google.credentials_store", test_store)

    client = TestClient(app)
    res = client.post(
        "/api/connectors/gmail/connect",
        json={
            "tokens": {
                "access_token": "ya29.test_token_sample",
                "account_identifier": "testuser@gmail.com",
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["connector"]["status"] == "connected"
    assert data["connector"]["account_identifier"] == "testuser@gmail.com"


@pytest.mark.asyncio
async def test_spotify_play_stops_when_search_rejects_access_token(monkeypatch):
    from backend.connectors.adapters.direct_api import DirectAPIAdapter

    adapter = DirectAPIAdapter(get_catalog_entry("spotify"))
    response = MagicMock(status_code=401, text='{"error":{"status":401}}')
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.put = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("backend.connectors.adapters.direct_api.credentials_store.get_credential", lambda *_: {"token": "expired"})
    with patch("backend.connectors.adapters.direct_api.httpx.AsyncClient", return_value=context):
        result = await adapter.execute_tool(
            "spotify_play_track",
            {"query": "Bohemian Rhapsody"},
            "test_user",
        )

    assert not result.success
    assert "short-lived OAuth bearer token" in result.error
    client.put.assert_not_awaited()


def test_spotify_auth_url_uses_pkce_without_client_secret(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from backend.connectors.adapters.direct_api import DirectAPIAdapter

    monkeypatch.setattr("backend.connectors.adapters.direct_api.get_spotify_client_id", lambda: "spotify-client-id")
    adapter = DirectAPIAdapter(get_catalog_entry("spotify"))
    url = adapter.get_spotify_auth_url("state-value", "challenge-value", "http://127.0.0.1:8000/api/connectors/spotify/callback")
    params = parse_qs(urlparse(url).query)

    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == ["challenge-value"]
    assert "user-modify-playback-state" in params["scope"][0]
    assert "client_secret" not in params


def test_spotify_403_preserves_provider_policy_reason():
    from backend.connectors.adapters.direct_api import _spotify_api_error

    message = _spotify_api_error(
        403,
        "search",
        "Active premium subscription required for the owner of the app.",
    )

    assert "Active premium subscription required" in message


def test_connector_auth_denial_is_not_reframed_as_automation(monkeypatch):
    from types import SimpleNamespace
    from backend.agent.nodes.executor import _is_terminal_connector_auth_error

    monkeypatch.setattr(
        "backend.agent.nodes.executor.tool_registry.get",
        lambda action: SimpleNamespace(connector_id="spotify") if action.startswith("spotify_") else None,
    )

    assert _is_terminal_connector_auth_error("spotify_play_track", "Spotify search forbidden (403)")
    assert not _is_terminal_connector_auth_error("browser_click", "Browser click failed (403)")


def test_log_redaction_masks_api_keys_tokens_and_bearer_values():
    import logging
    from backend.core.logging_security import SecretRedactionFilter, redact_secrets

    message = (
        "HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/models/generateContent?key=AIzaSecretValue123&alt=sse "
        "GET https://oauth2.googleapis.com/tokeninfo?access_token=ya29.SecretValue123 "
        "Authorization: Bearer gsk_secret_value123 GEMMA_API_KEY=AQ.secret_value123"
    )

    redacted = redact_secrets(message)

    assert "AIzaSecretValue123" not in redacted
    assert "ya29.SecretValue123" not in redacted
    assert "gsk_secret_value123" not in redacted
    assert "AQ.secret_value123" not in redacted
    assert redacted.count("[REDACTED]") >= 4

    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        "",
        0,
        "HTTP Request: GET %s",
        ("https://oauth2.googleapis.com/tokeninfo?access_token=ya29.SecretValue123",),
        None,
    )
    SecretRedactionFilter().filter(record)
    assert "ya29.SecretValue123" not in record.getMessage()


@pytest.mark.asyncio
async def test_spotify_refresh_renews_and_persists_access_token(monkeypatch):
    from backend.connectors.adapters.direct_api import DirectAPIAdapter

    creds = {
        "access_token": "expired-access-token",
        "refresh_token": "persistent-refresh-token",
        "expires_at": 1,
    }
    store = MagicMock()
    store.get_credential.return_value = creds
    store.save_credential = MagicMock()
    monkeypatch.setattr("backend.connectors.adapters.direct_api.credentials_store", store)
    monkeypatch.setattr("backend.connectors.adapters.direct_api.get_spotify_client_id", lambda: "spotify-client-id")

    response = MagicMock(status_code=200)
    response.json.return_value = {
        "access_token": "new-access-token",
        "refresh_token": "rotated-refresh-token",
        "expires_in": 3600,
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch("backend.connectors.adapters.direct_api.httpx.AsyncClient", return_value=context):
        token = await DirectAPIAdapter(get_catalog_entry("spotify")).get_valid_spotify_token("test_user")

    assert token == "new-access-token"
    saved_creds = store.save_credential.call_args.args[2]
    assert saved_creds["refresh_token"] == "rotated-refresh-token"
    assert saved_creds["access_token"] == "new-access-token"


def test_spotify_oauth_callback_consumes_pkce_state(monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from backend.connectors.adapters.direct_api import DirectAPIAdapter
    from backend.connectors.manager import connector_manager
    from backend.api import connectors as connectors_api

    monkeypatch.setattr("backend.connectors.adapters.direct_api.get_spotify_client_id", lambda: "spotify-client-id")
    client = TestClient(app)
    auth_response = client.get("/api/connectors/spotify/auth-url")
    assert auth_response.status_code == 200
    params = parse_qs(urlparse(auth_response.json()["url"]).query)
    state = params["state"][0]
    assert state in connectors_api._spotify_oauth_sessions

    adapter = connector_manager.get_adapter("spotify")
    assert isinstance(adapter, DirectAPIAdapter)
    exchange = AsyncMock(return_value={
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
        "scope": "user-modify-playback-state",
    })
    monkeypatch.setattr(adapter, "exchange_spotify_code", exchange)
    connect = AsyncMock()
    monkeypatch.setattr(connector_manager, "connect", connect)

    callback = client.get("/api/connectors/spotify/callback", params={"code": "auth-code", "state": state})
    assert callback.status_code == 200
    assert "Spotify connected" in callback.text
    exchange.assert_awaited_once()
    assert connect.await_args.args[1]["refresh_token"] == "refresh-token"
    assert state not in connectors_api._spotify_oauth_sessions
