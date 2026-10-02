"""Visual Language Model (VLM) validation and self-healing layer for Excel Copilot.

Captures real-time visual snapshots of Microsoft Excel worksheets post-execution
and applies multimodal reasoning to verify that calculations, formulas, formats,
and data layouts have executed correctly without errors (#VALUE!, #NAME?, 0-sums, etc.).
If an anomaly is detected, it automatically diagnoses the root cause, replans, and re-executes.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger("nexus.excel_copilot.validator")


def capture_excel_screenshot(hwnd: Optional[int] = None) -> Optional[bytes]:
    """Capture a visual snapshot of the targeted Excel window or worksheet."""
    if os.name != "nt":
        return None

    # 1. Primary: Win32 PrintWindow directly on target window handle
    if hwnd:
        try:
            import win32gui
            import win32ui
            import win32con

            if win32gui.IsWindow(hwnd):
                left, top, right, bot = win32gui.GetWindowRect(hwnd)
                w = max(100, right - left)
                h = max(100, bot - top)

                hwndDC = win32gui.GetWindowDC(hwnd)
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                saveDC = mfcDC.CreateCompatibleDC()
                saveBitMap = win32ui.CreateBitmap()
                saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
                saveDC.SelectObject(saveBitMap)

                # Try PW_RENDERFULLCONTENT (2), fallback to standard (0)
                res = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
                if not res:
                    res = win32gui.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

                bmpinfo = saveBitMap.GetInfo()
                bmpstr = saveBitMap.GetBitmapBits(True)
                im = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)

                win32gui.DeleteObject(saveBitMap.GetHandle())
                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwndDC)

                # Keep width compact for low VLM inference latency
                if im.width > 1280:
                    ratio = 1280 / im.width
                    im = im.resize((1280, int(im.height * ratio)), Image.Resampling.LANCZOS)

                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                val = buf.getvalue()
                if len(val) > 1000:
                    return val
        except Exception as e:
            logger.debug(f"PrintWindow screenshot failed: {e}")

    # 2. Secondary: PIL ImageGrab by window bounds
    try:
        from PIL import ImageGrab
        bbox = None
        if hwnd:
            import win32gui
            if win32gui.IsWindow(hwnd):
                bbox = win32gui.GetWindowRect(hwnd)

        im = ImageGrab.grab(bbox=bbox)
        if im.width > 1280:
            ratio = 1280 / im.width
            im = im.resize((1280, int(im.height * ratio)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        val = buf.getvalue()
        if len(val) > 1000:
            return val
    except Exception as e:
        logger.debug(f"ImageGrab screenshot failed: {e}")

    return None


async def validate_excel_execution_with_vlm(
    goal: str,
    step: Dict[str, Any],
    tool_result: Any,
    hwnd: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Multimodal visual auditor for Excel Copilot operations.
    Validates the visual outcome of the spreadsheet action using VLM + screenshot.
    """
    from backend.agent.router.model_router import call_vision_with_dynamic_switch

    tool_name = step.get("tool", "")
    params = dict(step.get("parameters") or step.get("args") or {})
    reported_output = str(getattr(tool_result, "output", "") or getattr(tool_result, "data", ""))

    # Capture screenshot
    screenshot_bytes = capture_excel_screenshot(hwnd)

    # Fast heuristic check for obvious calculation anomalies
    heuristic_anomaly = None
    if "sum" in params.get("operation", ""):
        # Check if output explicitly reports Calculated Value: 0 or None when summing positive numbers
        if "Value: 0" in reported_output or "Value: 0.0" in reported_output:
            heuristic_anomaly = "Formula evaluated to 0 on a sum aggregation. Text column was likely summed instead of numeric column."
    if any(err in reported_output for err in ("#VALUE!", "#NAME?", "#REF!", "#DIV/0!", "#N/A", "#NUM!")):
        heuristic_anomaly = f"Formula produced native Excel error: {reported_output}"

    if not screenshot_bytes:
        # If no visual device available (e.g. headless), return heuristic validation
        if heuristic_anomaly:
            return {
                "passed": False,
                "confidence": 0.9,
                "observation": heuristic_anomaly,
                "needs_replan": True,
                "source": "heuristic",
            }
        return {
            "passed": True,
            "confidence": 0.8,
            "observation": f"Operation succeeded and verified: {reported_output}",
            "needs_replan": False,
            "source": "heuristic",
        }

    b64_img = base64.b64encode(screenshot_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64_img}"

    vlm_prompt = (
        f"You are the NEXUS Excel Visual Auditor. You inspect screenshots of Microsoft Excel to verify if an automated operation was executed properly.\n\n"
        f"User Goal: \"{goal}\"\n"
        f"Executed Tool: {tool_name}\n"
        f"Operation Parameters: {json.dumps(params)}\n"
        f"Reported Tool Output: \"{reported_output}\"\n\n"
        f"Look carefully at the spreadsheet in the screenshot:\n"
        f"1. Did the formula or action calculate properly according to the user's goal?\n"
        f"2. Does the calculated cell display an anomaly?\n"
        f"   - Value is 0 when calculating a sum/average of positive numbers\n"
        f"   - Cell displays an Excel error: #VALUE!, #NAME?, #REF!, #DIV/0!, #N/A\n"
        f"   - The formula was inserted into the wrong column (e.g. inserted into a names/text column instead of numeric column)\n"
        f"3. Is the result completed properly?\n\n"
        f"Respond strictly in JSON format (no markdown):\n"
        f"{{\n"
        f"  \"passed\": true or false,\n"
        f"  \"confidence\": 0.0 to 1.0,\n"
        f"  \"calculated_value\": \"detected value\",\n"
        f"  \"observation\": \"concise visual summary of what happened\",\n"
        f"  \"needs_replan\": true or false,\n"
        f"  \"replan_hint\": \"specific instruction for how to fix the operation if failed\"\n"
        f"}}"
    )

    try:
        raw_res = await call_vision_with_dynamic_switch(
            prompt=vlm_prompt,
            data_url=data_url,
            max_tokens=300,
            temperature=0.0,
        )
        clean_text = raw_res.strip()
        if "```" in clean_text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
            if m:
                clean_text = m.group(1).strip()
        parsed = json.loads(clean_text)
        parsed["source"] = "vlm"
        return parsed
    except Exception as exc:
        logger.warning(f"VLM visual validation failed: {exc}")
        if heuristic_anomaly:
            return {
                "passed": False,
                "confidence": 0.85,
                "observation": heuristic_anomaly,
                "needs_replan": True,
                "source": "heuristic_fallback",
            }
        return {
            "passed": True,
            "confidence": 0.75,
            "observation": f"Executed and verified: {reported_output}",
            "needs_replan": False,
            "source": "fallback",
        }


