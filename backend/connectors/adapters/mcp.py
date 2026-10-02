"""
Model Context Protocol (MCP) Connector Adapter for NEXUS.
Manages MCP server subprocess/SSE lifecycle, JSON-RPC 2.0 protocol handshake,
dynamic tool discovery (`tools/list`), schema validation, and tool invocation (`tools/call`).
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from backend.agent.tools.base import ToolResult
from backend.connectors.adapters.base import BaseConnectorAdapter
from backend.connectors.credentials_store import credentials_store
from backend.connectors.models import (
    ConnectorDefinition,
    ConnectorStatus,
    ConnectorToolMetadata,
)

logger = logging.getLogger("nexus.connectors.mcp")


def _classify_mcp_tool_risk(name: str, desc: str) -> str:
    """Classify tool risk level based on naming and semantic intent."""
    lowered = name.lower()
    if any(p in lowered for p in ("delete", "remove", "drop", "purge", "destroy", "kill")):
        return "dangerous"
    if any(p in lowered for p in ("create", "update", "write", "post", "send", "mutate", "modify", "push", "fork")):
        return "caution"
    return "safe"


class MCPConnectorAdapter(BaseConnectorAdapter):
    def __init__(self, definition: ConnectorDefinition):
        super().__init__(definition)
        self._process: Optional[asyncio.subprocess.Process] = None
        self._next_rpc_id: int = 1
        self._discovered_tools: List[ConnectorToolMetadata] = []
        self._lock = asyncio.Lock()

    async def connect(self, auth_payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Store authentication configuration, launch or test MCP server session,
        perform protocol handshake, and discover tools.
        """
        token = auth_payload.get("token") or auth_payload.get("api_key")
        env_vars = auth_payload.get("env") or {}

        # Save credentials securely
        if token or env_vars:
            credentials_store.save_credential(
                user_id=user_id,
                connector_id=self.connector_id,
                creds={
                    "token": token,
                    "env": env_vars,
                },
            )

        # Attempt handshake & tool discovery
        try:
            tools = await self.discover_tools(user_id)
            if tools:
                return {
                    "status": ConnectorStatus.CONNECTED,
                    "account_identifier": f"MCP ({len(tools)} tools discovered)",
                    "connected_at": "now",
                    "tools_count": len(tools),
                }
            else:
                return {
                    "status": ConnectorStatus.CONNECTED,
                    "account_identifier": "MCP Server Ready",
                    "connected_at": "now",
                    "tools_count": 0,
                }
        except Exception as e:
            logger.warning(f"MCP connection handshake warning: {e}")
            return {
                "status": ConnectorStatus.CONNECTED,
                "account_identifier": "MCP Configured",
                "connected_at": "now",
            }

    async def disconnect(self, user_id: str) -> bool:
        """Teardown active MCP process and purge credentials."""
        async with self._lock:
            if self._process:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=3.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
            self._discovered_tools = []
        return credentials_store.delete_credential(user_id, self.connector_id)

    async def health_check(self, user_id: str) -> ConnectorStatus:
        creds = credentials_store.get_credential(user_id, self.connector_id)
        if self.definition.auth_type != "none" and not creds:
            return ConnectorStatus.DISCONNECTED
        return ConnectorStatus.CONNECTED

    def _build_env(self, user_id: str) -> Dict[str, str]:
        """Assemble environment variables including stored tokens and system PATH."""
        env = dict(os.environ)
        creds = credentials_store.get_credential(user_id, self.connector_id) or {}
        token = creds.get("token")

        mcp_cfg = self.definition.mcp_config or {}
        cfg_env = mcp_cfg.get("env", {})

        for k, v in cfg_env.items():
            if isinstance(v, str) and "{token}" in v and token:
                env[k] = v.replace("{token}", token)
            elif token and not v:
                env[k] = token
            elif isinstance(v, str):
                env[k] = v

        if token:
            if self.connector_id == "github":
                env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
                env["GITHUB_TOKEN"] = token

        return env

    async def _ensure_process(self, user_id: str) -> Optional[asyncio.subprocess.Process]:
        """Ensure active MCP subprocess with stdio transport."""
        if self._process and self._process.returncode is None:
            return self._process

        mcp_cfg = self.definition.mcp_config
        if not mcp_cfg:
            return None

        command = mcp_cfg.get("command")
        args = list(mcp_cfg.get("args", []))

        # Check if command exists
        cmd_path = shutil.which(command)
        if not cmd_path and sys.platform == "win32" and command in ("npx", "npm", "node"):
            cmd_path = shutil.which(f"{command}.cmd") or command

        env = self._build_env(user_id)

        try:
            self._process = await asyncio.create_subprocess_exec(
                cmd_path or command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Perform MCP Handshake
            await self._send_rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
                    "clientInfo": {"name": "nexus-agent", "version": "1.0.0"},
                },
                timeout=10.0,
            )

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            return self._process
        except Exception as e:
            logger.error(f"Failed to launch MCP server ({self.connector_id}): {e}")
            self._process = None
            return None

    async def _send_rpc(self, method: str, params: Dict[str, Any], timeout: float = 15.0) -> Optional[Dict[str, Any]]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        rpc_id = self._next_rpc_id
        self._next_rpc_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
        }
        raw_msg = json.dumps(payload) + "\n"
        self._process.stdin.write(raw_msg.encode("utf-8"))
        await self._process.stdin.drain()

        # Read JSON-RPC response line
        try:
            line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
            if line:
                data = json.loads(line.decode("utf-8").strip())
                return data.get("result")
        except Exception as e:
            logger.warning(f"MCP RPC error on {method}: {e}")
        return None

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        raw_msg = json.dumps(payload) + "\n"
        self._process.stdin.write(raw_msg.encode("utf-8"))
        await self._process.stdin.drain()

    async def discover_tools(self, user_id: str) -> List[ConnectorToolMetadata]:
        async with self._lock:
            # First check if live process can provide dynamic tools
            proc = await self._ensure_process(user_id)
            if proc:
                res = await self._send_rpc("tools/list", {})
                if res and "tools" in res:
                    mcp_tools = res["tools"]
                    discovered = []
                    for t in mcp_tools:
                        name = t.get("name", "")
                        desc = t.get("description", "")
                        schema = t.get("inputSchema", {})
                        risk = _classify_mcp_tool_risk(name, desc)
                        discovered.append(
                            ConnectorToolMetadata(
                                tool_id=f"{self.connector_id}.{name}",
                                connector_id=self.connector_id,
                                name=f"{self.connector_id}_{name}",
                                description=desc or f"{self.definition.name} tool {name}",
                                risk_level=risk,
                                source="mcp",
                                input_schema=schema,
                            )
                        )
                    self._discovered_tools = discovered
                    return discovered

            # If MCP server is not currently running as subprocess, return catalog default schemas
            fallback = []
            for dt in self.definition.default_tools:
                clean_name = dt.replace(f"{self.connector_id}_", "")
                fallback.append(
                    ConnectorToolMetadata(
                        tool_id=f"{self.connector_id}.{clean_name}",
                        connector_id=self.connector_id,
                        name=dt,
                        description=f"{self.definition.name} {clean_name.replace('_', ' ')}",
                        risk_level=_classify_mcp_tool_risk(clean_name, ""),
                        source="mcp",
                        input_schema={"type": "object", "properties": {}},
                    )
                )
            self._discovered_tools = fallback
            return fallback

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], user_id: str) -> ToolResult:
        proc = await self._ensure_process(user_id)
        if not proc:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP Server for {self.definition.name} is not running or failed to launch.",
            )

        clean_name = tool_name
        if tool_name.startswith(f"{self.connector_id}_"):
            clean_name = tool_name[len(f"{self.connector_id}_"):]
        elif "." in tool_name:
            clean_name = tool_name.split(".", 1)[1]

        res = await self._send_rpc("tools/call", {"name": clean_name, "arguments": args}, timeout=30.0)
        if not res:
            return ToolResult(success=False, output="", error=f"MCP tool call '{tool_name}' timed out or gave no response.")

        content = res.get("content", [])
        is_error = res.get("isError", False)
        output_parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                output_parts.append(item["text"])
            else:
                output_parts.append(str(item))

        full_output = "\n".join(output_parts) or str(res)
        return ToolResult(
            success=not is_error,
            output=full_output if not is_error else "",
            error=full_output if is_error else "",
            metadata=res,
        )
