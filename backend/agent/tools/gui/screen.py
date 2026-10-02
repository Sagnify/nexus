"""Screen perception and VLM inspection tool."""
from __future__ import annotations
import asyncio
import base64
import io
import json
import os
import re
import sys
from pathlib import Path
import httpx
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.core.config import get_groq_api_key, get_groq_model, get_gemma_api_key

try:
    import pyautogui
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def _capture_live_screen() -> tuple[bytes | None, Path]:
    """Capture fresh screen snapshot, saving to ~/.nexus/screens/latest_screen.png with fallback."""
    screens_dir = Path.home() / ".nexus" / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    shot_file = screens_dir / "latest_screen.png"

    if HAS_PYAUTOGUI:
        try:
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()
            shot_file.write_bytes(data)
            return data, shot_file
        except Exception:
            pass

    if shot_file.exists():
        return shot_file.read_bytes(), shot_file

    return None, shot_file


def _find_green_button_coords(image_bytes: bytes, screen_w: int, screen_h: int) -> dict | None:
    """Fast connected-component detector for Spotify circular green play button (#1ed760)."""
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        ih, iw, _ = arr.shape
        # Spotify green: R < 100, G > 170, B < 130
        mask = (arr[:, :, 1] > 170) & (arr[:, :, 0] < 100) & (arr[:, :, 2] < 130)
        # Ignore top 9% (nav/search bar) and bottom 14% (player bar)
        mask[:int(ih * 0.09), :] = False
        mask[int(ih * 0.86):, :] = False

        try:
            import scipy.ndimage as ndi
            labels, num_features = ndi.label(mask)
            best_center = None
            max_size = 0
            for i in range(1, num_features + 1):
                pts = np.where(labels == i)
                size = len(pts[0])
                if size >= 100:  # Button circle
                    cy = int(np.mean(pts[0]))
                    cx = int(np.mean(pts[1]))
                    if size > max_size:
                        max_size = size
                        best_center = (cx, cy)
            if best_center:
                cx, cy = best_center
                xp = (cx / iw) * 100.0
                yp = (cy / ih) * 100.0
                real_x = int(round((xp / 100.0) * screen_w))
                real_y = int(round((yp / 100.0) * screen_h))
                return {
                    "found": True,
                    "x": real_x,
                    "y": real_y,
                    "x_percent": xp,
                    "y_percent": yp,
                    "description": "Circular green play button",
                }
        except ImportError:
            pass
    except Exception:
        pass
    return None


def _extract_json_object(raw_content: str | None) -> dict:
    """Extract a JSON object from a model response, even if the reply includes extra prose."""
    if not raw_content:
        return {}
    match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0), strict=False)
    except Exception:
        return {}


async def _call_gemma_vlm(prompt: str, data_url: str, fallback_models: list[str] | None = None) -> str:
    """Try Google AI Studio vision-capable models as a fallback when Groq VLM is unavailable."""
    gemma_key = get_gemma_api_key()
    if not gemma_key:
        raise RuntimeError("Gemma API key not configured.")

    candidates = fallback_models or [
        "gemma-4-26b-a4b-it",
        "gemini-3.8-flash",
    ]
    last_error = None

    for model_name in candidates:
        clean_model = model_name.replace("google/", "").replace("models/", "")
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "image/jpeg", "data": data_url.split(",", 1)[1] if "," in data_url else data_url}},
                ],
            }],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(url, json=payload, headers={"x-goog-api-key": gemma_key})
                if response.status_code != 200:
                    last_error = RuntimeError(f"Gemma VLM error ({response.status_code}): {response.text[:200]}")
                    continue
                data = response.json()
                parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
                texts = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
                if texts:
                    return "\n".join(texts).strip()
                if parts:
                    text = str(parts[0]).strip()
                    if text:
                        return text
                last_error = RuntimeError(f"Gemma VLM response from model '{model_name}' did not include usable text.")
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("No Gemma VLM model produced a usable response.")


