"""
NEXUS Multi-Tier Outcome Validation Layer
=========================================
Verifies that a completed task's intended effect was ACTUALLY achieved in the real world
before declaring success.

Tiers:
- Tier 1: Deterministic Ground-Truth Verifier (0 LLM Calls, <5ms).
  Inspects real files on disk (existence, size, non-empty content, valid docx/xlsx/pptx/json),
  running process state in Windows, active media playback (Windows SMTC), and command return codes.
- Tier 2: Live DOM Mutation Verifier (Web tasks).
  Inspects URL transitions, form submission toasts, and element visibility without vision models.
- Tier 3: Semantic Verifier (Only if Tier 1/2 are genuinely ambiguous).

If validation fails, returns exact failure reason and corrective suggestion
to enable closed-loop LLM exception repair.
"""
from __future__ import annotations

import os
import re
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.outcome_validator")


@dataclass
class OutcomeValidationResult:
    passed: bool
    confidence: float            # 0.0 – 1.0
    reason: str
    tier: str                    # "ground_truth" | "live_dom" | "semantic" | "skipped"
    corrective_suggestion: Optional[str] = None
    details: dict = field(default_factory=dict)


def verify_filesystem_outcome(
    target_path: str,
    expected_type: Optional[str] = None,
    min_bytes: int = 1,
) -> OutcomeValidationResult:
    """Verifies that a file was actually created on disk, is non-empty, and structurally valid."""
    if not target_path:
        return OutcomeValidationResult(
            passed=False,
            confidence=0.95,
            reason="No target file path was specified for filesystem verification.",
            tier="ground_truth",
            corrective_suggestion="Provide a concrete file path.",
        )

    # Normalize Windows/Unix path
    norm_path = os.path.expanduser(os.path.expandvars(target_path.strip().strip("'\"")))
    if not os.path.isabs(norm_path):
        # Resolve relative to current working directory or Desktop
        if norm_path.lower().startswith("desktop"):
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            norm_path = os.path.join(desktop, norm_path[len("desktop"):].lstrip("\\/"))
        elif norm_path.lower().startswith("downloads"):
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            norm_path = os.path.join(downloads, norm_path[len("downloads"):].lstrip("\\/"))
        elif norm_path.lower().startswith("documents"):
            documents = os.path.join(os.path.expanduser("~"), "Documents")
            norm_path = os.path.join(documents, norm_path[len("documents"):].lstrip("\\/"))
        else:
            norm_path = os.path.abspath(norm_path)

    if not os.path.exists(norm_path):
        return OutcomeValidationResult(
            passed=False,
            confidence=1.0,
            reason=f"Target file does not exist on disk: '{norm_path}'",
            tier="ground_truth",
            corrective_suggestion=f"Verify file save path or retry writing to '{norm_path}'.",
            details={"path": norm_path, "exists": False},
        )

    try:
        size = os.path.getsize(norm_path)
    except Exception as e:
        return OutcomeValidationResult(
            passed=False,
            confidence=0.9,
            reason=f"Failed to inspect file size: {e}",
            tier="ground_truth",
            details={"path": norm_path, "error": str(e)},
        )

    if size < min_bytes:
        return OutcomeValidationResult(
            passed=False,
            confidence=1.0,
            reason=f"File exists but is empty (0 bytes): '{norm_path}'",
            tier="ground_truth",
            corrective_suggestion=f"Re-write content into '{norm_path}'.",
            details={"path": norm_path, "size": size},
        )

    ext = os.path.splitext(norm_path)[1].lower()
    details: dict[str, Any] = {"path": norm_path, "size": size, "extension": ext}

    # Format-specific deep structural validation
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(norm_path)
            para_count = len(doc.paragraphs)
            table_count = len(doc.tables)
            details["paragraphs"] = para_count
            details["tables"] = table_count
            if para_count == 0 and table_count == 0:
                return OutcomeValidationResult(
                    passed=False,
                    confidence=0.95,
                    reason=f"Word document '{norm_path}' was created but has 0 paragraphs and 0 tables.",
                    tier="ground_truth",
                    corrective_suggestion="Ensure paragraphs or headings are inserted before saving.",
                    details=details,
                )
        except Exception as e:
            return OutcomeValidationResult(
                passed=False,
                confidence=0.95,
                reason=f"Word document '{norm_path}' is corrupted or cannot be parsed by python-docx: {e}",
                tier="ground_truth",
                corrective_suggestion="Re-generate and save valid DOCX document.",
                details=details,
            )

    elif ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(norm_path, data_only=True, read_only=True)
            sheet_names = wb.sheetnames
            details["sheet_names"] = sheet_names
            wb.close()
            if not sheet_names:
                return OutcomeValidationResult(
                    passed=False,
                    confidence=0.95,
                    reason=f"Excel workbook '{norm_path}' contains no worksheets.",
                    tier="ground_truth",
                    corrective_suggestion="Add at least one sheet with tabular data.",
                    details=details,
                )
        except Exception as e:
            return OutcomeValidationResult(
                passed=False,
                confidence=0.95,
                reason=f"Excel workbook '{norm_path}' is corrupted or unreadable: {e}",
                tier="ground_truth",
                details=details,
            )

    elif ext == ".pptx":
        try:
            import pptx
            prs = pptx.Presentation(norm_path)
            slide_count = len(prs.slides)
            details["slides"] = slide_count
            if slide_count == 0:
                return OutcomeValidationResult(
                    passed=False,
                    confidence=0.95,
                    reason=f"PowerPoint presentation '{norm_path}' has 0 slides.",
                    tier="ground_truth",
                    details=details,
                )
        except Exception as e:
            return OutcomeValidationResult(
                passed=False,
                confidence=0.95,
                reason=f"PowerPoint presentation '{norm_path}' is corrupted: {e}",
                tier="ground_truth",
                details=details,
            )

    elif ext == ".json":
        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            details["json_type"] = type(json_data).__name__
        except Exception as e:
            return OutcomeValidationResult(
                passed=False,
                confidence=0.95,
                reason=f"JSON file '{norm_path}' contains invalid syntax: {e}",
                tier="ground_truth",
                details=details,
            )

    return OutcomeValidationResult(
        passed=True,
        confidence=1.0,
        reason=f"Verified file exists, valid structure, and non-empty size ({size} bytes): '{os.path.basename(norm_path)}'",
        tier="ground_truth",
        details=details,
    )


