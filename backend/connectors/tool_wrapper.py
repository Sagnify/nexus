"""
ConnectorTool wrapper bridging connector discovered capabilities into NexusTool and ToolRegistry.
"""
from __future__ import annotations
from typing import Any, Dict
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.connectors.models import ConnectorToolMetadata


def _map_risk_level(level_str: str) -> RiskLevel:
    l = level_str.lower()
    if l in ("destructive", "dangerous", "delete"):
        return RiskLevel.DESTRUCTIVE
    elif l in ("caution", "mutation", "write", "modifying"):
        return RiskLevel.MODIFYING
    elif l in ("network", "http", "api"):
        return RiskLevel.NETWORK
    elif l in ("read_only", "readonly", "read"):
        return RiskLevel.READ_ONLY
    return RiskLevel.SAFE


class ConnectorTool(NexusTool):
    def __init__(self, metadata: ConnectorToolMetadata, adapter: Any, user_id: str = "default"):
        self.metadata = metadata
        self.adapter = adapter
        self.user_id = user_id
        self.name = metadata.name
        self.description = metadata.description
        self.risk_level = _map_risk_level(metadata.risk_level)
        self.connector_id = metadata.connector_id
        self.source = metadata.source

    async def execute(self, **kwargs) -> ToolResult:
        try:
            return await self.adapter.execute_tool(self.name, kwargs, self.user_id)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error executing {self.name} on connector {self.connector_id}: {e}",
            )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "connector_id": self.connector_id,
            "source": self.source,
            "parameters": self.metadata.input_schema,
        }
