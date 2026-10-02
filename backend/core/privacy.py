"""
Privacy-First Metadata Sanitizer for NEXUS.
Redacts API keys, credentials, sensitive paths, and extracts structured metadata.
"""
from __future__ import annotations
import re
from typing import Any

# Sensitive regex patterns to sanitize
_REDACT_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|token|secret|password|bearer|auth|authorization)\s*[:=]\s*["\']?([^"\'\s,;]{6,})["\']?'),
    re.compile(r'gsk_[a-zA-Z0-9]{20,}'),
    re.compile(r'AIza[0-9A-Za-z-_]{35}'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'postgres(?:ql)?:\/\/[^:]+:[^@]+@'),
]


def sanitize_value(val: Any) -> Any:
    """Recursively redact secrets and sensitive values from dictionaries, lists, and strings."""
    if isinstance(val, str):
        cleaned = val
        for pat in _REDACT_PATTERNS:
            cleaned = pat.sub(r'\1: [REDACTED]', cleaned) if pat.groups > 0 else pat.sub('[REDACTED]', cleaned)
        return cleaned
    elif isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ("password", "secret", "token", "api_key", "cookie", "auth")):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, list):
        return [sanitize_value(item) for item in val]
    return val


def detect_application(tool_name: str, args: dict | None = None) -> str:
    """Classify the target application based on tool name and parameters."""
    if not tool_name:
        return "System"

    tool = tool_name.lower()
    if tool.startswith("browser_") or "extension" in tool or "web" in tool or "dom" in tool:
        return "Chrome"
    elif "docx" in tool or "word" in tool:
        return "Word"
    elif "xlsx" in tool or "spreadsheet" in tool or "excel" in tool:
        return "Excel"
    elif tool in ("run_command", "shell_execute", "execute_command"):
        return "Terminal"
    elif any(f in tool for f in ("read_file", "write_file", "search_files", "delete_file", "list_directory")):
        return "Filesystem"
    elif "gui_" in tool or "screen" in tool or "mouse" in tool or "keyboard" in tool:
        return "Desktop GUI"
    elif "tts" in tool or "speech" in tool:
        return "Voice"
    return "General"


def normalize_task_category(intent: str | None, prompt: str = "") -> str:
    """Map intent or prompt into a stable, normalized taxonomy category."""
    p_lower = prompt.lower()
    if intent:
        i_lower = intent.lower()
        if "doc" in i_lower or "word" in i_lower or ".docx" in p_lower:
            return "document_editing"
        if "sheet" in i_lower or "excel" in i_lower or "xlsx" in i_lower or ".xlsx" in p_lower:
            return "spreadsheet_analysis"
        if "browser" in i_lower or "web" in i_lower or "http" in p_lower or "youtube" in p_lower:
            return "web_automation"
        if "shell" in i_lower or "terminal" in i_lower or "cmd" in i_lower:
            return "system_automation"
        if "coding" in i_lower or "python" in p_lower or "code" in p_lower:
            return "coding"
        if "file" in i_lower:
            return "file_management"
        return i_lower

    if ".docx" in p_lower or "word" in p_lower:
        return "document_editing"
    if ".xlsx" in p_lower or "excel" in p_lower or "sheet" in p_lower:
        return "spreadsheet_analysis"
    if "youtube" in p_lower or "browse" in p_lower or "google" in p_lower:
        return "web_automation"
    return "general"