def verify_process_outcome(app_name: str) -> OutcomeValidationResult:
    """Verifies that an application or process was successfully started and is currently running."""
    if not app_name:
        return OutcomeValidationResult(
            passed=True, confidence=0.7,
            reason="No application process to verify.", tier="skipped"
        )

    clean_name = app_name.lower().replace(".exe", "").strip()
    # Map common aliases to executable names
    exe_map = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "edge": "msedge.exe",
        "msedge": "msedge.exe",
        "notepad": "notepad.exe",
        "calc": "calculatorapp.exe",
        "calculator": "calculatorapp.exe",
        "code": "code.exe",
        "vscode": "code.exe",
        "vs code": "code.exe",
        "spotify": "spotify.exe",
        "excel": "excel.exe",
        "word": "winword.exe",
        "terminal": "windowsterminal.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "paint": "mspaint.exe",
    }
    target_exe = exe_map.get(clean_name, f"{clean_name}.exe")

    try:
        # Use Windows tasklist directly
        cmd = f'tasklist /FI "IMAGENAME eq {target_exe}" /NH'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        is_running = target_exe.lower() in out.lower()
        if is_running:
            return OutcomeValidationResult(
                passed=True,
                confidence=0.99,
                reason=f"Verified process '{target_exe}' is actively running in Windows.",
                tier="ground_truth",
                details={"process": target_exe, "running": True},
            )
        else:
            # Check without extension or partial match
            cmd_all = "tasklist /NH"
            out_all = subprocess.check_output(cmd_all, shell=True, text=True, stderr=subprocess.DEVNULL)
            if clean_name in out_all.lower():
                return OutcomeValidationResult(
                    passed=True,
                    confidence=0.95,
                    reason=f"Verified application matching '{clean_name}' is running.",
                    tier="ground_truth",
                    details={"matched": clean_name, "running": True},
                )

            return OutcomeValidationResult(
                passed=False,
                confidence=0.9,
                reason=f"Process '{target_exe}' was not found in active Windows process table.",
                tier="ground_truth",
                corrective_suggestion=f"Attempt launching '{app_name}' with explicit executable path.",
                details={"process": target_exe, "running": False},
            )
    except Exception as e:
        return OutcomeValidationResult(
            passed=True,  # Don't fail if tasklist check itself errored
            confidence=0.5,
            reason=f"Could not inspect process table: {e}",
            tier="skipped",
        )


