"""Filesystem search tool."""
from __future__ import annotations
from pathlib import Path
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel


class SearchFilesTool(NexusTool):
    name = "search_files"
    description = "Search for files by filename pattern (glob) or text content within a directory."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, query: str, path: str = ".", search_content: bool = False, max_results: int = 25, **_) -> ToolResult:
        try:
            root = Path(path)
            if not root.exists():
                return ToolResult(success=False, error=f"Directory not found: {path}", output="")

            matches = []
            skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

            if search_content:
                for p in root.rglob("*"):
                    if any(part in skip_dirs for part in p.parts):
                        continue
                    if p.is_file():
                        try:
                            # skip large or binary files
                            if p.stat().st_size > 1_000_000:
                                continue
                            text = p.read_text(encoding="utf-8", errors="ignore")
                            if query.lower() in text.lower():
                                matches.append(str(p))
                                if len(matches) >= max_results:
                                    break
                        except Exception:
                            continue
            else:
                for p in root.rglob(f"*{query}*"):
                    if any(part in skip_dirs for part in p.parts):
                        continue
                    matches.append(str(p))
                    if len(matches) >= max_results:
                        break

            if not matches:
                return ToolResult(success=True, output=f"No matching files found for '{query}' in {path}")

            return ToolResult(
                success=True,
                output="\n".join(matches),
                metadata={"count": len(matches), "query": query}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")
