"""Hardware and GUI automation tools using pyautogui and win32gui."""
from __future__ import annotations
import asyncio
import os
import sys
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel

try:
    import pyautogui
    # Configure safety delay
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def _find_window_by_title(title_query: str) -> int | None:
    """Find a window handle matching the title query."""
    if not HAS_WIN32:
        return None

    matches = []

    def enum_windows_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            win_text = win32gui.GetWindowText(hwnd)
            if win_text and title_query.lower() in win_text.lower():
                matches.append(hwnd)

    win32gui.EnumWindows(enum_windows_callback, None)
    return matches[0] if matches else None


class ActivateWindowTool(NexusTool):
    name = "activate_window"
    description = "Find and bring a desktop application window to the foreground (e.g., 'Chrome', 'Notepad', 'Code')."
    risk_level = RiskLevel.SAFE

    async def execute(self, title: str, **_) -> ToolResult:
        def _activate():
            try:
                import win32com.client
                wscript = win32com.client.Dispatch("WScript.Shell")
                success = wscript.AppActivate(title)
                if success:
                    return True, f"Brought window matching '{title}' to the foreground."
                return True, f"Sent focus activation for '{title}' window."
            except Exception as e:
                return False, f"Could not activate window: {e}"

        success, message = await asyncio.to_thread(_activate)
        return ToolResult(
            success=success,
            output=message if success else "",
            error="" if success else message
        )


class PressHotkeyTool(NexusTool):
    name = "press_hotkey"
    description = "Simulate hardware keyboard shortcuts / hotkeys (e.g., keys: ['ctrl', 'shift', 'n'] or shortcut: 'ctrl+shift+n')."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, keys: list[str] | None = None, shortcut: str | None = None, **_) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(
                success=False,
                error="pyautogui is not installed in the Python environment.",
                output=""
            )

        key_list = []
        if keys:
            key_list = [k.lower().strip() for k in keys]
        elif shortcut:
            key_list = [k.lower().strip() for k in shortcut.replace("-", "+").split("+")]

        if not key_list:
            return ToolResult(success=False, error="No hotkey or keys provided.", output="")

        def _press():
            try:
                pyautogui.hotkey(*key_list)
                return True, f"Pressed hardware hotkey: {' + '.join(key_list)}"
            except Exception as e:
                return False, f"Failed to press hotkey: {e}"

        success, message = await asyncio.to_thread(_press)
        return ToolResult(
            success=success,
            output=message if success else "",
            error="" if success else message,
            metadata={"keys": key_list}
        )


class TypeTextTool(NexusTool):
    name = "type_text"
    description = "Content-aware physical keyboard typing. Visually locates the input box with VLM, dismisses any blocking overlays, clicks to focus, selects existing placeholder text with Ctrl+A, and types into the right place."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, target: str | None = None, interval: float = 0.02, **_) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(
                success=False,
                error="pyautogui is not installed.",
                output=""
            )

        if not text:
            return ToolResult(success=False, error="No text provided to type.", output="")

        grounding_meta = None
        if target:
            from backend.agent.tools.gui.screen import vlm_ground_target, vlm_detect_and_dismiss_overlay
            grounding = await vlm_ground_target(target)
            if not grounding.get("found"):
                # Blocking overlay might be obscuring the field
                dismiss_info = await vlm_detect_and_dismiss_overlay()
                if dismiss_info.get("dismissed"):
                    await asyncio.sleep(0.5)
                    grounding = await vlm_ground_target(target)

            if not grounding.get("found"):
                # Proactively dismiss overlay once more if still not found
                dismiss_info = await vlm_detect_and_dismiss_overlay()
                if dismiss_info.get("dismissed"):
                    await asyncio.sleep(0.5)
                    grounding = await vlm_ground_target(target)

            if not grounding.get("found"):
                return ToolResult(
                    success=False,
                    error=f"Visual perception (Qwen VLM) could not find target input field '{target}' on screen to type into.",
                    output="",
                    metadata={"target": target, "grounding": grounding}
                )

            x, y = grounding["x"], grounding["y"]
            grounding_meta = grounding

            def _focus_target():
                pyautogui.moveTo(x, y, duration=0.25)
                pyautogui.click(x, y)
                pyautogui.sleep(0.15)
                # Select all existing placeholder text (e.g. "Untitled Question", "Untitled form")
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.sleep(0.05)

            await asyncio.to_thread(_focus_target)
            await asyncio.sleep(0.1)
        else:
            # If no target specified, check if an overlay is blocking before typing
            from backend.agent.tools.gui.screen import vlm_detect_and_dismiss_overlay
            await vlm_detect_and_dismiss_overlay()

        def _type():
            try:
                pyautogui.write(text, interval=interval)
                target_str = f" into '{target}'" if target else ""
                return True, f"Typed {len(text)} character(s){target_str}."
            except Exception as e:
                return False, f"Failed to type text: {e}"

        success, message = await asyncio.to_thread(_type)
        meta = {}
        if grounding_meta:
            meta["grounding"] = grounding_meta

        return ToolResult(
            success=success,
            output=message if success else "",
            error="" if success else message,
            metadata=meta
        )


