"""Command and filesystem safety policies."""
from __future__ import annotations
import re
from enum import Enum


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    SAFE = "SAFE"
    MODIFYING = "MODIFYING"
    NETWORK = "NETWORK"
    DESTRUCTIVE = "DESTRUCTIVE"
    PRIVILEGED = "PRIVILEGED"


# --- Shell Command Policy ---

_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-rf?\b",
    r"\brmdir\b",
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bdd\b.*\bof=/dev",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bkill\b.*\-9",
    r"\bpoweroff\b",
    r"\bClear-RecycleBin\b",
    r"\brecycle\s*bin\b",
    r"\bRemove-Item\b.*\-Recurse\b",
    r"\bRm-Item\b.*\-Recurse\b",
    r"\btaskkill\b",
    r"\bStop-Process\b",
    r"\bnet\s+stop\b",
    r"\bsc\s+stop\b",
]

_PRIVILEGED_PATTERNS = [
    r"^sudo\b",
    r"^su\b",
    r"runas\b",
    r"privilege",
    r"\bStart-Process\b.*\-Verb\s+RunAs\b",
    r"\bShellExecute\b.*runas\b",
    r"\bClear-RecycleBin\b",
    r"\btaskkill\b",
    r"\bStop-Process\b",
    r"\bnet\s+stop\b",
    r"\bsc\s+stop\b",
]

_NETWORK_PATTERNS = [
    r"\bcurl\b",
    r"\bwget\b",
    r"\bhttp[s]?://",
    r"\bssh\b",
    r"\bscp\b",
    r"\bftp\b",
]

_READ_ONLY_PATTERNS = [
    r"^(cat|less|more|head|tail|grep|find|ls|dir|type|echo|pwd|whoami|git\s+status|git\s+log|git\s+diff|git\s+show)\b",
]

_SAFE_PATTERNS = [
    r"^(npm|yarn|pip|python|node|npx)\b",
    r"^(git\s+(add|commit|push|pull|fetch|clone|checkout|branch))\b",
    r"^(mkdir|touch|cp|mv)\b",
    r"^(pytest|jest|cargo\s+test|go\s+test)\b",
    r"^(start|code|explorer|calc|notepad)\b",
]


def classify_command(command: str) -> RiskLevel:
    cmd = command.strip()
    if any(re.search(p, cmd, re.IGNORECASE) for p in _PRIVILEGED_PATTERNS):
        return RiskLevel.PRIVILEGED
    if any(re.search(p, cmd, re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS):
        return RiskLevel.DESTRUCTIVE
    if any(re.search(p, cmd, re.IGNORECASE) for p in _READ_ONLY_PATTERNS):
        return RiskLevel.READ_ONLY
    if any(re.search(p, cmd, re.IGNORECASE) for p in _NETWORK_PATTERNS):
        return RiskLevel.NETWORK
    if any(re.search(p, cmd, re.IGNORECASE) for p in _SAFE_PATTERNS):
        return RiskLevel.SAFE
    return RiskLevel.MODIFYING


def requires_permission(risk: RiskLevel) -> bool:
    return risk in (RiskLevel.DESTRUCTIVE, RiskLevel.PRIVILEGED)


# --- File Operation Policy ---

def classify_file_op(operation: str) -> RiskLevel:
    op = operation.lower()
    if op in ("read", "list", "search"):
        return RiskLevel.READ_ONLY
    if op in ("create", "write"):
        return RiskLevel.MODIFYING
    if op in ("delete", "overwrite"):
        return RiskLevel.DESTRUCTIVE
    if op in ("move", "copy", "rename"):
        return RiskLevel.MODIFYING
    return RiskLevel.MODIFYING


# --- Browser Operation Policy ---

def classify_browser_op(tool_name: str, args: dict | None = None) -> RiskLevel:
    name = tool_name.lower().strip()
    if name in ("browser_get_tabs", "browser_inspect"):
        return RiskLevel.READ_ONLY
    if name == "browser_execute_js":
        return RiskLevel.MODIFYING
    if name in ("browser_navigate", "browser_click", "browser_type", "browser_select", "browser_press", "browser_wait", "browser_switch_tab", "browser_dismiss_popup"):
        return RiskLevel.SAFE
    return RiskLevel.SAFE


# --- Document Operation Policy ---

def classify_document_op(tool_name: str, args: dict | None = None) -> RiskLevel:
    name = tool_name.lower().strip()
    if name in ("document_read", "document_verify", "document_open"):
        return RiskLevel.READ_ONLY
    if name in (
        "document_create", "document_add_title", "document_add_heading",
        "document_add_paragraph", "document_add_bullet", "document_add_numbered_item",
        "document_add_table", "document_add_page_break", "document_add_image", "document_save"
    ):
        return RiskLevel.MODIFYING
    return RiskLevel.MODIFYING


# --- Spreadsheet Operation Policy ---

def classify_spreadsheet_op(tool_name: str, args: dict | None = None) -> RiskLevel:
    name = tool_name.lower().strip()
    if name in (
        "spreadsheet_read", "spreadsheet_verify", "spreadsheet_open",
        "spreadsheet_list_sheets", "spreadsheet_read_cell", "spreadsheet_read_range", "spreadsheet_read_sheet"
    ):
        return RiskLevel.READ_ONLY
    if name in (
        "spreadsheet_create", "spreadsheet_create_sheet", "spreadsheet_rename_sheet",
        "spreadsheet_write_cell", "spreadsheet_write_range", "spreadsheet_add_formula",
        "spreadsheet_format_range", "spreadsheet_create_table", "spreadsheet_create_chart", "spreadsheet_save"
    ):
        return RiskLevel.MODIFYING
    return RiskLevel.MODIFYING



