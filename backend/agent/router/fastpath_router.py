"""
NEXUS Deterministic Fast-Path Router
====================================
Compiler for routine, predictable user intents that can be resolved deterministically
with ZERO LLM calls (<1ms latency).

Categories:
1. Application Launching (Chrome, Notepad, Calculator, VS Code, Spotify, Excel, Word, Terminal, etc.)
2. Filesystem Navigation & Operations (Open Downloads/Desktop/Documents, List Directory, Delete)
3. System Diagnostics & Hardware Control (Time, Date, Screenshot, Recycle Bin, Kill Process, Volume)
4. Math & Direct Calculations
5. Media Playback & Control (Spotify/Web via media_fastpath)
6. Web Search (Google, YouTube, Reddit, GitHub, Amazon via search_fastpath)
7. Connected APIs (Gmail quick-send, Calendar events)
"""
from __future__ import annotations

import re
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class FastPathResult:
    intent: str               # "shell" | "file_op" | "web_automation" | "general" | "question"
    goal: str
    category: str             # "app_launch" | "filesystem" | "system_util" | "math" | "media" | "search"
    plan: list[dict[str, Any]]
    rationale: str
    tokens_saved: int = 2400  # Conservative estimate of skipped LLM reasoning & planning tokens


def match_fastpath_plan(query: str, active_target: Optional[dict] = None) -> Optional[FastPathResult]:
    """
    Evaluates a user query against high-confidence deterministic patterns.
    Returns a FastPathResult if matched, or None to fall through to the LLM planner.
    """
    if not query or not query.strip():
        return None

    raw_query = query.strip()
    lower = raw_query.lower()

    # Guard: Do not intercept queries asking for full AI creative writing, coding, or deep explanation
    complex_triggers = (
        "why", "how to", "explain", "write an essay", "write a story", "refactor",
        "debug", "fix code", "analyze why", "summarize the difference",
    )
    if any(lower.startswith(w) for w in complex_triggers):
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Media Playback & Controls (Spotify, YouTube Music, SMTC)
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from backend.agent.router.media_fastpath import build_media_plan, extract_media_intent
        media_intent = extract_media_intent(raw_query)
        if media_intent:
            plan = build_media_plan(raw_query)
            if plan:
                intent_type = "web_automation" if (
                    media_intent.get("service") in ("youtube", "youtube_music", "soundcloud")
                    or not media_intent.get("prefer_desktop", True)
                ) else "shell"
                return FastPathResult(
                    intent=intent_type,
                    goal=raw_query,
                    category="media",
                    plan=plan,
                    rationale=f"Routing media playback directly: {raw_query}",
                    tokens_saved=2800,
                )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Web Search Fast-Path (Google, YouTube, Reddit, GitHub, Amazon, Wikipedia)
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from backend.agent.router.search_fastpath import build_search_plan, extract_search_intent
        if extract_search_intent(raw_query, active_target=active_target):
            plan = build_search_plan(raw_query)
            if plan:
                return FastPathResult(
                    intent="web_automation",
                    goal=raw_query,
                    category="search",
                    plan=plan,
                    rationale=f"Compiling direct search query: {raw_query}",
                    tokens_saved=2600,
                )
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Time & Date System Queries
    # ─────────────────────────────────────────────────────────────────────────
    time_date_patterns = [
        r"^(?:what(?:'?s|\s+is)?\s+)?(?:the\s+)?(?:current\s+)?(?:time|date|day)(?:\s+today|\s+now)?\??$",
        r"^(?:what\s+time\s+is\s+it|what\s+is\s+today'?s\s+date|today'?s\s+date)\??$",
        r"^(?:clock|calendar|current\s+time)\??$",
    ]
    if any(re.match(p, lower) for p in time_date_patterns):
        return FastPathResult(
            intent="question",
            goal=raw_query,
            category="system_util",
            plan=[
                {
                    "id": f"step_{uuid.uuid4().hex[:6]}",
                    "title": "Query System Clock & Date",
                    "description": "Retrieve current local time and calendar date.",
                    "tool": "get_current_time",
                    "args": {},
                    "risk_level": "READ_ONLY",
                    "status": "pending",
                }
            ],
            rationale="Retrieving current local time and date from system clock.",
            tokens_saved=2200,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Math & Calculations (e.g. "calculate 50 * 20", "what is 250 / 5")
    # ─────────────────────────────────────────────────────────────────────────
    math_match = re.match(
        r"^(?:calculate|what\s+is|calc|compute)\s+([0-9\s\+\-\*\/\^\(\)\.\%]+)\??$",
        lower,
    )
    if math_match:
        expr = math_match.group(1).strip()
        # Clean safe math expression
        clean_expr = expr.replace("^", "**").replace("%", "/100")
        if re.match(r"^[0-9\s\+\-\*\/\(\)\.]+$", clean_expr):
            try:
                # Safe eval of pure numeric expressions
                result = eval(clean_expr, {"__builtins__": {}}, {})
                formatted_res = f"### Calculation Result\n\n`{expr}` = **{result}**"
                return FastPathResult(
                    intent="question",
                    goal=raw_query,
                    category="math",
                    plan=[
                        {
                            "id": f"step_{uuid.uuid4().hex[:6]}",
                            "title": "Calculate Math Expression",
                            "description": f"Evaluate {expr}",
                            "tool": "ai_response",
                            "args": {"answer": formatted_res},
                            "risk_level": "READ_ONLY",
                            "status": "pending",
                        }
                    ],
                    rationale=f"Computed math expression: {expr} = {result}",
                    tokens_saved=2400,
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Application Launching & Window Management
    # ─────────────────────────────────────────────────────────────────────────
    app_launch_map = {
        "chrome": ("Google Chrome", "start chrome"),
        "google chrome": ("Google Chrome", "start chrome"),
        "chrome incognito": ("Google Chrome (Incognito)", "start chrome --incognito"),
        "notepad": ("Notepad", "start notepad"),
        "calculator": ("Calculator", "calc"),
        "calc": ("Calculator", "calc"),
        "vs code": ("Visual Studio Code", "code"),
        "vscode": ("Visual Studio Code", "code"),
        "code": ("Visual Studio Code", "code"),
        "spotify": ("Spotify", "start spotify:"),
        "terminal": ("Windows Terminal", "start wt"),
        "cmd": ("Command Prompt", "start cmd"),
        "powershell": ("PowerShell", "start powershell"),
        "paint": ("Paint", "start mspaint"),
        "mspaint": ("Paint", "start mspaint"),
        "word": ("Microsoft Word", "start winword"),
        "ms word": ("Microsoft Word", "start winword"),
        "excel": ("Microsoft Excel", "start excel"),
        "ms excel": ("Microsoft Excel", "start excel"),
        "edge": ("Microsoft Edge", "start msedge"),
        "task manager": ("Task Manager", "start taskmgr"),
        "file explorer": ("File Explorer", "start explorer"),
        "explorer": ("File Explorer", "start explorer"),
        "settings": ("Windows Settings", "start ms-settings:"),
    }

    launch_verb_match = re.match(
        r"^(?:open|launch|start|run|bring\s+up)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:app|application))?$",
        lower,
    )
    if launch_verb_match:
        target_app_key = launch_verb_match.group(1).strip()
        if target_app_key in app_launch_map:
            app_title, run_cmd = app_launch_map[target_app_key]
            return FastPathResult(
                intent="shell",
                goal=raw_query,
                category="app_launch",
                plan=[
                    {
                        "id": f"step_{uuid.uuid4().hex[:6]}",
                        "title": f"Launch {app_title}",
                        "description": f"Open and activate {app_title} on host operating system.",
                        "tool": "run_command",
                        "args": {"command": run_cmd},
                        "risk_level": "SAFE",
                        "status": "pending",
                    }
                ],
                rationale=f"Opening {app_title} directly via Windows execution service.",
                tokens_saved=2500,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Common Filesystem Folders Navigation
    # ─────────────────────────────────────────────────────────────────────────
    folder_map = {
        "downloads": ("Downloads", os.path.join(os.path.expanduser("~"), "Downloads")),
        "downloads folder": ("Downloads", os.path.join(os.path.expanduser("~"), "Downloads")),
        "my downloads": ("Downloads", os.path.join(os.path.expanduser("~"), "Downloads")),
        "desktop": ("Desktop", os.path.join(os.path.expanduser("~"), "Desktop")),
        "desktop folder": ("Desktop", os.path.join(os.path.expanduser("~"), "Desktop")),
        "documents": ("Documents", os.path.join(os.path.expanduser("~"), "Documents")),
        "my documents": ("Documents", os.path.join(os.path.expanduser("~"), "Documents")),
        "documents folder": ("Documents", os.path.join(os.path.expanduser("~"), "Documents")),
        "pictures": ("Pictures", os.path.join(os.path.expanduser("~"), "Pictures")),
        "music": ("Music", os.path.join(os.path.expanduser("~"), "Music")),
        "videos": ("Videos", os.path.join(os.path.expanduser("~"), "Videos")),
    }

    open_folder_match = re.match(
        r"^(?:open|show|view|explore)\s+(?:my\s+)?([a-zA-Z\s]+?)(?:\s+(?:folder|directory))?$",
        lower,
    )
    if open_folder_match:
        target_folder = open_folder_match.group(1).strip()
        if target_folder in folder_map:
            folder_title, folder_path = folder_map[target_folder]
            return FastPathResult(
                intent="file_op",
                goal=raw_query,
                category="filesystem",
                plan=[
                    {
                        "id": f"step_{uuid.uuid4().hex[:6]}",
                        "title": f"Open {folder_title} Folder",
                        "description": f"Open File Explorer in {folder_title} ({folder_path}).",
                        "tool": "run_command",
                        "args": {"command": f'explorer.exe "{folder_path}"'},
                        "risk_level": "SAFE",
                        "status": "pending",
                    }
                ],
                rationale=f"Opening {folder_title} folder in File Explorer.",
                tokens_saved=2400,
            )

    # List files in folder (e.g. "list files in downloads", "show files in desktop")
    list_files_match = re.match(
        r"^(?:list|show|get)\s+(?:all\s+)?files\s+(?:in|on|under)\s+(?:my\s+)?([a-zA-Z\s]+?)(?:\s+(?:folder|directory))?$",
        lower,
    )
    if list_files_match:
        target_folder = list_files_match.group(1).strip()
        if target_folder in folder_map:
            folder_title, folder_path = folder_map[target_folder]
            return FastPathResult(
                intent="file_op",
                goal=raw_query,
                category="filesystem",
                plan=[
                    {
                        "id": f"step_{uuid.uuid4().hex[:6]}",
                        "title": f"List Files in {folder_title}",
                        "description": f"Read and inspect file contents in {folder_path}.",
                        "tool": "list_directory",
                        "args": {"path": folder_path},
                        "risk_level": "READ_ONLY",
                        "status": "pending",
                    }
                ],
                rationale=f"Listing files in {folder_title} directory.",
                tokens_saved=2300,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 7. System Utilities: Screenshot & Recycle Bin
    # ─────────────────────────────────────────────────────────────────────────
    if lower in ("take screenshot", "take a screenshot", "screenshot", "screen capture", "capture screen"):
        return FastPathResult(
            intent="shell",
            goal=raw_query,
            category="system_util",
            plan=[
                {
                    "id": f"step_{uuid.uuid4().hex[:6]}",
                    "title": "Capture Screen State",
                    "description": "Take and inspect full desktop screenshot.",
                    "tool": "inspect_screen",
                    "args": {},
                    "risk_level": "READ_ONLY",
                    "status": "pending",
                }
            ],
            rationale="Capturing full screen state directly.",
            tokens_saved=2200,
        )

    if any(w in lower for w in ("recycle bin", "recyclebin", "trash bin")) and any(w in lower for w in ("empty", "clear", "clean", "purge")):
        return FastPathResult(
            intent="shell",
            goal=raw_query,
            category="system_util",
            plan=[
                {
                    "id": f"step_{uuid.uuid4().hex[:6]}",
                    "title": "Empty Windows Recycle Bin",
                    "description": "Permanently clear and remove all deleted files from the Windows Recycle Bin.",
                    "tool": "run_command",
                    "args": {
                        "command": "powershell.exe -NoProfile -Command \"Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Output 'Recycle Bin emptied successfully'\""
                    },
                    "risk_level": "DESTRUCTIVE",
                    "status": "pending",
                }
            ],
            rationale="Emptying Windows Recycle Bin via PowerShell.",
            tokens_saved=2500,
        )

    # Volume Control (Mute / Unmute / Volume Up / Volume Down)
    if "volume" in lower or "mute" in lower:
        vol_cmd = None
        if "mute" in lower or "unmute" in lower:
            vol_cmd = "$w = New-Object -ComObject Wscript.Shell; $w.SendKeys([char]173)"
        elif "up" in lower or "increase" in lower or "raise" in lower:
            vol_cmd = "$w = New-Object -ComObject Wscript.Shell; 1..5 | % { $w.SendKeys([char]175) }"
        elif "down" in lower or "decrease" in lower or "lower" in lower:
            vol_cmd = "$w = New-Object -ComObject Wscript.Shell; 1..5 | % { $w.SendKeys([char]174) }"

        if vol_cmd:
            return FastPathResult(
                intent="shell",
                goal=raw_query,
                category="system_util",
                plan=[
                    {
                        "id": f"step_{uuid.uuid4().hex[:6]}",
                        "title": "Adjust System Audio Volume",
                        "description": "Trigger hardware volume keys via PowerShell.",
                        "tool": "run_command",
                        "args": {"command": f'powershell.exe -NoProfile -Command "{vol_cmd}"'},
                        "risk_level": "SAFE",
                        "status": "pending",
                    }
                ],
                rationale="Adjusting system audio volume via host keyboard keys.",
                tokens_saved=2400,
            )

    return None