class PressKeyTool(NexusTool):
    name = "press_key"
    description = "Press a single hardware key (e.g. 'enter', 'esc', 'tab', 'backspace', 'up', 'down')."
    risk_level = RiskLevel.SAFE

    async def execute(self, key: str, presses: int = 1, **_) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(success=False, error="pyautogui is not installed.", output="")

        def _press():
            try:
                pyautogui.press(key.lower().strip(), presses=presses)
                return True, f"Pressed key '{key}' {presses} time(s)."
            except Exception as e:
                return False, f"Failed to press key: {e}"

        success, message = await asyncio.to_thread(_press)
        return ToolResult(
            success=success,
            output=message if success else "",
            error="" if success else message
        )


class ClickMouseTool(NexusTool):
    name = "click_mouse"
    description = "Move cursor and click on screen coordinates (x, y) or visually ground and click a named UI target (e.g. target='circle with plus sign to add question')."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        x: int | None = None,
        y: int | None = None,
        target: str | None = None,
        wait_seconds: float = 0.0,
        button: str = "left",
        clicks: int = 1,
        **_
    ) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(success=False, error="pyautogui is not installed.", output="")

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        grounding_meta = None
        if (x is None or y is None) and target:
            try:
                from backend.api.nexus import push_event
                await push_event(None, "status", {"status": "executing", "message": f"Locating '{target[:30]}' with VLM perception..."})
            except Exception:
                pass
            from backend.agent.tools.gui.screen import vlm_ground_target, vlm_detect_and_dismiss_overlay
            grounding = await vlm_ground_target(target)
            if not grounding.get("found"):
                # Content-aware: Check if a blocking overlay is covering the UI and dismiss it
                dismiss_info = await vlm_detect_and_dismiss_overlay()
                if dismiss_info.get("dismissed"):
                    await asyncio.sleep(0.5)
                    grounding = await vlm_ground_target(target)

            # Safety check: if y < 75 (in browser tab / address bar strip) and target is a form element, reject bogus coordinate
            if grounding.get("found") and grounding.get("y", 0) < 75 and any(w in target.lower() for w in ("question", "form", "plus", "add", "field", "input")):
                dismiss_info = await vlm_detect_and_dismiss_overlay()
                if dismiss_info.get("dismissed"):
                    await asyncio.sleep(0.5)
                    grounding = await vlm_ground_target(target)

            if not grounding.get("found"):
                # Retry once after a brief delay in case page/element was still rendering
                await asyncio.sleep(0.8)
                grounding = await vlm_ground_target(target)

            if not grounding.get("found"):
                err_msg = f"Visual perception (Qwen VLM) could not find '{target}' on screen: {grounding.get('error', 'not visible')}"
                try:
                    import datetime
                    from backend.api.nexus import pause_task, push_event
                    await push_event(None, "issue", {
                        "type": "target_not_found",
                        "message": err_msg,
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                    })
                    await pause_task()
                except Exception:
                    pass

                return ToolResult(
                    success=False,
                    error=err_msg,
                    output="",
                    metadata={"target": target, "grounding": grounding, "paused": True}
                )
            x = grounding["x"]
            y = grounding["y"]
            grounding_meta = grounding
            try:
                from backend.api.nexus import push_event
                await push_event(None, "status", {"status": "executing", "message": f"Clicking '{target[:25]}' at ({x}, {y})..."})
            except Exception:
                pass

        if x is None or y is None:
            return ToolResult(
                success=False,
                error="Please provide either screen coordinates (x, y) or a visual target description (target='...').",
                output=""
            )

        def _click():
            try:
                # Move cursor smoothly to target
                pyautogui.moveTo(x, y, duration=0.28)
                # Realistic human hover pause before click
                pyautogui.sleep(0.06)
                for i in range(clicks):
                    pyautogui.mouseDown(x=x, y=y, button=button)
                    pyautogui.sleep(0.04)  # Natural physical button hold duration
                    pyautogui.mouseUp(x=x, y=y, button=button)
                    if i < clicks - 1:
                        pyautogui.sleep(0.08)
                target_str = f" for '{target}'" if target else ""
                return True, f"Clicked mouse {button} button at ({x}, {y}){target_str} {clicks} time(s)."
            except Exception as e:
                return False, f"Failed to click mouse: {e}"

        success, message = await asyncio.to_thread(_click)
        meta = {"x": x, "y": y, "target": target}
        if grounding_meta:
            meta["grounding"] = grounding_meta

        return ToolResult(
            success=success,
            output=message if success else "",
            error="" if success else message,
            metadata=meta
        )