async def vlm_ground_target(
    target_description: str,
    screenshot_path: str | Path | None = None,
    image_bytes: bytes | None = None,
    wait_seconds: float = 0.0,
    check_overlay_first: bool = True,
) -> dict:
    """Use Groq Qwen VLM + visual perception to ground a UI element and return physical coordinates."""
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)

    # Obtain fresh screenshot bytes
    if image_bytes is None:
        if screenshot_path:
            p = Path(screenshot_path)
            if p.exists():
                image_bytes = p.read_bytes()
        if image_bytes is None:
            image_bytes, _ = _capture_live_screen()

    if not image_bytes:
        return {"found": False, "error": "No screenshot available for VLM perception"}

    try:
        from backend.api.nexus import push_event
        await push_event(None, "status", {"status": "executing", "message": f"Analyzing screen snapshot with VLM for '{target_description[:32]}'..."})
    except Exception:
        pass

    # Screen dimensions
    screen_w, screen_h = pyautogui.size() if HAS_PYAUTOGUI else (1920, 1080)

    # Fast precision check for Spotify green play button
    if any(w in target_description.lower() for w in ("green", "spotify", "play button", "play icon")):
        green_res = _find_green_button_coords(image_bytes, screen_w, screen_h)
        if green_res and green_res.get("found"):
            try:
                from backend.api.nexus import push_event
                await push_event(None, "status", {"status": "executing", "message": f"Found green play button at ({green_res['x']}, {green_res['y']})"})
            except Exception:
                pass
            return green_res

    api_key = get_groq_api_key()
    if not api_key and not get_gemma_api_key():
        return {"found": False, "error": "Groq/Gemma API key not configured"}

    # Convert to base64 data URL
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    prompt = (
        f"You are a GUI visual perception and UI grounding agent.\n"
        f"User display resolution is {screen_w}x{screen_h}.\n"
        f"Target element to find: '{target_description}'.\n"
        f"Analyze the image and locate the UI element, button, input box, or icon matching this description.\n"
        f"Visual grounding guidelines:\n"
        f"1. For 'add question' or 'plus button', look for the '+' icon button, circular '+' button, or action toolbar on the form card.\n"
        f"2. For question or title inputs, look for question field boxes, 'Untitled Question', 'Untitled form', or active editable text areas.\n"
        f"3. Do NOT return coordinates in the top browser tabs/address bar (y_percent MUST be >= 8.0%). Elements are inside the web page.\n"
        f"4. If a modal/dialog overlay (such as Google Gemini 'Hello / Let's start creating' modal) is covering the screen and blocking the target, return: {{\"found\": false, \"blocked_by_overlay\": true, \"description\": \"blocked by overlay modal\"}}.\n"
        f"5. Estimate the center coordinates as a percentage of width (x: 0 to 100) and height (y: 0 to 100).\n"
        f"Respond strictly in JSON format:\n"
        f"{{\"found\": true, \"x_percent\": <number 0-100>, \"y_percent\": <number 0-100>, \"description\": \"<brief description>\"}}\n"
        f"If the element is not visible on screen, return: {{\"found\": false, \"blocked_by_overlay\": false, \"description\": \"not visible\"}}"
    )

    def _call_groq_vlm(user_prompt: str, current_data_url: str):
        from groq import Groq
        client = Groq(api_key=api_key)
        vision_model = get_groq_model("vision") or "qwen/qwen3.8-27b"
        res = client.chat.completions.create(
            model=vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": current_data_url}},
                ]
            }],
            max_tokens=150,
            temperature=0.1,
        )
        return res.choices[0].message.content

    try:
        try:
            raw_content = await asyncio.to_thread(_call_groq_vlm, prompt, data_url)
            parsed = _extract_json_object(raw_content)
        except Exception as groq_exc:
            parsed = {}
            raw_content = None
            if get_gemma_api_key():
                try:
                    raw_content = await _call_gemma_vlm(prompt, data_url)
                    parsed = _extract_json_object(raw_content)
                except Exception as gemma_exc:
                    return {"found": False, "error": f"Groq VLM failed ({groq_exc}); Gemma VLM fallback failed ({gemma_exc})"}
            else:
                return {"found": False, "error": str(groq_exc)}

        # If blocked by overlay or not found, proactively detect and dismiss overlay, then retry once
        if (parsed.get("blocked_by_overlay") or not parsed.get("found")) and check_overlay_first:
            dismiss_res = await vlm_detect_and_dismiss_overlay()
            if dismiss_res.get("dismissed"):
                await asyncio.sleep(0.5)
                # Fresh capture after dismissing modal
                new_bytes, _ = _capture_live_screen()
                if new_bytes:
                    new_b64 = base64.b64encode(new_bytes).decode("utf-8")
                    new_data_url = f"data:image/jpeg;base64,{new_b64}"
                    try:
                        raw_retry = await asyncio.to_thread(_call_groq_vlm, prompt, new_data_url)
                    except Exception:
                        raw_retry = None
                    if raw_retry:
                        retry_match = re.search(r"\{.*\}", raw_retry, re.DOTALL)
                        if retry_match:
                            parsed = json.loads(retry_match.group(0), strict=False)
                    elif get_gemma_api_key():
                        try:
                            raw_retry = await _call_gemma_vlm(prompt, new_data_url)
                            parsed = _extract_json_object(raw_retry)
                        except Exception:
                            parsed = {}

        # If not found and target mentions plus or add, try specialized fallback query
        if not parsed.get("found") and any(w in target_description.lower() for w in ("plus", "add", "question")):
            fallback_prompt = (
                f"Locate any '+' or plus button, circle with plus sign, or add question button on the web page. Display: {screen_w}x{screen_h}.\n"
                f"Coordinates must be on the page canvas (y_percent >= 10.0).\n"
                f"Respond in JSON: {{\"found\": true, \"x_percent\": <0-100>, \"y_percent\": <0-100>, \"description\": \"plus icon\"}} or {{\"found\": false}}"
            )
            try:
                raw_fallback = await asyncio.to_thread(_call_groq_vlm, fallback_prompt, data_url)
            except Exception:
                raw_fallback = None
            if raw_fallback:
                fb_match = re.search(r"\{.*\}", raw_fallback, re.DOTALL)
                if fb_match:
                    parsed = json.loads(fb_match.group(0), strict=False)
            elif get_gemma_api_key():
                try:
                    raw_fallback = await _call_gemma_vlm(fallback_prompt, data_url)
                    parsed = _extract_json_object(raw_fallback)
                except Exception:
                    parsed = {}

        if parsed.get("found"):
            xp = float(parsed.get("x_percent", parsed.get("x", 50)))
            yp = float(parsed.get("y_percent", parsed.get("y", 50)))

            # Discard bogus coordinates located in browser tab/header strip
            if yp < 7.0 and any(w in target_description.lower() for w in ("question", "form", "plus", "add", "field", "title")):
                return {"found": False, "error": f"Detected element was in browser chrome ({xp}%, {yp}%), not on page canvas"}

            if xp > 100 or yp > 100:
                real_x = int(xp)
                real_y = int(yp)
            else:
                real_x = int(round((xp / 100.0) * screen_w))
                real_y = int(round((yp / 100.0) * screen_h))

            real_x = max(0, min(screen_w - 1, real_x))
            real_y = max(0, min(screen_h - 1, real_y))

            return {
                "found": True,
                "x": real_x,
                "y": real_y,
                "x_percent": xp,
                "y_percent": yp,
                "description": parsed.get("description", target_description),
            }
    except Exception as e:
        return {"found": False, "error": str(e)}

    return {"found": False, "error": "Element not found on screen"}


