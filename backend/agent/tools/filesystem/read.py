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


class ReadFileTool(NexusTool):
    name = "read_file"
    description = "Read the content of a file at the given path."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: str, **_) -> ToolResult:
        try:
            p = _resolve_filesystem_path(path)
            if not p.exists():
                return ToolResult(success=False, error=f"File not found: {path}", output="")
            if p.stat().st_size > 2_000_000:  # 2MB limit
                return ToolResult(success=False, error="File too large (>2MB)", output="")
            content = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(success=True, output=content, metadata={"path": str(p), "size": p.stat().st_size})
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")


class ListDirectoryTool(NexusTool):
    name = "list_directory"
    description = "List files and directories at the given path."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: str = ".", depth: int = 2, **_) -> ToolResult:
        try:
            p = _resolve_filesystem_path(path)
            if not p.exists():
                return ToolResult(success=False, error=f"Path not found: {path}", output="")
            lines = self._scan(p, depth, 0)
            return ToolResult(success=True, output="\n".join(lines), metadata={"path": str(p)})
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")

    def _scan(self, p: Path, max_depth: int, current: int) -> list[str]:
        if current > max_depth:
            return []
        results = []
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return [f"{'  ' * current}[permission denied]"]
        for entry in entries:
            prefix = "  " * current
            if entry.name.startswith(".") or entry.name in ("node_modules", "__pycache__", "venv", ".git"):
                continue
            if entry.is_dir():
                results.append(f"{prefix}[dir] {entry.name}/")
                results.extend(self._scan(entry, max_depth, current + 1))
            else:
                results.append(f"{prefix}[file] {entry.name}")
        return results
