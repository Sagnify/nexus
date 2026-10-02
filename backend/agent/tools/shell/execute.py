"""Shell command execution tool."""
from __future__ import annotations
import asyncio
import os
import subprocess
import sys
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel, classify_command


import re
import shlex
import shutil
import ctypes


def _is_admin() -> bool:
    """Check if running with admin privileges on Windows."""
    try:
        return ctypes.windll.shell.IsUserAnAdmin()
    except Exception:
        return False


def _needs_elevation(command: str) -> bool:
    """Check if command requires admin elevation."""
    cmd_lower = command.lower()
    elevation_keywords = (
        "clear-recyclebin", "taskkill", "stop-process", "net stop", "sc stop",
        "remove-item", "rm-item", "format", "diskpart", "shutdown", "reboot"
    )
    return any(kw in cmd_lower for kw in elevation_keywords)


def _normalize_target_url(token: str) -> str:
    """Ensure a web URL has http:// or https:// prefix if it looks like a domain."""
    cleaned = token.strip("\"'")
    if re.match(r"^https?://", cleaned, re.I):
        return cleaned
    if cleaned.startswith("www.") or re.match(r"^[a-zA-Z0-9-]+\.(com|org|net|io|edu|gov|co|ai|app|dev|in|me|gg|tv)(/.*)?$", cleaned, re.I):
        return f"https://{cleaned}"
    return cleaned


def resolve_system_app(command: str) -> tuple[bool, list[str] | str]:
    """Check if command is launching a known desktop application on Windows."""
    raw_cmd = command.strip()
    cmd_lower = raw_cmd.lower()

    # Strip leading 'start '
    cmd_body = re.sub(r"^start\s+", "", raw_cmd, flags=re.IGNORECASE).strip()
    try:
        tokens = shlex.split(cmd_body, posix=False)
    except Exception:
        tokens = cmd_body.split()

    if not tokens:
        return False, command

    app_token = tokens[0].lower().replace(".exe", "").strip("\"'")
    rest_args = tokens[1:]

    # Google Chrome
    if app_token in ("chrome", "google-chrome") or "chrome" in app_token:
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ]
        exe = next((p for p in chrome_paths if os.path.exists(p)), None) or shutil.which("chrome") or "chrome"
        final_args = [exe]

        has_incognito = any(a.lower().strip("\"'") in ("--incognito", "-incognito", "/incognito") for a in rest_args)
        if ("incognito" in cmd_lower or "private" in cmd_lower) and not has_incognito:
            final_args.append("--incognito")

        for arg in rest_args:
            arg_lower = arg.lower().strip("\"'")
            if arg_lower in ("--incognito", "-incognito", "/incognito"):
                if "--incognito" not in final_args:
                    final_args.append("--incognito")
            else:
                final_args.append(_normalize_target_url(arg))
        return True, final_args

    # Microsoft Edge
    if app_token in ("edge", "msedge", "microsoft-edge") or "edge" in app_token or "msedge" in app_token:
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        ]
        exe = next((p for p in edge_paths if os.path.exists(p)), None) or shutil.which("msedge") or "msedge"
        final_args = [exe]

        has_inprivate = any(a.lower().strip("\"'") in ("-inprivate", "--inprivate", "/inprivate", "-incognito", "--incognito") for a in rest_args)
        if ("inprivate" in cmd_lower or "incognito" in cmd_lower or "private" in cmd_lower) and not has_inprivate:
            final_args.append("-inprivate")

        for arg in rest_args:
            arg_lower = arg.lower().strip("\"'")
            if arg_lower in ("-inprivate", "--inprivate", "/inprivate", "-incognito", "--incognito"):
                if "-inprivate" not in final_args:
                    final_args.append("-inprivate")
            else:
                final_args.append(_normalize_target_url(arg))
        return True, final_args

    # Brave Browser
    if app_token in ("brave", "brave-browser") or "brave" in app_token:
        brave_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        exe = next((p for p in brave_paths if os.path.exists(p)), None) or shutil.which("brave")
        if exe:
            final_args = [exe]
            if "incognito" in cmd_lower or "private" in cmd_lower:
                final_args.append("--incognito")
            for arg in rest_args:
                if arg.lower().strip("\"'") not in ("--incognito", "-incognito"):
                    final_args.append(_normalize_target_url(arg))
            return True, final_args

    # Notepad
    if app_token == "notepad":
        return True, ["notepad.exe"] + [a.strip("\"'") for a in rest_args]

    # Calculator
    if app_token in ("calc", "calculator"):
        return True, ["calc.exe"]

    if cmd_lower.startswith("start "):
        return True, command

    return False, command


class RunCommandTool(NexusTool):
    name = "run_command"
    description = "Execute a shell command in the operating system."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, command: str, cwd: str | None = None, timeout: int = 30, **_) -> ToolResult:
        try:
            working_dir = cwd or os.getcwd()

            if sys.platform == "win32":
                is_app, app_target = resolve_system_app(command)
                if is_app:
                    if isinstance(app_target, list):
                        subprocess.Popen(app_target, cwd=working_dir)
                    else:
                        subprocess.Popen(app_target, shell=True, cwd=working_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return ToolResult(
                        success=True,
                        output=f"Successfully launched application: {command}",
                        error="",
                        metadata={"command": command, "cwd": working_dir}
                    )

            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds.",
                    output=""
                )

            stdout = stdout_bytes.decode(errors="replace").strip()
            stderr = stderr_bytes.decode(errors="replace").strip()
            exit_code = proc.returncode

            combined_output = stdout
            if stderr:
                if combined_output:
                    combined_output += f"\n[stderr]\n{stderr}"
                else:
                    combined_output = f"[stderr]\n{stderr}"

            success = (exit_code == 0)
            
            if not success and exit_code in (1, 5) and _needs_elevation(command) and sys.platform == "win32":
                if not _is_admin():
                    elevated_cmd = f'powershell.exe -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList \'\'-NoProfile -Command {shlex.quote(command)}\' -Wait"'
                    try:
                        proc_elevated = await asyncio.create_subprocess_shell(
                            elevated_cmd,
                            cwd=working_dir,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc_elevated.communicate(), timeout=timeout)
                        stdout = stdout_bytes.decode(errors="replace").strip()
                        stderr = stderr_bytes.decode(errors="replace").strip()
                        exit_code = proc_elevated.returncode
                        success = (exit_code == 0)
                        combined_output = stdout
                        if stderr:
                            if combined_output:
                                combined_output += f"\n[stderr]\n{stderr}"
                            else:
                                combined_output = f"[stderr]\n{stderr}"
                    except Exception as e:
                        return ToolResult(
                            success=False,
                            error=f"Elevation retry failed: {e}",
                            output=combined_output
                        )
            
            return ToolResult(
                success=success,
                output=combined_output if combined_output else "(no output)",
                error="" if success else f"Command exited with code {exit_code}",
                metadata={"exit_code": exit_code, "command": command, "cwd": working_dir}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), output="")