async def vlm_detect_and_dismiss_overlay() -> dict:
    """Detect if an active modal, dialog, or popup overlay (e.g. Google Gemini welcome dialog) is blocking the UI and dismiss it."""
    if not HAS_PYAUTOGUI:
        return {"dismissed": False, "reason": "pyautogui not available"}

    api_key = get_groq_api_key()
    if not api_key and not get_gemma_api_key():
        return {"dismissed": False, "reason": "Groq/Gemma API key not configured"}

    image_bytes, _ = _capture_live_screen()
    if not image_bytes:
        return {"dismissed": False, "reason": "Screenshot capture failed"}

    screen_w, screen_h = pyautogui.size()
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    prompt = (
        f"Analyze this screen. Display resolution: {screen_w}x{screen_h}.\n"
        f"Is there an active modal, dialog, banner, or popup overlay covering or blocking the main application (for example: Google Gemini 'Hello / Let's start creating' modal, cookie consent, welcome tour, sign-in popup)?\n"
        f"If an overlay is present, locate its close button ('X' icon, 'Close', 'Skip', or 'Dismiss') as percentage coordinates (x: 0-100, y: 0-100).\n"
        f"Respond strictly in JSON format:\n"
        f"{{\"has_overlay\": true, \"overlay_title\": \"<brief title>\", \"close_button\": {{\"x_percent\": <0-100>, \"y_percent\": <0-100>}}}}\n"
        f"If no overlay is visible or blocking, return: {{\"has_overlay\": false}}"
    )

    def _call_groq():
        from groq import Groq
        client = Groq(api_key=api_key)
        vision_model = get_groq_model("vision") or "qwen/qwen3.8-27b"
        res = client.chat.completions.create(
            model=vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
            }],
            max_tokens=150,
            temperature=0.1,
        )
        return res.choices[0].message.content

    try:
        if api_key:
            raw_content = await asyncio.to_thread(_call_groq)
        else:
            raw_content = await _call_gemma_vlm(prompt, data_url)
        parsed = _extract_json_object(raw_content)
        if parsed:
            if parsed.get("has_overlay") and parsed.get("close_button"):
                cb = parsed["close_button"]
                xp = float(cb.get("x_percent", 78.5))
                yp = float(cb.get("y_percent", 12.5))
                real_x = int(round((xp / 100.0) * screen_w))
                real_y = int(round((yp / 100.0) * screen_h))
                real_x = max(0, min(screen_w - 1, real_x))
                real_y = max(0, min(screen_h - 1, real_y))

                def _click_close():
                    pyautogui.moveTo(real_x, real_y, duration=0.25)
                    pyautogui.click(real_x, real_y)
                    # Also press Escape as secondary guarantee to dismiss any dialog
                    pyautogui.press('esc')

                await asyncio.to_thread(_click_close)
                await asyncio.sleep(0.6)

                # Update live screenshot after closing modal
                _capture_live_screen()

                return {
                    "dismissed": True,
                    "overlay_title": parsed.get("overlay_title", "Modal overlay"),
                    "x": real_x,
                    "y": real_y
                }
    except Exception as e:
        return {"dismissed": False, "error": str(e)}

    return {"dismissed": False}


