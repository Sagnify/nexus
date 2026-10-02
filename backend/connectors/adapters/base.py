"""
Base class for Connector Adapters.
Every connector type (MCP, Direct API, Native, Local) inherits from this interface.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from backend.agent.tools.base import ToolResult
from backend.connectors.models import (
    ConnectorDefinition,
    ConnectorStatus,
    ConnectorToolMetadata,
)


class BaseConnectorAdapter(ABC):
    def __init__(self, definition: ConnectorDefinition):
        self.definition = definition
        self.connector_id = definition.id

    @abstractmethod
    async def connect(self, auth_payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Authenticate and establish connector readiness.
        Returns dict containing status, account_identifier, and optional metadata.
        """
        ...

    @abstractmethod
    async def disconnect(self, user_id: str) -> bool:
        """Revoke or clear credentials and teardown active sessions."""
        ...

    @abstractmethod
    async def health_check(self, user_id: str) -> ConnectorStatus:
        """Check whether the external service/server is reachable."""
        ...

    @abstractmethod
    async def discover_tools(self, user_id: str) -> List[ConnectorToolMetadata]:
        """Discover tools exposed by the connector."""
        ...

    @abstractmethod
    async def execute_tool(self, tool_name: str, args: Dict[str, Any], user_id: str) -> ToolResult:
        """Execute a tool exposed by this connector."""
        ...
