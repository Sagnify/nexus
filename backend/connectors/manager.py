"""
NEXUS Central Connector Manager.
Coordinates connector lifecycle, authentication, adapters (MCP, Google API, Direct API),
tool discovery, and dynamic integration into the unified NEXUS Tool Registry.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from backend.agent.tools.registry import tool_registry
from backend.connectors.adapters.base import BaseConnectorAdapter
from backend.connectors.adapters.direct_api import DirectAPIAdapter
from backend.connectors.adapters.google import GoogleAPIAdapter
from backend.connectors.adapters.mcp import MCPConnectorAdapter
from backend.connectors.catalog import CATALOG, get_all_connector_definitions, get_connector_definition
from backend.connectors.credentials_store import credentials_store
from backend.connectors.models import (
    ConnectorDefinition,
    ConnectorState,
    ConnectorStatus,
    ConnectorToolMetadata,
    ConnectorType,
)
from backend.connectors.tool_wrapper import ConnectorTool

logger = logging.getLogger("nexus.connectors.manager")


class ConnectorManager:
    def __init__(self):
        self._adapters: Dict[str, BaseConnectorAdapter] = {}
        self._initialized: bool = False
        self._lock = asyncio.Lock()

    def get_adapter(self, connector_id: str) -> Optional[BaseConnectorAdapter]:
        if connector_id in self._adapters:
            return self._adapters[connector_id]

        defn = get_connector_definition(connector_id)
        if not defn:
            return None

        adapter: BaseConnectorAdapter
        if defn.id in ("gmail", "google_calendar", "google_drive"):
            adapter = GoogleAPIAdapter(defn)
        elif defn.type == ConnectorType.MCP:
            adapter = MCPConnectorAdapter(defn)
        else:
            adapter = DirectAPIAdapter(defn)

        self._adapters[connector_id] = adapter
        return adapter

    async def list_connectors(self, user_id: str = "default") -> List[ConnectorState]:
        """
        List all connectors with current real-time connection status,
        account identity, capabilities, and discovered tools.
        """
        states: List[ConnectorState] = []
        for defn in get_all_connector_definitions():
            state = await self.get_connector_state(defn.id, user_id)
            states.append(state)
        return states

    async def get_connector_state(self, connector_id: str, user_id: str = "default") -> ConnectorState:
        defn = get_connector_definition(connector_id)
        if not defn:
            raise ValueError(f"Unknown connector ID: {connector_id}")

        adapter = self.get_adapter(connector_id)

        # Filesystem is local and always connected
        if defn.type == ConnectorType.LOCAL:
            discovered = await adapter.discover_tools(user_id) if adapter else []
            return ConnectorState(
                id=defn.id,
                name=defn.name,
                description=defn.description,
                category=defn.category.value,
                type=defn.type.value,
                icon=defn.icon,
                status=ConnectorStatus.CONNECTED,
                auth_type=defn.auth_type.value,
                account_identifier="Local System",
                capabilities=defn.capabilities,
                discovered_tools=discovered,
                required_scopes=defn.required_scopes,
                auth_fields=defn.auth_fields,
            )

        creds = credentials_store.get_credential(user_id, connector_id)
        status = ConnectorStatus.DISCONNECTED
        account_id = None
        discovered_tools: List[ConnectorToolMetadata] = []

        if creds:
            account_id = creds.get("account_identifier")
            if defn.auth_type in ("google_oauth", "oauth"):
                if adapter:
                    status = await adapter.health_check(user_id)
            else:
                status = ConnectorStatus.CONNECTED

        if status == ConnectorStatus.CONNECTED and adapter:
            try:
                discovered_tools = await adapter.discover_tools(user_id)
                for t in discovered_tools:
                    wrapper = ConnectorTool(t, adapter, user_id)
                    tool_registry.register(wrapper)
                    if "." in t.tool_id:
                        alias_wrapper = ConnectorTool(
                            ConnectorToolMetadata(
                                tool_id=t.tool_id,
                                connector_id=t.connector_id,
                                name=t.tool_id,
                                description=t.description,
                                risk_level=t.risk_level,
                                source=t.source,
                                input_schema=t.input_schema,
                            ),
                            adapter,
                            user_id,
                        )
                        tool_registry.register(alias_wrapper)
            except Exception as e:
                logger.warning(f"Error fetching discovered tools for {connector_id}: {e}")

        return ConnectorState(
            id=defn.id,
            name=defn.name,
            description=defn.description,
            category=defn.category.value,
            type=defn.type.value,
            icon=defn.icon,
            status=status,
            auth_type=defn.auth_type.value,
            account_identifier=account_id,
            capabilities=defn.capabilities,
            discovered_tools=discovered_tools,
            required_scopes=defn.required_scopes,
            auth_fields=defn.auth_fields,
        )

    async def connect(self, connector_id: str, auth_payload: Dict[str, Any], user_id: str = "default") -> ConnectorState:
        """
        Authorize and establish connection for a connector.
        Registers its discovered tools directly into NEXUS ToolRegistry.
        """
        adapter = self.get_adapter(connector_id)
        if not adapter:
            raise ValueError(f"Unknown connector ID: {connector_id}")

        res = await adapter.connect(auth_payload, user_id)
        status = res.get("status", ConnectorStatus.CONNECTED)

        # Register tools in ToolRegistry if connection succeeded
        if status == ConnectorStatus.CONNECTED:
            tools = await adapter.discover_tools(user_id)
            for t in tools:
                wrapper = ConnectorTool(t, adapter, user_id)
                tool_registry.register(wrapper)
                # Register alias with dot notation if present
                if "." in t.tool_id:
                    alias_wrapper = ConnectorTool(
                        ConnectorToolMetadata(
                            tool_id=t.tool_id,
                            connector_id=t.connector_id,
                            name=t.tool_id,
                            description=t.description,
                            risk_level=t.risk_level,
                            source=t.source,
                            input_schema=t.input_schema,
                        ),
                        adapter,
                        user_id,
                    )
                    tool_registry.register(alias_wrapper)
            logger.info(f"Registered {len(tools)} tools from connector '{connector_id}' into ToolRegistry.")

        # Sync to DB if available
        await self._sync_db_connector(connector_id, user_id, status, res.get("account_identifier"))

        return await self.get_connector_state(connector_id, user_id)

    async def disconnect(self, connector_id: str, user_id: str = "default") -> ConnectorState:
        """
        Disconnect a connector, tear down sessions, and deregister its tools.
        """
        adapter = self.get_adapter(connector_id)
        if adapter:
            await adapter.disconnect(user_id)

        # Deregister all tools from ToolRegistry
        tool_registry.deregister_connector_tools(connector_id)
        logger.info(f"Deregistered tools for connector '{connector_id}' from ToolRegistry.")

        # Sync to DB
        await self._sync_db_connector(connector_id, user_id, ConnectorStatus.DISCONNECTED, None)

        return await self.get_connector_state(connector_id, user_id)

    async def initialize(self, user_id: str = "default") -> None:
        """Alias for initialize_connected_tools."""
        await self.initialize_connected_tools(user_id)

    async def initialize_connected_tools(self, user_id: str = "default") -> None:
        """
        Scan all connected connectors on startup and ensure their tools
        are populated in ToolRegistry.
        """
        async with self._lock:
            if self._initialized:
                return
            for defn in get_all_connector_definitions():
                try:
                    state = await self.get_connector_state(defn.id, user_id)
                    if state.status == ConnectorStatus.CONNECTED:
                        adapter = self.get_adapter(defn.id)
                        if adapter:
                            tools = await adapter.discover_tools(user_id)
                            for t in tools:
                                wrapper = ConnectorTool(t, adapter, user_id)
                                tool_registry.register(wrapper)
                except Exception as e:
                    logger.warning(f"Could not auto-register connector '{defn.id}' on startup: {e}")
            self._initialized = True

    def get_tool_prompt_additions(self) -> str:
        """
        Generate markdown instructions describing all active connector tools
        to inject dynamically into the Planner LLM prompt.
        """
        tools = tool_registry.all_connector_tools()
        if not tools:
            return ""

        lines = [
            "\n=======================================================",
            "TIER 0: ACTIVE APPLICATION CONNECTORS & MCP TOOLS (HIGHEST PRIORITY):",
            "- If the user's goal targets an application or service with an active connector listed below,",
            "  YOU MUST ALWAYS USE THE CONNECTOR TOOL INSTEAD OF BROWSER OR GUI AUTOMATION!",
            "- Connector tools execute directly via secure authenticated APIs in milliseconds, with zero UI interference.",
            "- NEVER generate `browser_navigate`, `browser_click`, or desktop clicks for an app when a connector tool is available.",
            "- Only fall back to browser/web automation if the requested service is NOT connected or has no matching tool.",
            "=======================================================",
            "\nConnected Application Connectors & Active MCP Tools:",
        ]
        by_conn: Dict[str, List[Any]] = {}
        for t in tools:
            cid = getattr(t, "connector_id", "external")
            by_conn.setdefault(cid, []).append(t)

        for cid, ctools in by_conn.items():
            lines.append(f"\nConnector '{cid}':")
            for t in ctools:
                schema = t.schema()
                params_str = json.dumps(schema.get("parameters", {}).get("properties", {}))
                lines.append(f"- \"{t.name}\": {t.description}. args: {params_str}")

        return "\n".join(lines) + "\n"

    async def _sync_db_connector(self, connector_id: str, user_id: str, status: ConnectorStatus, account_id: Optional[str]) -> None:
        try:
            from backend.database.session import safe_db_context
            from backend.database.models import UserConnector
            from sqlalchemy import select
            import uuid

            user_uuid = None
            try:
                user_uuid = uuid.UUID(user_id)
            except Exception:
                pass

            if not user_uuid:
                return

            async with safe_db_context() as session:
                if not session:
                    return
                stmt = select(UserConnector).where(
                    UserConnector.user_id == user_uuid,
                    UserConnector.connector_id == connector_id,
                )
                res = await session.execute(stmt)
                record = res.scalar_one_or_none()
                if record:
                    record.status = status.value
                    if account_id:
                        record.account_identifier = account_id
                else:
                    record = UserConnector(
                        user_id=user_uuid,
                        connector_id=connector_id,
                        status=status.value,
                        account_identifier=account_id or "",
                    )
                    session.add(record)
        except Exception as e:
            logger.debug(f"DB connector sync skipped: {e}")


connector_manager = ConnectorManager()