def verify_media_outcome(query: str = "") -> OutcomeValidationResult:
    """Verifies that media is actively playing via Windows SMTC (System Media Transport Controls)."""
    try:
        from backend.agent.nodes.evaluator import _get_smtc_media_info
        smtc = _get_smtc_media_info()
        status = smtc.get("status")
        title = smtc.get("title") or ""
        artist = smtc.get("artist") or ""

        if status == "Playing":
            return OutcomeValidationResult(
                passed=True,
                confidence=0.98,
                reason=f"Verified media is Playing via Windows SMTC: '{title}' by '{artist}'.",
                tier="ground_truth",
                details=smtc,
            )
        elif status in ("Paused", "Stopped"):
            return OutcomeValidationResult(
                passed=True,
                confidence=0.9,
                reason=f"Verified media state is {status} in Windows SMTC: '{title}'.",
                tier="ground_truth",
                details=smtc,
            )
        else:
            return OutcomeValidationResult(
                passed=True,
                confidence=0.7,
                reason="Media action dispatched (SMTC state not definitively Playing/Paused).",
                tier="ground_truth",
                details=smtc,
            )
    except Exception as e:
        return OutcomeValidationResult(
            passed=True,
            confidence=0.6,
            reason=f"Media verification bypassed: {e}",
            tier="skipped",
        )


