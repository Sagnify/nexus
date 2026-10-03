"""
NEXUS Connector Catalog.
Defines all officially supported external application connectors with their configuration,
metadata, transport protocols, and authentication requirements.
"""
from __future__ import annotations
from typing import Dict, List, Optional
from backend.connectors.models import (
    AuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorType,
)

CATALOG: Dict[str, ConnectorDefinition] = {
    # ── 1. Google Gmail (Google API) ──────────────────────────────────────────
    "gmail": ConnectorDefinition(
        id="gmail",
        name="Gmail",
        description="Read inbox messages, send emails, and create drafts through the official Gmail API.",
        category=ConnectorCategory.COMMUNICATION,
        type=ConnectorType.API,
        icon="Mail",
        auth_type=AuthType.GOOGLE_OAUTH,
        required_scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        auth_instructions="Authorize NEXUS to read inbox messages, send emails, and create drafts.",
        capabilities=[
            "Read inbox messages",
            "Send emails",
            "Draft messages",
            "Template mail composition",
        ],
        default_tools=["gmail_list_messages", "gmail_brief_messages", "gmail_send_email", "gmail_create_draft"],
    ),

    # ── 2. Google Calendar (Google API) ───────────────────────────────────────
    "google_calendar": ConnectorDefinition(
        id="google_calendar",
        name="Google Calendar",
        description="Schedule, view, and organize meetings and calendar events.",
        category=ConnectorCategory.PRODUCTIVITY,
        type=ConnectorType.API,
        icon="Calendar",
        auth_type=AuthType.GOOGLE_OAUTH,
        required_scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
        auth_instructions="Authorize NEXUS to access Google Calendar for scheduling.",
        capabilities=[
            "View upcoming events",
            "Schedule meetings",
            "Find free time slots",
        ],
        default_tools=["calendar_list_events", "calendar_create_event", "calendar_delete_event"],
    ),

    # ── 3. GitHub (MCP Connector) ────────────────────────────────────────────
    "github": ConnectorDefinition(
        id="github",
        name="GitHub",
        description="Search code, manage repositories, create issues, and inspect pull requests.",
        category=ConnectorCategory.DEVELOPMENT,
        type=ConnectorType.MCP,
        icon="Github",
        auth_type=AuthType.TOKEN,
        auth_instructions="Provide a GitHub Personal Access Token (classic or fine-grained) with 'repo' and 'read:user' permissions.",
        auth_fields=[
            {
                "id": "token",
                "label": "GitHub Personal Access Token",
                "type": "password",
                "placeholder": "ghp_...",
                "required": True,
            }
        ],
        capabilities=[
            "Search repositories and issues",
            "Create and update issues",
            "Read pull requests and diffs",
            "Inspect repository trees and files",
        ],
        mcp_config={
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "{token}"},
            "transport": "stdio",
        },
        default_tools=[
            "github_search_repositories",
            "github_create_issue",
            "github_get_issue",
            "github_list_pull_requests",
        ],
    ),

    # ── 4. Spotify (Media & Playback API / MCP) ──────────────────────────────
    "spotify": ConnectorDefinition(
        id="spotify",
        name="Spotify",
        description="Control music playback, search tracks, and access your music playlists.",
        category=ConnectorCategory.MEDIA,
        type=ConnectorType.API,
        icon="Music",
        auth_type=AuthType.OAUTH,
        required_scopes=["user-modify-playback-state", "user-read-playback-state", "user-read-private"],
        auth_instructions="Sign in to Spotify once. Configure SPOTIFY_CLIENT_ID and register http://127.0.0.1:8000/api/connectors/spotify/callback as a redirect URI in your Spotify app. NEXUS uses PKCE and refreshes access tokens automatically; no client secret is needed.",
        capabilities=[
            "Search tracks and playlists",
            "Control playback (play, pause, skip)",
            "Get currently playing track",
        ],
        default_tools=["spotify_search_tracks", "spotify_play_track", "spotify_pause_playback"],
    ),

    # ── 5. Filesystem (Native / Local MCP) ────────────────────────────────────
    "filesystem": ConnectorDefinition(
        id="filesystem",
        name="Local Filesystem",
        description="Native local file access, document reading, directory inspection, and search.",
        category=ConnectorCategory.STORAGE,
        type=ConnectorType.LOCAL,
        icon="FolderOpen",
        auth_type=AuthType.NONE,
        capabilities=[
            "Read local files",
            "Write and edit documents",
            "Search files by name or pattern",
            "List directories",
        ],
        default_tools=["read_file", "write_file", "search_files", "list_directory"],
    ),

    # ── 6. Todoist (MCP / API) ────────────────────────────────────────────────
    "todoist": ConnectorDefinition(
        id="todoist",
        name="Todoist",
        description="Manage task lists, project deadlines, and daily todos.",
        category=ConnectorCategory.PRODUCTIVITY,
        type=ConnectorType.API,
        icon="CheckSquare",
        auth_type=AuthType.API_KEY,
        auth_instructions="Provide your Todoist API token from Settings > Integrations > Developer.",
        auth_fields=[
            {
                "id": "api_key",
                "label": "Todoist API Token",
                "type": "password",
                "placeholder": "e.g. 0123456789abcdef...",
                "required": True,
            }
        ],
        capabilities=[
            "Create tasks",
            "List project tasks",
            "Complete todos",
        ],
        default_tools=["todoist_create_task", "todoist_list_tasks", "todoist_complete_task"],
    ),

    # ── 7. Linear (MCP / API) ─────────────────────────────────────────────────
    "linear": ConnectorDefinition(
        id="linear",
        name="Linear",
        description="Track software issues, cycles, sprint milestones, and team projects.",
        category=ConnectorCategory.DEVELOPMENT,
        type=ConnectorType.API,
        icon="Layers",
        auth_type=AuthType.API_KEY,
        auth_instructions="Provide your Linear Personal API Key from Account Settings > Security & API.",
        auth_fields=[
            {
                "id": "api_key",
                "label": "Linear API Key",
                "type": "password",
                "placeholder": "lin_api_...",
                "required": True,
            }
        ],
        capabilities=[
            "Create and assign issues",
            "Search team sprint issues",
            "Update issue status",
        ],
        default_tools=["linear_create_issue", "linear_search_issues"],
    ),

    # ── 8. Slack (Communication API / MCP) ────────────────────────────────────
    "slack": ConnectorDefinition(
        id="slack",
        name="Slack",
        description="Send channel messages, lookup colleagues, and notify team channels.",
        category=ConnectorCategory.COMMUNICATION,
        type=ConnectorType.API,
        icon="MessageSquare",
        auth_type=AuthType.TOKEN,
        auth_instructions="Provide a Slack Bot User OAuth Token (xoxb-...) with chat:write permissions.",
        auth_fields=[
            {
                "id": "token",
                "label": "Bot User OAuth Token",
                "type": "password",
                "placeholder": "xoxb-...",
                "required": True,
            }
        ],
        capabilities=[
            "Post channel messages",
            "List public channels",
            "Send direct notifications",
        ],
        default_tools=["slack_send_message", "slack_list_channels"],
    ),

    # ── 9. Notion (Knowledge / Notes API) ─────────────────────────────────────
    "notion": ConnectorDefinition(
        id="notion",
        name="Notion",
        description="Search workspace databases, query pages, and append notes to Notion blocks.",
        category=ConnectorCategory.PRODUCTIVITY,
        type=ConnectorType.API,
        icon="FileText",
        auth_type=AuthType.TOKEN,
        auth_instructions="Enter your Notion Internal Integration Secret (secret_...).",
        auth_fields=[
            {
                "id": "token",
                "label": "Internal Integration Secret",
                "type": "password",
                "placeholder": "secret_...",
                "required": True,
            }
        ],
        capabilities=[
            "Search workspace pages",
            "Create database items",
            "Read page content",
        ],
        default_tools=["notion_search_pages", "notion_create_page"],
    ),

    # ── 10. Google Drive (Google API) ─────────────────────────────────────────
    "google_drive": ConnectorDefinition(
        id="google_drive",
        name="Google Drive",
        description="Search documents, spreadsheets, and files stored in your Google Drive.",
        category=ConnectorCategory.STORAGE,
        type=ConnectorType.API,
        icon="HardDrive",
        auth_type=AuthType.GOOGLE_OAUTH,
        required_scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        auth_instructions="Authorize NEXUS to search documents across Google Drive.",
        capabilities=[
            "Search Drive files",
            "Download file contents",
        ],
        default_tools=["drive_search_files", "drive_get_file"],
    ),
}


def get_all_connector_definitions() -> List[ConnectorDefinition]:
    return list(CATALOG.values())


def get_connector_definition(connector_id: str) -> Optional[ConnectorDefinition]:
    return CATALOG.get(connector_id)


CONNECTOR_CATALOG = CATALOG
list_all_definitions = get_all_connector_definitions
get_catalog_entry = get_connector_definition