async def vlm_inspect_and_click(
    target_description: str,
    task_id: str | None = None,
    clicks: int = 1,
    button: str = "left",
    pause_on_failure: bool = True
) -> dict:
    """Takes a live screen snapshot, sends to VLM for visual grounding coordinates, moves cursor and clicks.
    If target is not found or fails, automatically registers an issue and pauses automation like the web pill.
    """
    if not HAS_PYAUTOGUI:
        return {"success": False, "error": "pyautogui is not installed"}

    # 1. Take fresh snapshot and ground target with VLM
    try:
        from backend.api.nexus import push_event
        await push_event(task_id, "status", {"status": "executing", "message": f"Taking screen snapshot for '{target_description[:30]}'..."})
    except Exception:
        pass
    grounding = await vlm_ground_target(target_description)

    # 2. Check if blocking overlay is obscuring it
    if not grounding.get("found"):
        dismiss = await vlm_detect_and_dismiss_overlay()
        if dismiss.get("dismissed"):
            await asyncio.sleep(0.5)
            grounding = await vlm_ground_target(target_description)

    # 3. If found, smoothly move cursor and click
    if grounding.get("found"):
        x = grounding["x"]
        y = grounding["y"]

        try:
            from backend.api.nexus import push_event
            await push_event(task_id, "status", {"status": "executing", "message": f"Clicking '{target_description[:25]}' at ({x}, {y})..."})
        except Exception:
            pass

        def _perform_click():
            pyautogui.moveTo(x, y, duration=0.25)
            pyautogui.sleep(0.06)
            for i in range(clicks):
                pyautogui.mouseDown(x=x, y=y, button=button)
                pyautogui.sleep(0.04)
                pyautogui.mouseUp(x=x, y=y, button=button)
                if i < clicks - 1:
                    pyautogui.sleep(0.08)

        await asyncio.to_thread(_perform_click)
        return {
            "success": True,
            "x": x,
            "y": y,
            "grounding": grounding,
            "message": f"Moved cursor and clicked '{target_description}' at ({x}, {y})",
        }

    # 4. If not found, log issue and automatically pause task
    err_msg = f"Visual perception (VLM) could not locate '{target_description}' on screen."
    if pause_on_failure:
        try:
            import datetime
            from backend.api.nexus import pause_task, push_event
            await push_event(task_id, "issue", {
                "type": "target_not_found",
                "message": err_msg,
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
            })
            await pause_task(task_id)
        except Exception:
            pass

    return {
        "success": False,
        "error": err_msg,
        "grounding": grounding,
    }


def _get_active_window_info() -> dict:
    """Retrieve title, dimensions, and process of the currently focused window on Windows."""
    if not HAS_WIN32 or sys.platform != "win32":
        return {}

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {}
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return {
            "title": title,
            "bounds": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
            "width": rect[2] - rect[0],
            "height": rect[3] - rect[1],
            "pid": pid,
        }
    except Exception:
        return {}


