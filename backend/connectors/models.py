"""
NEXUS Connector Models & Data Structures.
Defines connector specifications, authentication requirements, and tool schemas.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConnectorType(str, Enum):
    MCP = "mcp"
    API = "api"
    NATIVE = "native"
    LOCAL = "local"


class ConnectorStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ACTION_REQUIRED = "action_required"
    ERROR = "error"
    DISABLED = "disabled"


class AuthType(str, Enum):
    NONE = "none"
    TOKEN = "token"
    API_KEY = "api_key"
    OAUTH = "oauth"
    GOOGLE_OAUTH = "google_oauth"


class ConnectorCategory(str, Enum):
    ALL = "all"
    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    DEVELOPMENT = "development"
    MEDIA = "media"
    STORAGE = "storage"
    AUTOMATION = "automation"


class ConnectorToolMetadata(BaseModel):
    tool_id: str
    connector_id: str
    name: str
    description: str
    risk_level: str = "safe"  # safe, caution, dangerous
    source: str = "mcp"  # mcp, api, native, local
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ConnectorDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: ConnectorCategory = ConnectorCategory.PRODUCTIVITY
    type: ConnectorType = ConnectorType.API
    icon: str  # Lucide icon identifier or brand name
    auth_type: AuthType = AuthType.NONE
    required_scopes: List[str] = Field(default_factory=list)
    auth_instructions: str = ""
    auth_fields: List[Dict[str, Any]] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    default_tools: List[str] = Field(default_factory=list)
    mcp_config: Optional[Dict[str, Any]] = None


class ConnectorState(BaseModel):
    id: str
    name: str
    description: str
    category: str
    type: str
    icon: str
    status: ConnectorStatus = ConnectorStatus.DISCONNECTED
    auth_type: str = "none"
    account_identifier: Optional[str] = None
    connected_at: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    discovered_tools: List[ConnectorToolMetadata] = Field(default_factory=list)
    error_message: Optional[str] = None
    required_scopes: List[str] = Field(default_factory=list)
    auth_fields: List[Dict[str, Any]] = Field(default_factory=list)
