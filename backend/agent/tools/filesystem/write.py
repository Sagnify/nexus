import os
import re
from pathlib import Path
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel


import sys


from backend.core.paths import resolve_system_path, get_active_desktop


def _resolve_filesystem_path(path_str: str) -> Path:
    """Resolve tilde, env vars, username placeholders, and OneDrive-synced Windows folders."""
    return resolve_system_path(path_str)


class WriteFileTool(NexusTool):
    name = "write_file"
    description = "Write or overwrite content to a file at the specified path."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, path: str, content: str, append: bool = False, **_) -> ToolResult:
        try:
            p = _resolve_filesystem_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(p, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Wrote"
            return ToolResult(
                success=True,
                output=f"{action} file: {p} ({len(content)} characters)",
                metadata={"path": str(p), "length": len(content), "append": append}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")


class DeleteFileTool(NexusTool):
    name = "delete_file"
    description = "Delete a file at the specified path."
    risk_level = RiskLevel.DESTRUCTIVE

    async def execute(self, path: str, **_) -> ToolResult:
        try:
            p = _resolve_filesystem_path(path)
            if not p.exists():
                return ToolResult(success=False, error=f"File not found: {path}", output="")
            if p.is_dir():
                return ToolResult(success=False, error=f"Target is a directory: {path}. Use specific directory operations.", output="")
            p.unlink()
            return ToolResult(
                success=True,
                output=f"Deleted file: {p}",
                metadata={"path": str(p)}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")