def _get_visible_windows() -> list[str]:
    """Retrieve titles of visible top-level windows."""
    if not HAS_WIN32 or sys.platform != "win32":
        return []

    titles = []

    def enum_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd).strip()
            if text and text not in ("Program Manager", "Settings", ""):
                titles.append(text)
        return True

    try:
        win32gui.EnumWindows(enum_callback, None)
    except Exception:
        pass

    return titles[:10]


class InspectScreenTool(NexusTool):
    name = "inspect_screen"
    description = "Capture and analyze current display state, active foreground window, cursor coordinates, and visible desktop elements before taking hardware action."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, save_screenshot: bool = True, target: str | None = None, query: str | None = None, wait_seconds: float = 0.0, **_) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(
                success=False,
                error="pyautogui is not available for screen perception.",
                output=""
            )

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        try:
            from backend.api.nexus import push_event
            await push_event(None, "status", {"status": "executing", "message": "Inspecting live screen snapshot..."})
        except Exception:
            pass

        def _inspect():
            # Screen geometry & cursor
            screen_w, screen_h = pyautogui.size()
            cursor_x, cursor_y = pyautogui.position()

            # Active window info
            active_win = _get_active_window_info()
            visible_apps = _get_visible_windows()

            screenshot_path = ""
            if save_screenshot or target or query:
                try:
                    screens_dir = Path.home() / ".nexus" / "screens"
                    screens_dir.mkdir(parents=True, exist_ok=True)
                    screenshot_file = screens_dir / "latest_screen.png"
                    img = pyautogui.screenshot()
                    img.save(str(screenshot_file))
                    screenshot_path = str(screenshot_file)
                except Exception:
                    pass

            lines = [
                f"Screen Resolution: {screen_w}x{screen_h}",
                f"Current Cursor Position: ({cursor_x}, {cursor_y})",
            ]

            if active_win and active_win.get("title"):
                b = active_win.get("bounds", {})
                lines.append(
                    f"Active Foreground Window: '{active_win['title']}' "
                    f"[Rect: left={b.get('left')}, top={b.get('top')}, size={active_win.get('width')}x{active_win.get('height')}]"
                )
            else:
                lines.append("Active Foreground Window: None detected or desktop focused")

            if visible_apps:
                lines.append(f"Visible Top-Level Windows: {', '.join(visible_apps[:6])}")

            if screenshot_path:
                lines.append(f"Visual Snapshot Saved: {screenshot_path}")

            return "\n".join(lines), screenshot_path

        output_text, shot_path = await asyncio.to_thread(_inspect)
        meta = {"screen_inspected": True}

        # If a visual target or query was requested, run Qwen VLM perception
        search_target = target or query
        if search_target and shot_path:
            grounding = await vlm_ground_target(search_target, screenshot_path=shot_path)
            if grounding.get("found"):
                output_text += f"\nVisual Grounding (Qwen VLM): Found '{search_target}' at coordinates ({grounding['x']}, {grounding['y']}) [{grounding.get('description', '')}]"
                meta["grounding"] = grounding
            else:
                output_text += f"\nVisual Grounding (Qwen VLM): '{search_target}' not visually detected on screen."

        return ToolResult(
            success=True,
            output=output_text,
            error="",
            metadata=meta
        )


class DismissOverlayTool(NexusTool):
    name = "dismiss_overlay"
    description = "Content-aware screen perception tool to detect and close blocking overlays, modal dialogs, AI welcome prompts (e.g. Google Gemini popup), or cookie banners by clicking their close 'X' button or sending Escape."
    risk_level = RiskLevel.SAFE

    async def execute(self, **_) -> ToolResult:
        res = await vlm_detect_and_dismiss_overlay()
        if res.get("dismissed"):
            return ToolResult(
                success=True,
                output=f"Content-aware VLM detected and dismissed overlay: '{res.get('overlay_title')}' at ({res.get('x')}, {res.get('y')}).",
                error="",
                metadata=res
            )
        # If no overlay was found via VLM, press Escape as a fallback safety measure
        if HAS_PYAUTOGUI:
            pyautogui.press('esc')
            return ToolResult(
                success=True,
                output="No blocking modal overlay detected by VLM; sent Escape key to ensure clean canvas.",
                error=""
            )
        return ToolResult(
            success=True,
            output="No blocking overlay detected.",
            error=""
        )
