"""
Robust Unit and Integration Test Suite for NEXUS Google Calendar Integration.
Tests catalog, adapter, discovery, execution, planner parameter extraction,
and live/mocked API operations.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.connectors.catalog import get_connector_definition, list_all_definitions
from backend.connectors.adapters.google import GoogleAPIAdapter
from backend.connectors.models import ConnectorType, ConnectorStatus
from backend.connectors.manager import ConnectorManager
from backend.agent.tools.registry import tool_registry
from backend.agent.nodes.planner import planner_node


# ── 1. Catalog Definition Tests ──────────────────────────────────────────────

def test_calendar_catalog_definition():
    """Verify Google Calendar definition in connector catalog."""
    defn = get_connector_definition("google_calendar")
    assert defn is not None
    assert defn.id == "google_calendar"
    assert defn.type == ConnectorType.API
    assert "https://www.googleapis.com/auth/calendar.events" in defn.required_scopes
    assert "https://www.googleapis.com/auth/calendar.readonly" in defn.required_scopes
    assert "calendar_list_events" in defn.default_tools
    assert "calendar_create_event" in defn.default_tools
    assert "calendar_delete_event" in defn.default_tools


# ── 2. Tool Discovery Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_tool_discovery():
    """Verify Google Calendar adapter discovers list, create, and delete tools."""
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)
    tools = await adapter.discover_tools("test_user")

    tool_names = [t.name for t in tools]
    assert "calendar_list_events" in tool_names
    assert "calendar_create_event" in tool_names
    assert "calendar_delete_event" in tool_names

    list_tool = next(t for t in tools if t.name == "calendar_list_events")
    assert list_tool.risk_level == "safe"

    create_tool = next(t for t in tools if t.name == "calendar_create_event")
    assert create_tool.risk_level == "caution"
    assert "summary" in create_tool.input_schema["properties"]
    assert "start_time" in create_tool.input_schema["properties"]

    delete_tool = next(t for t in tools if t.name == "calendar_delete_event")
    assert delete_tool.risk_level == "destructive"
    assert "event_id" in delete_tool.input_schema["properties"]


# ── 3. Adapter Execution Unit Tests (Mocked API) ─────────────────────────────

@pytest.mark.asyncio
async def test_adapter_calendar_list_events_mocked(monkeypatch):
    """Test calendar_list_events with mock HTTP response."""
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)

    monkeypatch.setattr(adapter, "get_valid_token", AsyncMock(return_value="mock_access_token"))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "id": "event_123",
                "summary": "Engineering Sync",
                "start": {"dateTime": "2026-10-05T10:00:00Z"},
            },
            {
                "id": "event_456",
                "summary": "Product Review",
                "start": {"dateTime": "2026-10-05T14:00:00Z"},
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.connectors.adapters.google.httpx.AsyncClient", return_value=mock_client_ctx):
        res = await adapter.execute_tool(
            "calendar_list_events",
            {"max_results": 5, "query": "Sync"},
            "test_user"
        )

    assert res.success is True
    assert "Engineering Sync" in res.output
    assert "Product Review" in res.output
    assert "event_123" in res.output
    assert len(res.metadata["items"]) == 2


@pytest.mark.asyncio
async def test_adapter_calendar_create_event_mocked(monkeypatch):
    """Test calendar_create_event formatting and HTTP post with mock."""
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)

    monkeypatch.setattr(adapter, "get_valid_token", AsyncMock(return_value="mock_access_token"))

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "new_created_event_id",
        "summary": "Sprint Planning",
        "htmlLink": "https://www.google.com/calendar/event?eid=mock_eid",
    }

    captured_payload = {}

    async def mock_post(url, headers=None, json=None):
        nonlocal captured_payload
        captured_payload = json
        return mock_resp

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=mock_post)
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.connectors.adapters.google.httpx.AsyncClient", return_value=mock_client_ctx):
        res = await adapter.execute_tool(
            "calendar_create_event",
            {
                "summary": "Sprint Planning",
                "description": "Weekly sprint planning meeting",
                "start_time": "2026-10-06 15:00:00",
                "end_time": "2026-10-06 16:00:00",
                "attendees": "dev1@example.com, dev2@example.com",
            },
            "test_user"
        )

    assert res.success is True
    assert "Sprint Planning" in res.output
    assert "new_created_event_id" in res.output
    assert captured_payload["summary"] == "Sprint Planning"
    assert "2026-10-06T15:00:00Z" in captured_payload["start"]["dateTime"]
    assert "2026-10-06T16:00:00Z" in captured_payload["end"]["dateTime"]
    assert len(captured_payload["attendees"]) == 2
    assert captured_payload["attendees"][0]["email"] == "dev1@example.com"


@pytest.mark.asyncio
async def test_adapter_calendar_delete_event_mocked(monkeypatch):
    """Test calendar_delete_event by event_id with mock HTTP delete."""
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)

    monkeypatch.setattr(adapter, "get_valid_token", AsyncMock(return_value="mock_access_token"))

    mock_resp = MagicMock()
    mock_resp.status_code = 204

    mock_client = MagicMock()
    mock_client.delete = AsyncMock(return_value=mock_resp)
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.connectors.adapters.google.httpx.AsyncClient", return_value=mock_client_ctx):
        res = await adapter.execute_tool(
            "calendar_delete_event",
            {"event_id": "event_to_delete_999"},
            "test_user"
        )

    assert res.success is True
    assert "event_to_delete_999" in res.output
    assert res.metadata["event_id"] == "event_to_delete_999"


@pytest.mark.asyncio
async def test_adapter_calendar_unauthorized():
    """Verify tool execution fails gracefully when connector is not authorized."""
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)

    with patch.object(adapter, "get_valid_token", AsyncMock(return_value=None)):
        res = await adapter.execute_tool("calendar_list_events", {}, "unauth_user")
        assert res.success is False
        assert "not authorized" in res.error


# ── 4. Planner Parameter Extraction & Routing Tests ──────────────────────────

@pytest.mark.asyncio
async def test_planner_creates_event_plan():
    """Test that event scheduling prompt generates calendar_create_event plan with extracted fields."""
    state = {
        "user_input": 'Schedule a meeting called "Design Critique" tomorrow at 3pm with sarah@example.com',
        "user_id": "local_default_user",
    }
    result = await planner_node(state)
    assert result is not None
    plan = result.get("plan", [])
    assert len(plan) == 1
    step = plan[0]
    assert step["tool"] == "calendar_create_event"
    assert step["args"]["summary"] == "Design Critique"
    assert "15:00:00" in step["args"]["start_time"]
    assert "16:00:00" in step["args"]["end_time"]
    assert "sarah@example.com" in step["args"]["attendees"]


@pytest.mark.asyncio
async def test_planner_lists_events_plan():
    """Test that listing calendar query routes to calendar_list_events."""
    state = {
        "user_input": "Show my upcoming calendar events for today",
        "user_id": "local_default_user",
    }
    result = await planner_node(state)
    assert result is not None
    plan = result.get("plan", [])
    assert len(plan) == 1
    assert plan[0]["tool"] == "calendar_list_events"
    assert plan[0]["args"]["max_results"] == 10
    assert "time_min" in plan[0]["args"]
    assert "time_max" in plan[0]["args"]


@pytest.mark.asyncio
async def test_planner_searches_events_plan():
    """Test that calendar search query routes to calendar_list_events with query arg."""
    state = {
        "user_input": 'Search my calendar for "Autonomous Sync"',
        "user_id": "local_default_user",
    }
    result = await planner_node(state)
    assert result is not None
    plan = result.get("plan", [])
    assert len(plan) == 1
    assert plan[0]["tool"] == "calendar_list_events"
    assert plan[0]["args"]["query"] == "Autonomous Sync"


@pytest.mark.asyncio
async def test_planner_cancels_event_plan():
    """Test that calendar cancellation routes to calendar_delete_event."""
    state = {
        "user_input": 'Cancel calendar event called "Design Critique"',
        "user_id": "local_default_user",
    }
    result = await planner_node(state)
    assert result is not None
    plan = result.get("plan", [])
    assert len(plan) == 1
    assert plan[0]["tool"] == "calendar_delete_event"
    assert plan[0]["args"]["summary"] == "Design Critique"


# ── 5. End-to-End Live Google Calendar API Integration Test ──────────────────

@pytest.mark.asyncio
async def test_live_google_calendar_lifecycle():
    """
    Live end-to-end integration test with real Google Calendar API credentials.
    Performs full lifecycle:
    1. Create an event 'NEXUS Automated Verification Test'
    2. Search and list events to confirm it was registered
    3. Delete the event using calendar_delete_event
    4. Confirm it is no longer listed
    """
    defn = get_connector_definition("google_calendar")
    adapter = GoogleAPIAdapter(defn)

    # Check if live token is available for local_default_user
    token = await adapter.get_valid_token("local_default_user")
    if not token:
        pytest.skip("Live Google Calendar credentials not available, skipping live test.")

    test_title = "NEXUS Automated Verification Test"
    import datetime
    now_utc = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    start_iso = now_utc.strftime("%Y-%m-%dT10:00:00Z")
    end_iso = now_utc.strftime("%Y-%m-%dT11:00:00Z")

    # Step 1: Create event
    create_res = await adapter.execute_tool(
        "calendar_create_event",
        {
            "summary": test_title,
            "description": "Created by automated integration test",
            "start_time": start_iso,
            "end_time": end_iso,
        },
        "local_default_user",
    )
    assert create_res.success is True, f"Failed to create event: {create_res.error}"
    event_id = create_res.metadata.get("id")
    assert event_id is not None, "Created event metadata missing id"

    try:
        # Step 2: List / Query events
        list_res = await adapter.execute_tool(
            "calendar_list_events",
            {"query": test_title, "max_results": 5},
            "local_default_user",
        )
        assert list_res.success is True, f"Failed to list events: {list_res.error}"
        found_ids = [it.get("id") for it in list_res.metadata.get("items", [])]
        assert event_id in found_ids, f"Created event {event_id} not found in search results"

    finally:
        # Step 3: Delete event (cleanup)
        del_res = await adapter.execute_tool(
            "calendar_delete_event",
            {"event_id": event_id},
            "local_default_user",
        )
        assert del_res.success is True, f"Failed to delete event: {del_res.error}"

    # Step 4: Verify deletion
    verify_res = await adapter.execute_tool(
        "calendar_list_events",
        {"query": test_title, "max_results": 5},
        "local_default_user",
    )
    assert verify_res.success is True
    post_del_ids = [it.get("id") for it in verify_res.metadata.get("items", [])]
    assert event_id not in post_del_ids, f"Event {event_id} still found after deletion"
