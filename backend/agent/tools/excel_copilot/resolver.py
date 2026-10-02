"""Target resolver for Microsoft Excel windows and workbooks.

Ensures that the floating NEXUS assistant binds to the exact targeted Excel window
and workbook, preventing cross-workbook mutations when multiple workbooks are open.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.excel_copilot.resolver")


class ExcelTargetError(Exception):
    """Raised when the specified Excel target cannot be resolved or accessed."""
    pass


def get_excel_app_from_hwnd(hwnd: int) -> Optional[Any]:
    """Retrieve the Excel.Application COM object from an XLMAIN or EXCEL7 window handle via oleacc."""
    if not hwnd or os.name != "nt":
        return None
    try:
        import ctypes
        import win32gui
        import pythoncom
        import win32com.client

        excel7_hwnds: List[int] = []
        def _enum_child(h: int, _: Any) -> bool:
            try:
                if win32gui.GetClassName(h) == "EXCEL7":
                    excel7_hwnds.append(h)
                    return False
            except Exception:
                pass
            return True

        try:
            if win32gui.GetClassName(hwnd) == "EXCEL7":
                excel7_hwnds.append(hwnd)
            else:
                win32gui.EnumChildWindows(hwnd, _enum_child, None)
        except Exception:
            pass

        if not excel7_hwnds:
            return None

        oleacc = ctypes.windll.oleacc
        IID_IDispatch = pythoncom.IID_IDispatch
        OBJID_NATIVEOM = 0xFFFFFFF0

        class GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', ctypes.c_ulong),
                ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort),
                ('Data4', ctypes.c_ubyte * 8)
            ]

        guid = GUID(0x00020400, 0x0000, 0x0000, (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
        ptr = ctypes.c_void_p()

        res = oleacc.AccessibleObjectFromWindow(
            excel7_hwnds[0],
            ctypes.c_uint32(OBJID_NATIVEOM),
            ctypes.byref(guid),
            ctypes.byref(ptr)
        )
        if res == 0 and ptr.value:
            disp = win32com.client.Dispatch(pythoncom.ObjectFromAddress(ptr.value, IID_IDispatch))
            if hasattr(disp, "Application"):
                return disp.Application
    except Exception as exc:
        logger.debug(f"Could not get Excel app from hwnd {hwnd}: {exc}")
    return None


def is_window_or_process_foreground(target_hwnd: int, allowed_hwnds: Optional[set[int]] = None) -> bool:
    """Check if the given window, its process, or any allowed copilot window is currently the foreground window."""
    if not target_hwnd or os.name != "nt":
        return False
    try:
        import win32gui
        import win32process
        fg = win32gui.GetForegroundWindow()
        if not fg:
            return False
        # If the user is currently interacting with the floating copilot window
        if allowed_hwnds and (fg in allowed_hwnds or win32gui.GetAncestor(fg, 2) in allowed_hwnds):
            return True
        if fg == target_hwnd or win32gui.GetAncestor(fg, 2) == target_hwnd:
            return True
        _, fg_pid = win32process.GetWindowThreadProcessId(fg)
        _, target_pid = win32process.GetWindowThreadProcessId(target_hwnd)
        return fg_pid > 0 and fg_pid == target_pid
    except Exception:
        return False


def get_open_excel_windows(copilot_hwnds: Optional[set[int]] = None) -> List[Dict[str, Any]]:
    """Enumerate all open Excel workbooks and windows with their HWNDs, titles, and foreground state."""
    if os.name != "nt":
        return []

    windows_info = []
    try:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        import win32com.client
        import win32gui

        excel = None
        try:
            excel = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            pass

        # If GetActiveObject didn't return an instance, search for visible XLMAIN windows
        if not excel or not hasattr(excel, "Workbooks") or len(excel.Workbooks) == 0:
            xlmain_hwnds: List[int] = []
            def _find_xlmain(h: int, _: Any) -> bool:
                try:
                    if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "XLMAIN":
                        xlmain_hwnds.append(h)
                except Exception:
                    pass
                return True

            try:
                win32gui.EnumWindows(_find_xlmain, None)
            except Exception:
                pass

            for h in xlmain_hwnds:
                try:
                    r = win32gui.GetWindowRect(h)
                    is_minimized = bool(win32gui.IsIconic(h))
                    is_fg = not is_minimized and is_window_or_process_foreground(int(h), copilot_hwnds)
                    title = win32gui.GetWindowText(h)
                    wb_name = title.replace(" - Excel", "").strip() or "Workbook.xlsx"
                    app_from_hwnd = get_excel_app_from_hwnd(h)
                    active_sheet = "Sheet1"
                    wb_path = wb_name
                    if app_from_hwnd and hasattr(app_from_hwnd, "ActiveWorkbook") and app_from_hwnd.ActiveWorkbook:
                        wb_name = str(app_from_hwnd.ActiveWorkbook.Name)
                        wb_path = str(getattr(app_from_hwnd.ActiveWorkbook, "FullName", wb_name))
                        active_sheet = str(getattr(app_from_hwnd.ActiveWorkbook.ActiveSheet, "Name", "Sheet1"))

                    windows_info.append({
                        "hwnd": int(h),
                        "title": f"{wb_name} - Excel" if "Excel" not in title else title,
                        "workbook_name": wb_name,
                        "workbook_path": wb_path,
                        "active_sheet": active_sheet,
                        "visible": not is_minimized and bool(win32gui.IsWindowVisible(h)),
                        "is_minimized": is_minimized,
                        "is_foreground": is_fg,
                        "rect": {
                            "left": r[0],
                            "top": r[1],
                            "right": r[2],
                            "bottom": r[3],
                            "width": max(0, r[2] - r[0]),
                            "height": max(0, r[3] - r[1]),
                        },
                    })
                except Exception:
                    pass

            if windows_info:
                return windows_info

        if not excel or not hasattr(excel, "Workbooks") or len(excel.Workbooks) == 0:
            return []

        for wb in excel.Workbooks:
            wb_name = str(wb.Name)
            wb_path = str(getattr(wb, "FullName", wb_name))
            active_sheet = str(getattr(wb.ActiveSheet, "Name", "Sheet1")) if getattr(wb, "ActiveSheet", None) else "Sheet1"

            # Check for Windows associated with this workbook
            if hasattr(wb, "Windows") and len(wb.Windows) > 0:
                for win in wb.Windows:
                    hwnd = getattr(win, "Hwnd", None)
                    caption = str(getattr(win, "Caption", wb_name))
                    rect_info = None
                    is_minimized = False
                    if hwnd:
                        try:
                            import win32gui
                            # GA_ROOT = 2: Get top-level parent (XLMAIN) for consistent HWND and screen rect
                            root_hwnd = win32gui.GetAncestor(int(hwnd), 2)
                            if not root_hwnd or not win32gui.IsWindow(root_hwnd):
                                root_hwnd = getattr(excel, "Hwnd", int(hwnd))
                            r = win32gui.GetWindowRect(root_hwnd)
                            rect_info = {
                                "left": r[0],
                                "top": r[1],
                                "right": r[2],
                                "bottom": r[3],
                                "width": max(0, r[2] - r[0]),
                                "height": max(0, r[3] - r[1]),
                            }
                            is_minimized = bool(win32gui.IsIconic(root_hwnd))
                            hwnd = root_hwnd
                        except Exception:
                            pass

                    is_fg = not is_minimized and is_window_or_process_foreground(int(hwnd), copilot_hwnds) if hwnd else False

                    windows_info.append({
                        "hwnd": int(hwnd) if hwnd else None,
                        "title": f"{caption} - Excel" if "Excel" not in caption else caption,
                        "workbook_name": wb_name,
                        "workbook_path": wb_path,
                        "active_sheet": active_sheet,
                        "visible": bool(getattr(win, "Visible", True)) and not is_minimized,
                        "is_minimized": is_minimized,
                        "is_foreground": is_fg,
                        "rect": rect_info,
                    })
            else:
                windows_info.append({
                    "hwnd": None,
                    "title": f"{wb_name} - Excel",
                    "workbook_name": wb_name,
                    "workbook_path": wb_path,
                    "active_sheet": active_sheet,
                    "visible": True,
                    "is_minimized": False,
                    "rect": None,
                })
    except Exception as err:
        logger.debug(f"Error enumerating Excel windows: {err}")

    return windows_info


def resolve_excel_target(
    workbook_name: Optional[str] = None,
    hwnd: Optional[int] = None,
    target_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any, Any, Any]:
    """
    Resolve the exact Excel Application, Workbook, Worksheet, and Window.
    
    Priority order:
    1. HWND match (exact window handle from floating copilot)
    2. Workbook name / file path / window title match
    3. Active target from NEXUS TargetManager
    4. Fallback only if single workbook is open
    """
    if os.name != "nt":
        raise ExcelTargetError("Microsoft Excel COM automation is only supported on Windows.")

    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    import win32com.client

    excel = None
    if hwnd:
        excel = get_excel_app_from_hwnd(int(hwnd))

    if not excel:
        try:
            excel = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            pass

    if not excel:
        raise ExcelTargetError("Could not connect to Microsoft Excel. Is Excel open?")

    wbs_count = len(excel.Workbooks) if hasattr(excel, "Workbooks") else 0
    if not excel or wbs_count == 0:
        raise ExcelTargetError("No open Excel workbooks found. Please open an Excel file.")

    matched_wb = None
    matched_win = None

    # Check target_dict if supplied
    target_hwnd = hwnd
    target_name = (workbook_name or "").strip()
    if not target_hwnd and target_dict:
        wid = target_dict.get("window_id")
        if wid and str(wid).isdigit():
            target_hwnd = int(wid)
        if not target_name:
            target_name = (target_dict.get("window_title") or "").strip()

    # If neither was passed, check NEXUS TargetManager
    if not target_hwnd and not target_name:
        try:
            from backend.core.targets import target_manager, TargetType
            cur_target = target_manager.get_active_target()
            if cur_target and cur_target.target_type in (TargetType.EXCEL, TargetType.AUTO):
                if cur_target.window_id and cur_target.window_id.isdigit():
                    target_hwnd = int(cur_target.window_id)
                target_name = cur_target.window_title
        except Exception:
            pass

    # 1. Match by HWND
    if target_hwnd:
        for wb in excel.Workbooks:
            try:
                for win in wb.Windows:
                    win_hwnd = getattr(win, "Hwnd", None)
                    if win_hwnd and int(win_hwnd) == int(target_hwnd):
                        matched_wb = wb
                        matched_win = win
                        break
            except Exception:
                pass
            if matched_wb:
                break

    # 2. Match by workbook name or window title
    if not matched_wb and target_name:
        clean_target = target_name.replace(" - Excel", "").replace(" Microsoft Excel", "").lower().strip()
        for wb in excel.Workbooks:
            wb_name = str(wb.Name).lower().strip()
            wb_full = str(getattr(wb, "FullName", "")).lower().strip()

            # Window caption match
            try:
                for win in wb.Windows:
                    w_cap = str(getattr(win, "Caption", "")).lower().strip()
                    w_cap_clean = w_cap.replace(" - excel", "").replace(" microsoft excel", "").strip()
                    if w_cap_clean and (w_cap_clean in clean_target or clean_target in w_cap_clean):
                        matched_wb = wb
                        matched_win = win
                        break
            except Exception:
                pass
            if matched_wb:
                break

            # Workbook name match (e.g. Budget.xlsx)
            if wb_name and (wb_name in clean_target or clean_target in wb_name):
                matched_wb = wb
                matched_win = wb.Windows[0] if len(wb.Windows) > 0 else None
                break

            # Full file path match
            if wb_full and (wb_full in clean_target or clean_target in wb_full):
                matched_wb = wb
                matched_win = wb.Windows[0] if len(wb.Windows) > 0 else None
                break

    # 3. If only 1 workbook is open, safe to use it
    if not matched_wb and wbs_count == 1:
        matched_wb = excel.Workbooks[0]
        matched_win = matched_wb.Windows[0] if len(matched_wb.Windows) > 0 else excel.ActiveWindow

    # 4. Strict safety check: if multiple workbooks are open and no match was found, do NOT guess!
    if not matched_wb:
        available_names = [str(w.Name) for w in excel.Workbooks]
        raise ExcelTargetError(
            f"Could not unambiguously resolve target Excel workbook '{target_name or target_hwnd}'. "
            f"Open workbooks: {', '.join(available_names)}. Please specify which workbook to modify."
        )

    # Bring target window and workbook to active state
    try:
        matched_wb.Activate()
        if matched_win:
            matched_win.Activate()
    except Exception as act_err:
        logger.debug(f"Could not activate matched Excel window: {act_err}")

    sheet = matched_wb.ActiveSheet
    return excel, matched_wb, sheet, matched_win or getattr(excel, "ActiveWindow", None)