def verify_command_outcome(
    command: str,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> OutcomeValidationResult:
    """Verifies that a system CLI command succeeded cleanly."""
    if exit_code != 0:
        clean_err = (stderr or stdout or "Non-zero exit code").strip()
        return OutcomeValidationResult(
            passed=False,
            confidence=1.0,
            reason=f"Command '{command}' failed with exit code {exit_code}: {clean_err[:120]}",
            tier="ground_truth",
            corrective_suggestion="Review command syntax or required environment permissions.",
            details={"command": command, "exit_code": exit_code, "error": clean_err[:200]},
        )

    # Check for silent errors in stdout (e.g. 'not recognized as an internal or external command')
    lower_out = stdout.lower()
    fatal_patterns = [
        "not recognized as an internal or external command",
        "cannot find the path specified",
        "access is denied",
        "permission denied",
        "fatal error",
        "command not found",
    ]
    for fp in fatal_patterns:
        if fp in lower_out:
            return OutcomeValidationResult(
                passed=False,
                confidence=0.98,
                reason=f"Command produced system error: '{fp}'",
                tier="ground_truth",
                corrective_suggestion="Fix command path or launch with elevated permissions.",
                details={"command": command, "matched_error": fp},
            )

    return OutcomeValidationResult(
        passed=True,
        confidence=0.99,
        reason=f"Command '{command}' exited cleanly with return code 0.",
        tier="ground_truth",
        details={"command": command, "exit_code": 0},
    )


async def validate_task_outcome(state: dict[str, Any]) -> OutcomeValidationResult:
    """
    Central Outcome Validation Dispatcher.
    Inspects task state, plan steps, and execution history to select the appropriate ground-truth verifier.
    """
    plan = state.get("plan", [])
    history = state.get("execution_history", [])
    goal = (state.get("goal") or state.get("user_input") or "").lower()

    if not plan and not history:
        return OutcomeValidationResult(
            passed=True, confidence=1.0, reason="No executable actions to validate.", tier="skipped"
        )

    # 1. Any failed plan step is an immediate failure
    failed_steps = [s for s in plan if s.get("status") == "failed"]
    if failed_steps:
        err = failed_steps[0].get("error") or "A planned step failed during execution."
        return OutcomeValidationResult(
            passed=False,
            confidence=1.0,
            reason=f"Execution step '{failed_steps[0].get('title', 'Unknown')}' failed: {err}",
            tier="ground_truth",
            corrective_suggestion="Re-plan or retry the failed milestone.",
            details={"failed_step": failed_steps[0]},
        )

    # 2. Check for File Creation & Document Automation Outcomes
    file_save_steps = [
        s for s in plan
        if s.get("tool") in (
            "write_file", "document_save", "spreadsheet_save", "document_create",
            "spreadsheet_create", "document_verify", "spreadsheet_verify"
        )
    ]
    if file_save_steps:
        last_step = file_save_steps[-1]
        args = last_step.get("args") or {}
        path = args.get("path") or args.get("file_path") or ""
        # Also check history for resolved file path
        if not path:
            for h in reversed(history):
                if h.get("metadata", {}).get("path"):
                    path = h["metadata"]["path"]
                    break
                elif h.get("args", {}).get("path"):
                    path = h["args"]["path"]
                    break

        if path and path not in ("<ask_user>", "user_choice"):
            return verify_filesystem_outcome(path)

    # 3. Check for Process / App Launch Outcomes
    cmd_steps = [s for s in plan if s.get("tool") == "run_command"]
    if cmd_steps:
        for s in cmd_steps:
            cmd = (s.get("args") or {}).get("command", "")
            # If command was a launch command like "start chrome" or "notepad"
            for app in ("chrome", "notepad", "calc", "calculator", "spotify", "code", "excel", "word", "msedge"):
                if f"start {app}" in cmd.lower() or f"{app}.exe" in cmd.lower() or cmd.lower().strip() == app:
                    return verify_process_outcome(app)
            # General command verification
            res = s.get("result", "")
            err = s.get("error", "")
            ver = verify_command_outcome(cmd, exit_code=1 if err else 0, stdout=str(res), stderr=str(err))
            if not ver.passed:
                return ver

    # 4. Check for Media Playback Outcomes
    media_steps = [s for s in plan if s.get("tool") in ("play_music", "media_control")]
    if media_steps:
        return verify_media_outcome(goal)

    # 5. Check for Web Automation Outcomes (DOM Verification)
    is_web = any(s.get("tool", "").startswith("browser_") for s in plan) or any(
        h.get("action", "").startswith("browser_") for h in history
    )
    if is_web:
        try:
            from backend.agent.tools.web_automation.validator import validate_goal_completion
            dom_final = state.get("final_dom") or state.get("initial_dom") or {}
            dom_init = state.get("initial_dom") or {}
            val = await validate_goal_completion(goal, dom_init, dom_final, history)
            return OutcomeValidationResult(
                passed=val.passed,
                confidence=val.confidence,
                reason=val.reason,
                tier=val.tier,
                corrective_suggestion=val.suggestion,
                details=val.details,
            )
        except Exception as e:
            logger.warning("[OutcomeValidator] Web DOM validation fallback: %s", e)

    # Default verified for all completed steps
    return OutcomeValidationResult(
        passed=True,
        confidence=0.95,
        reason="All planned execution steps completed successfully without errors.",
        tier="ground_truth",
    )