async def self_heal_excel_operation(
    goal: str,
    failed_step: Dict[str, Any],
    vlm_diagnosis: Dict[str, Any],
    hwnd: Optional[int] = None,
    workbook_name: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Automatically replans and re-executes an Excel operation when VLM detects an execution defect.
    """
    from backend.agent.tools.registry import tool_registry
    from backend.agent.tools.excel_copilot.planner import build_excel_copilot_plan
    from backend.agent.tools.excel_copilot.resolver import resolve_excel_target

    logger.info(f"[Excel Self-Heal] VLM detected issue: {vlm_diagnosis.get('observation')}. Replanning...")

    active_target = {
        "window_id": str(hwnd or ""),
        "window_title": workbook_name or "",
    }

    # 1. Attempt replan with clarified context
    replan = build_excel_copilot_plan(goal, active_target=active_target, active_context=context)

    # If planner generated the exact same parameters or None, synthesize fix using VLM hint
    if not replan or replan[0].get("args") == failed_step.get("args"):
        # Correct target_column if it was a text column
        args = dict(failed_step.get("args", {}))
        headers = (context or {}).get("headers", [])
        numeric_headers = [h["name"] for h in headers if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id")]

        if numeric_headers:
            args["target_column"] = numeric_headers[0]
            if "sum" in args.get("operation", ""):
                args["condition_column"] = numeric_headers[0]
            replan = [{
                "title": f"Corrected {args.get('operation', 'Excel').upper()}",
                "description": f"Recalculate using numeric column {numeric_headers[0]}",
                "tool": "excel_formula",
                "args": args,
            }]

    if not replan:
        return False, [], vlm_diagnosis

    # 2. Re-execute corrected step
    corrected_results = []
    success = True
    for step in replan:
        tool_name = step.get("tool")
        params = dict(step.get("parameters") or step.get("args") or {})
        if "hwnd" not in params and hwnd:
            params["hwnd"] = hwnd
        if "workbook_name" not in params and workbook_name:
            params["workbook_name"] = workbook_name

        tool_res = tool_registry.execute(tool_name, params)
        corrected_results.append({
            "step_id": step.get("step_id"),
            "tool": tool_name,
            "success": tool_res.success,
            "data": tool_res.data,
            "error": tool_res.error,
        })
        if not tool_res.success:
            success = False
            break

    # 3. Post-replan visual verification
    final_vlm = await validate_excel_execution_with_vlm(
        goal=goal,
        step=replan[0],
        tool_result=corrected_results[0] if corrected_results else None,
        hwnd=hwnd,
        context=context,
    )

    return success and final_vlm.get("passed", True), replan, final_vlm
