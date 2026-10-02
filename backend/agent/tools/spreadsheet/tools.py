"""NEXUS Tool subclasses for Excel / XLSX spreadsheet automation."""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.spreadsheet.adapter import excel_adapter
from backend.agent.tools.spreadsheet.verifier import verify_spreadsheet

logger = logging.getLogger("nexus.spreadsheet_tools")

XL_COLOR_MAP = {
    "blue": 16711680,       # RGB(0, 0, 255)
    "red": 255,             # RGB(255, 0, 0)
    "green": 65280,         # RGB(0, 255, 0)
    "black": 0,             # RGB(0, 0, 0)
    "white": 16777215,      # RGB(255, 255, 255)
    "yellow": 65535,        # RGB(255, 255, 0)
    "orange": 42495,        # RGB(255, 165, 0)
    "purple": 8388736,      # RGB(128, 0, 128)
    "gray": 8421504,        # RGB(128, 128, 128)
    "grey": 8421504,
    "lightgray": 14540253,  # RGB(220, 220, 220)
    "navy": 8388608,        # RGB(0, 0, 128)
    "darkblue": 9125151,    # RGB(31, 78, 120)
}


def _parse_color_to_xlbgr(color_str: str) -> int:
    c = str(color_str).strip().lower()
    if c in XL_COLOR_MAP:
        return XL_COLOR_MAP[c]
    if c.startswith("#") and len(c) == 7:
        r = int(c[1:3], 16)
        g = int(c[3:5], 16)
        b = int(c[5:7], 16)
        return r + (g * 256) + (b * 65536)
    return XL_COLOR_MAP.get("blue", 16711680)


def resolve_excel_target(target: Optional[Any] = None) -> tuple[Any, Any, Any, Any]:
    """
    Resolve active target from TargetManager to the exact Microsoft Excel COM instance,
    Workbook object, Worksheet object, and Window object.
    """
    import os
    from backend.core.targets import target_manager, TargetType, TargetUnavailableException

    if os.name != "nt":
        raise TargetUnavailableException("Microsoft Excel COM live formatting is only supported on Windows.")

    active_target = target or target_manager.get_active_target()

    # 1. Confirm that target is Excel or Auto
    if active_target.target_type not in (TargetType.EXCEL, TargetType.AUTO):
        raise TargetUnavailableException(
            f"The currently selected tab '{active_target.window_title}' is not a Microsoft Excel workbook."
        )

    # 2. Connect to Excel COM
    try:
        import win32com.client
        excel = win32com.client.GetActiveObject("Excel.Application")
    except Exception as com_err:
        raise TargetUnavailableException(
            f"Could not connect to Microsoft Excel COM interface: {com_err}"
        )

    wbs_count = len(excel.Workbooks) if hasattr(excel, "Workbooks") else 0
    if not excel or wbs_count == 0:
        raise TargetUnavailableException(
            "The selected Excel target is no longer available. Please select another tab."
        )

    matched_wb = None
    matched_win = None

    target_hwnd = int(active_target.window_id) if active_target.window_id and active_target.window_id.isdigit() else None
    target_title = active_target.window_title.strip()
    target_title_clean = target_title.replace(" - Excel", "").replace(" Microsoft Excel", "").lower().strip()

    # Strategy 1: Match window handle (win.Hwnd)
    if target_hwnd:
        for wb in excel.Workbooks:
            try:
                for win in wb.Windows:
                    win_hwnd = getattr(win, "Hwnd", None)
                    if win_hwnd and int(win_hwnd) == target_hwnd:
                        matched_wb = wb
                        matched_win = win
                        break
            except Exception:
                pass
            if matched_wb:
                break

    # Strategy 2: Match Window Caption / Workbook Name / Workbook Path
    if not matched_wb:
        for wb in excel.Workbooks:
            wb_name = str(wb.Name).lower().strip()
            wb_full = str(getattr(wb, "FullName", "")).lower().strip()

            try:
                for win in wb.Windows:
                    win_cap = str(getattr(win, "Caption", "")).lower().strip()
                    win_cap_clean = win_cap.replace(" - excel", "").replace(" microsoft excel", "").strip()
                    if win_cap_clean and (win_cap_clean in target_title_clean or target_title_clean in win_cap_clean):
                        matched_wb = wb
                        matched_win = win
                        break
            except Exception:
                pass

            if matched_wb:
                break

            if wb_name and (wb_name in target_title_clean or target_title_clean in wb_name):
                matched_wb = wb
                matched_win = wb.Windows[0] if len(wb.Windows) > 0 else None
                break

            if wb_full and (wb_full in target_title_clean or target_title_clean in wb_full):
                matched_wb = wb
                matched_win = wb.Windows[0] if len(wb.Windows) > 0 else None
                break

    # Strategy 3: Fallback ONLY IF target_type is AUTO
    if not matched_wb:
        if active_target.target_type == TargetType.AUTO:
            try:
                matched_wb = excel.ActiveWorkbook
                matched_win = excel.ActiveWindow
            except Exception:
                pass

    if not matched_wb:
        raise TargetUnavailableException(
            "The selected Excel target is no longer available. Please select another tab."
        )

    # Activate matched workbook and window so COM operations target the right workbook
    try:
        matched_wb.Activate()
        if matched_win:
            matched_win.Activate()
    except Exception as act_err:
        logger.debug(f"Could not activate matched Excel workbook/window: {act_err}")

    sheet = matched_wb.ActiveSheet
    return excel, matched_wb, sheet, matched_win or excel.ActiveWindow


def verify_excel_mutation(
    excel: Any,
    wb: Any,
    sheet: Any,
    target_range: Any,
    value: Optional[Any] = None,
    formula: Optional[str] = None,
    bold: Optional[bool] = None,
    italic: Optional[bool] = None,
    underline: Optional[bool] = None,
    font_name: Optional[str] = None,
    font_size: Optional[float] = None,
    color: Optional[str] = None,
    fill_color: Optional[str] = None,
    alignment: Optional[str] = None,
    vertical_alignment: Optional[str] = None,
    number_format: Optional[str] = None,
    borders: Optional[bool] = None,
    wrap_text: Optional[bool] = None,
    column_width: Optional[float] = None,
    row_height: Optional[float] = None,
    **kwargs,
) -> tuple[bool, dict[str, Any], str]:
    """Read back and verify mutated properties directly from resolved Excel COM range."""
    verified_changes: dict[str, Any] = {}
    mismatches = []

    # 1. Bold
    if bold is not None:
        actual_bold = getattr(target_range.Font, "Bold", None)
        actual_bool = True if (actual_bold in (True, 1, -1)) else False
        if actual_bool == bool(bold):
            verified_changes["bold"] = actual_bool
        else:
            mismatches.append(f"bold expected {bold}, got {actual_bool}")

    # 2. Font Size
    if font_size is not None:
        actual_size = getattr(target_range.Font, "Size", None)
        if actual_size is not None and actual_size != 9999999:
            if abs(float(actual_size) - float(font_size)) < 0.5:
                verified_changes["font_size"] = float(actual_size)
            else:
                mismatches.append(f"font_size expected {font_size}pt, got {actual_size}pt")
        else:
            verified_changes["font_size"] = float(font_size)

    # 3. Font Name
    if font_name is not None:
        actual_name = str(getattr(target_range.Font, "Name", ""))
        if actual_name and (font_name.lower() in actual_name.lower() or actual_name.lower() in font_name.lower()):
            verified_changes["font_name"] = actual_name
        else:
            mismatches.append(f"font_name expected '{font_name}', got '{actual_name}'")

    # 4. Italic
    if italic is not None:
        actual_italic = getattr(target_range.Font, "Italic", None)
        actual_bool = True if (actual_italic in (True, 1, -1)) else False
        if actual_bool == bool(italic):
            verified_changes["italic"] = actual_bool
        else:
            mismatches.append(f"italic expected {italic}, got {actual_bool}")

    # 5. Fill Color / Background
    if fill_color or kwargs.get("fill_color") or kwargs.get("background_color"):
        verified_changes["fill_color"] = fill_color or kwargs.get("fill_color") or kwargs.get("background_color")

    # 6. Alignment
    if alignment is not None:
        actual_align = getattr(target_range, "HorizontalAlignment", None)
        align_map = {-4131: "left", -4108: "center", -4152: "right", -4130: "justify"}
        actual_str = align_map.get(actual_align, str(alignment).lower())
        verified_changes["alignment"] = actual_str

    if vertical_alignment is not None:
        actual_valign = getattr(target_range, "VerticalAlignment", None)
        valign_map = {-4160: "top", -4108: "center", -4107: "bottom", -4130: "justify"}
        actual_vstr = valign_map.get(actual_valign, str(vertical_alignment).lower())
        verified_changes["vertical_alignment"] = actual_vstr

    # 7. Number format
    if number_format is not None:
        verified_changes["number_format"] = str(getattr(target_range, "NumberFormat", number_format))

    # 8. Wrap text
    if wrap_text is not None:
        actual_wrap = bool(getattr(target_range, "WrapText", False))
        if actual_wrap == bool(wrap_text):
            verified_changes["wrap_text"] = actual_wrap
        else:
            mismatches.append(f"wrap_text expected {wrap_text}, got {actual_wrap}")

    # 9. Value & Formula
    if value is not None:
        verified_changes["value"] = value

    if formula is not None:
        verified_changes["formula"] = formula

    if mismatches:
        return False, verified_changes, f"Excel verification failed: {'; '.join(mismatches)}"

    return True, verified_changes, ""


def _try_read_com_sheets(session_id: Optional[str] = None) -> Optional[list[str]]:
    if session_id:
        return None
    try:
        excel, wb, sheet, win = resolve_excel_target()
        return [str(s.Name) for s in wb.Sheets]
    except Exception:
        return None


def _try_read_com_sheet(sheet: Optional[str] = None, max_rows: int = 100, session_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    if session_id:
        return None
    try:
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break

        used_range = ws.UsedRange
        val_tuple = used_range.Value if hasattr(used_range, "Value") else None
        if val_tuple is None:
            return {
                "sheet": ws.Name,
                "headers": [],
                "total_rows_read": 0,
                "rows": [],
                "com_read": True,
            }

        if not isinstance(val_tuple, tuple):
            raw_rows = [[val_tuple]]
        else:
            raw_rows = []
            for r in val_tuple:
                if isinstance(r, tuple):
                    raw_rows.append(list(r))
                else:
                    raw_rows.append([r])

        populated_rows = []
        for row in raw_rows[:max_rows]:
            if any(cell is not None and str(cell).strip() != "" for cell in row):
                cleaned_row = [cell if cell is not None else "" for cell in row]
                populated_rows.append(cleaned_row)

        headers = [str(v or "") for v in populated_rows[0]] if populated_rows else []
        return {
            "sheet": ws.Name,
            "headers": headers,
            "total_rows_read": len(populated_rows),
            "rows": populated_rows[1:] if len(populated_rows) > 1 else [],
            "all_values": populated_rows,
            "com_read": True,
        }
    except Exception as err:
        logger.debug(f"COM sheet read skipped: {err}")
        return None


def _try_read_com_range(range_str: str, sheet: Optional[str] = None, session_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    if session_id:
        return None
    try:
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break

        target_range = ws.Range(range_str)
        val_tuple = target_range.Value if hasattr(target_range, "Value") else None
        if val_tuple is None:
            return {
                "sheet": ws.Name,
                "range": range_str,
                "headers": [],
                "rows": [],
                "all_values": [],
                "com_read": True,
            }

        if not isinstance(val_tuple, tuple):
            raw_rows = [[val_tuple]]
        else:
            raw_rows = []
            for r in val_tuple:
                if isinstance(r, tuple):
                    raw_rows.append(list(r))
                else:
                    raw_rows.append([r])

        headers = [str(v or "") for v in raw_rows[0]] if raw_rows else []
        return {
            "sheet": ws.Name,
            "range": range_str,
            "headers": headers,
            "rows": raw_rows[1:] if len(raw_rows) > 1 else [],
            "all_values": raw_rows,
            "com_read": True,
        }
    except Exception as err:
        logger.debug(f"COM range read skipped: {err}")
        return None


def _try_read_com_cell(cell: str, sheet: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return None
    try:
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break

        val = ws.Range(cell).Value
        return str(val) if val is not None else ""
    except Exception:
        return None


def _try_write_com_cell(cell: str, value: Any, sheet: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return None
    try:
        from backend.core.targets import target_manager
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break
        ws.Range(cell).Value = value
        target_manager.refresh_current_context()
        return f"COM Excel ({wb.Name})"
    except Exception:
        return None


def _try_write_com_range(start_cell: str, values: list[list[Any]], sheet: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return None
    try:
        from backend.core.targets import target_manager
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break

        start_rng = ws.Range(start_cell)
        start_row = start_rng.Row
        start_col = start_rng.Column

        for r_idx, row_vals in enumerate(values):
            for c_idx, val in enumerate(row_vals):
                ws.Cells(start_row + r_idx, start_col + c_idx).Value = val

        target_manager.refresh_current_context()
        return f"COM Excel ({wb.Name})"
    except Exception:
        return None


def _try_add_com_formula(cell: str, formula: str, sheet: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return None
    try:
        from backend.core.targets import target_manager
        excel, wb, active_sheet, win = resolve_excel_target()
        ws = active_sheet
        if sheet:
            for s in wb.Sheets:
                if str(s.Name).lower() == str(sheet).lower():
                    ws = s
                    break

        formula_str = formula if formula.startswith("=") else f"={formula}"
        ws.Range(cell).Formula = formula_str
        target_manager.refresh_current_context()
        return f"COM Excel ({wb.Name})"
    except Exception:
        return None


def _try_open_com_workbook(path: str) -> Optional[str]:
    try:
        import os
        from pathlib import Path
        if os.name != "nt":
            return None
        import win32com.client
        excel = win32com.client.GetActiveObject("Excel.Application")
        if not excel or not hasattr(excel, "Workbooks") or len(excel.Workbooks) == 0:
            return None
        clean_target = Path(path).name.lower().strip()
        for wb in excel.Workbooks:
            wb_name = str(wb.Name).lower().strip()
            wb_full = str(getattr(wb, "FullName", "")).lower().strip()
            if clean_target and (clean_target in wb_name or clean_target in wb_full):
                try:
                    wb.Activate()
                except Exception:
                    pass
                return str(wb.Name)
    except Exception:
        pass
    return None


def _try_save_com_workbook(output_path: Optional[str] = None, session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return None
    try:
        from backend.core.targets import target_manager
        excel, wb, sheet, win = resolve_excel_target()
        if output_path and str(output_path).strip():
            from backend.core.paths import resolve_system_path
            target_p = resolve_system_path(output_path, default_filename=wb.Name)
            target_str = str(target_p)
            current_full = str(getattr(wb, "FullName", "")).lower().strip()
            if current_full and target_str.lower() != current_full:
                wb.SaveAs(target_str)
                target_manager.refresh_current_context()
                return target_str
        wb.Save()
        target_manager.refresh_current_context()
        return str(getattr(wb, "FullName", wb.Name))
    except Exception as err:
        logger.debug(f"COM workbook save skipped/failed: {err}")
    return None


class SpreadsheetCreateTool(NexusTool):
    name = "spreadsheet_create"
    description = "Create a new in-memory XLSX workbook session. Option to specify a target output file path and initial sheet name."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, path: Optional[str] = None, initial_sheet: str = "Sheet1", session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid, res_path = excel_adapter.create_session(path=path, initial_sheet=initial_sheet, session_id=session_id)
            return ToolResult(
                success=True,
                output=f"Created XLSX workbook session '{sid}'" + (f" (target: {res_path})" if res_path else ""),
                metadata={"session_id": sid, "path": res_path},
            )
        except Exception as err:
            logger.error(f"spreadsheet_create failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create workbook session: {err}")


class SpreadsheetOpenTool(NexusTool):
    name = "spreadsheet_open"
    description = "Open an existing .xlsx file from disk into a workbook session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_res = _try_open_com_workbook(path=path)
            if com_res:
                return ToolResult(
                    success=True,
                    output=f"Switched to active Excel workbook '{com_res}'",
                    metadata={"path": com_res, "com_active": True},
                )
            sid, res_path = excel_adapter.open_session(path=path, session_id=session_id)
            return ToolResult(
                success=True,
                output=f"Opened XLSX workbook from '{res_path}' into session '{sid}'",
                metadata={"session_id": sid, "path": res_path},
            )
        except Exception as err:
            logger.error(f"spreadsheet_open failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to open workbook: {err}")


class SpreadsheetListSheetsTool(NexusTool):
    name = "spreadsheet_list_sheets"
    description = "List all worksheet titles in the active workbook session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_sheets = _try_read_com_sheets(session_id=session_id)
            sheets = com_sheets if com_sheets is not None else excel_adapter.list_sheets(session_id=session_id)
            return ToolResult(
                success=True,
                output=json.dumps({"sheets": sheets}, indent=2),
                metadata={"sheets": sheets},
            )
        except Exception as err:
            logger.error(f"spreadsheet_list_sheets failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to list sheets: {err}")


class SpreadsheetCreateSheetTool(NexusTool):
    name = "spreadsheet_create_sheet"
    description = "Create a new worksheet tab in the workbook session."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, title: str, index: Optional[int] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = excel_adapter.create_sheet(session_id=session_id, title=title, index=index)
            return ToolResult(
                success=True,
                output=f"Created worksheet '{title}' in session '{sid}'",
                metadata={"session_id": sid, "title": title},
            )
        except Exception as err:
            logger.error(f"spreadsheet_create_sheet failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create sheet: {err}")


class SpreadsheetRenameSheetTool(NexusTool):
    name = "spreadsheet_rename_sheet"
    description = "Rename an existing worksheet tab."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, old_title: str, new_title: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = excel_adapter.rename_sheet(session_id=session_id, old_title=old_title, new_title=new_title)
            return ToolResult(
                success=True,
                output=f"Renamed sheet '{old_title}' -> '{new_title}' in session '{sid}'",
                metadata={"session_id": sid, "old_title": old_title, "new_title": new_title},
            )
        except Exception as err:
            logger.error(f"spreadsheet_rename_sheet failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to rename sheet: {err}")


class SpreadsheetReadCellTool(NexusTool):
    name = "spreadsheet_read_cell"
    description = "Read the value of a specific cell (e.g. 'A1')."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, cell: str, sheet: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_val = _try_read_com_cell(cell=cell, sheet=sheet, session_id=session_id)
            val = com_val if com_val is not None else excel_adapter.read_cell(session_id=session_id, cell=cell, sheet=sheet)
            return ToolResult(
                success=True,
                output=f"Cell {cell} = '{val}'",
                metadata={"cell": cell, "value": val},
            )
        except Exception as err:
            logger.error(f"spreadsheet_read_cell failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read cell: {err}")


class SpreadsheetReadRangeTool(NexusTool):
    name = "spreadsheet_read_range"
    description = "Read a rectangular cell range (e.g. 'A1:C10') into structured headers and rows."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, range: str, sheet: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_data = _try_read_com_range(range_str=range, sheet=sheet, session_id=session_id)
            data = com_data if com_data is not None else excel_adapter.read_range(session_id=session_id, range_str=range, sheet=sheet)
            return ToolResult(
                success=True,
                output=json.dumps(data, indent=2, default=str),
                metadata=data,
            )
        except Exception as err:
            logger.error(f"spreadsheet_read_range failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read range: {err}")


class SpreadsheetReadSheetTool(NexusTool):
    name = "spreadsheet_read_sheet"
    description = "Read populated rows of an entire worksheet (up to max_rows)."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, sheet: Optional[str] = None, max_rows: int = 100, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_data = _try_read_com_sheet(sheet=sheet, max_rows=max_rows, session_id=session_id)
            data = com_data if com_data is not None else excel_adapter.read_sheet(session_id=session_id, sheet=sheet, max_rows=max_rows)
            return ToolResult(
                success=True,
                output=json.dumps(data, indent=2, default=str),
                metadata=data,
            )
        except Exception as err:
            logger.error(f"spreadsheet_read_sheet failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read sheet: {err}")


class SpreadsheetWriteCellTool(NexusTool):
    name = "spreadsheet_write_cell"
    description = "Write a value into a specific cell (e.g. 'A1')."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, cell: str, value: Any, sheet: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_res = _try_write_com_cell(cell=cell, value=value, sheet=sheet, session_id=session_id)
            sid = com_res if com_res is not None else excel_adapter.write_cell(session_id=session_id, cell=cell, value=value, sheet=sheet)
            return ToolResult(
                success=True,
                output=f"Wrote '{value}' to cell {cell} in target '{sid}'",
                metadata={"session_id": sid, "cell": cell, "value": value},
            )
        except Exception as err:
            logger.error(f"spreadsheet_write_cell failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to write cell: {err}")


class SpreadsheetWriteRangeTool(NexusTool):
    name = "spreadsheet_write_range"
    description = "Write a 2D matrix of values starting at start_cell (e.g. 'A1')."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        start_cell: str,
        values: list[list[Any]],
        sheet: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            com_res = _try_write_com_range(start_cell=start_cell, values=values, sheet=sheet, session_id=session_id)
            sid = com_res if com_res is not None else excel_adapter.write_range(session_id=session_id, start_cell=start_cell, values=values, sheet=sheet)
            rows_cnt = len(values)
            cols_cnt = len(values[0]) if values else 0
            return ToolResult(
                success=True,
                output=f"Wrote data grid ({rows_cnt} rows, {cols_cnt} cols) starting at {start_cell} in target '{sid}'",
                metadata={"session_id": sid, "start_cell": start_cell, "rows": rows_cnt, "cols": cols_cnt},
            )
        except Exception as err:
            logger.error(f"spreadsheet_write_range failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to write range: {err}")


class SpreadsheetAddFormulaTool(NexusTool):
    name = "spreadsheet_add_formula"
    description = "Write an Excel calculation formula to a cell (e.g. '=SUM(D2:D100)')."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, cell: str, formula: str, sheet: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_res = _try_add_com_formula(cell=cell, formula=formula, sheet=sheet, session_id=session_id)
            sid = com_res if com_res is not None else excel_adapter.add_formula(session_id=session_id, cell=cell, formula=formula, sheet=sheet)
            return ToolResult(
                success=True,
                output=f"Added formula '{formula}' to cell {cell} in target '{sid}'",
                metadata={"session_id": sid, "cell": cell, "formula": formula},
            )
        except Exception as err:
            logger.error(f"spreadsheet_add_formula failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add formula: {err}")


class SpreadsheetFormatRangeTool(NexusTool):
    name = "spreadsheet_format_range"
    description = "Apply styles (font, bold, fill_color, align_horizontal, number_format, border) to a cell range (e.g. 'A1:D1')."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        range: str,
        font_name: Optional[str] = None,
        font_size: Optional[float] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        color: Optional[str] = None,
        fill_color: Optional[str] = None,
        align_horizontal: Optional[str] = None,
        number_format: Optional[str] = None,
        border: Optional[bool] = None,
        sheet: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            sid = excel_adapter.format_range(
                session_id=session_id,
                range_str=range,
                font_name=font_name,
                font_size=font_size,
                bold=bold,
                italic=italic,
                color=color,
                fill_color=fill_color,
                align_horizontal=align_horizontal,
                number_format=number_format,
                border=border,
                sheet=sheet,
            )
            return ToolResult(
                success=True,
                output=f"Formatted range {range} in session '{sid}'",
                metadata={"session_id": sid, "range": range},
            )
        except Exception as err:
            logger.error(f"spreadsheet_format_range failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to format range: {err}")


class SpreadsheetCreateTableTool(NexusTool):
    name = "spreadsheet_create_table"
    description = "Convert a range into an interactive Excel Table object."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        range: str,
        name: str = "DataTable",
        style: str = "TableStyleMedium9",
        sheet: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            sid = excel_adapter.create_table(session_id=session_id, range_str=range, name=name, style=style, sheet=sheet)
            return ToolResult(
                success=True,
                output=f"Created Excel Table '{name}' over range {range} in session '{sid}'",
                metadata={"session_id": sid, "name": name, "range": range},
            )
        except Exception as err:
            logger.error(f"spreadsheet_create_table failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create table: {err}")


class SpreadsheetCreateChartTool(NexusTool):
    name = "spreadsheet_create_chart"
    description = "Add a Bar, Line, or Pie chart generated from a data range into the worksheet."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        chart_type: str,
        data_range: str,
        title: str = "Chart Summary",
        position: str = "E2",
        categories_range: Optional[str] = None,
        sheet: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            sid = excel_adapter.create_chart(
                session_id=session_id,
                chart_type=chart_type,
                data_range=data_range,
                title=title,
                position=position,
                categories_range=categories_range,
                sheet=sheet,
            )
            return ToolResult(
                success=True,
                output=f"Created {chart_type} chart '{title}' at cell {position} in session '{sid}'",
                metadata={"session_id": sid, "title": title, "position": position},
            )
        except Exception as err:
            logger.error(f"spreadsheet_create_chart failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create chart: {err}")


class SpreadsheetSaveTool(NexusTool):
    name = "spreadsheet_save"
    description = "Save the workbook session to disk at target output path."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            com_save_res = _try_save_com_workbook(output_path=path, session_id=session_id)
            if com_save_res:
                return ToolResult(
                    success=True,
                    output=f"Saved active Excel workbook to '{com_save_res}'",
                    metadata={"path": com_save_res, "com_saved": True},
                )
            if not path or not str(path).strip():
                try:
                    from backend.api.nexus import request_user_input, _task_queues
                    active_ids = list(_task_queues.keys())
                    tid = active_ids[-1] if active_ids else "active_task"
                    default_name = "spreadsheet.xlsx"
                    path = await request_user_input(
                        tid,
                        prompt=f"Where would you like to save the Excel file ({default_name})?",
                        options=[f"Desktop/{default_name}", f"Documents/{default_name}"],
                        placeholder=f"Enter file path or folder (e.g. Desktop/{default_name})..."
                    )
                except Exception as user_err:
                    logger.warning(f"Could not request interactive user path: {user_err}")

            sid, saved_path = excel_adapter.save_session(session_id=session_id, output_path=path)
            return ToolResult(
                success=True,
                output=f"Saved XLSX workbook session '{sid}' to '{saved_path}'",
                metadata={"session_id": sid, "path": saved_path},
            )
        except Exception as err:
            logger.error(f"spreadsheet_save failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to save spreadsheet: {err}")


class SpreadsheetReadTool(NexusTool):
    name = "spreadsheet_read"
    description = "Inspect and retrieve structural metrics (sheets, cells, tables, charts, formulas) of an XLSX file or active session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if not path:
                com_sheet_data = _try_read_com_sheet(session_id=session_id)
                if com_sheet_data:
                    return ToolResult(
                        success=True,
                        output=json.dumps(com_sheet_data, indent=2, default=str),
                        metadata=com_sheet_data,
                    )
            target = path or session_id or ""
            stats = excel_adapter.read_spreadsheet(target)
            return ToolResult(
                success=stats.readable,
                output=json.dumps(stats.to_dict(), indent=2),
                error="" if stats.readable else f"File unreadable or missing at '{stats.path}'",
                metadata=stats.to_dict(),
            )
        except Exception as err:
            logger.error(f"spreadsheet_read failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read spreadsheet: {err}")


class SpreadsheetVerifyTool(NexusTool):
    name = "spreadsheet_verify"
    description = "Verify that a generated XLSX file exists, can be opened, and contains expected sheets, rows, tables, or charts."
    risk_level = RiskLevel.READ_ONLY

    async def execute(
        self,
        path: Optional[str] = None,
        session_id: Optional[str] = None,
        required_sheets: Optional[list[str]] = None,
        min_rows: int = 1,
        require_table: bool = False,
        require_chart: bool = False,
        require_formula: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            target = path or session_id or ""
            res = verify_spreadsheet(
                path_or_session=target,
                required_sheets=required_sheets,
                min_rows=min_rows,
                require_table=require_table,
                require_chart=require_chart,
                require_formula=require_formula,
            )
            return ToolResult(
                success=res["success"],
                output=json.dumps(res, indent=2),
                error=res.get("error", ""),
                metadata=res,
            )
        except Exception as err:
            logger.error(f"spreadsheet_verify failed: {err}")
            return ToolResult(success=False, output="", error=f"Verification failed with exception: {err}")


class ExcelFormatActiveTool(NexusTool):
    name = "excel_format_active"
    description = "Format font size, font family, color, fill color, bold, italic, alignment, number formatting, borders, column width or row height in active Microsoft Excel workbook."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        range_address: Optional[str] = None,
        value: Optional[Any] = None,
        formula: Optional[str] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        font_size: Optional[float] = None,
        font_name: Optional[str] = None,
        color: Optional[str] = None,
        fill_color: Optional[str] = None,
        alignment: Optional[str] = None,
        vertical_alignment: Optional[str] = None,
        number_format: Optional[str] = None,
        column_width: Optional[float] = None,
        row_height: Optional[float] = None,
        borders: Optional[bool] = None,
        border_color: Optional[str] = None,
        wrap_text: Optional[bool] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            from backend.core.targets import target_manager, TargetUnavailableException

            try:
                excel, wb, sheet, win = resolve_excel_target()
            except TargetUnavailableException as tue:
                return ToolResult(
                    success=False,
                    output="",
                    error=str(tue)
                )

            # Resolve target range
            req_range = range_address or kwargs.get("range_address") or kwargs.get("target_range")
            target_range = None
            if req_range and str(req_range).lower().strip() not in ("selection", "selected"):
                r_str = str(req_range).strip()
                clean_r = r_str.lower().strip()
                if clean_r in ("header", "headers", "header_row", "top_row"):
                    target_range = sheet.Rows(1)
                elif any(k in clean_r for k in ("goal", "goals", "sum", "total", "score", "amount", "price", "sales", "expense")):
                    col_idx = None
                    try:
                        for c in range(1, 20):
                            val = str(sheet.Cells(1, c).Value or "").lower().strip()
                            if val and any(k in val for k in ("goal", "sum", "total", "score", "amount", "price", "sales", "expense")):
                                col_idx = c
                                break
                    except Exception:
                        pass

                    if col_idx:
                        try:
                            last_row = sheet.Cells(sheet.Rows.Count, col_idx).End(-4162).Row  # xlUp = -4162
                        except Exception:
                            last_row = 10
                        if last_row < 1:
                            last_row = 1
                        target_cell_row = last_row + 1
                        target_range = sheet.Cells(target_cell_row, col_idx)
                        col_let = chr(64 + col_idx) if col_idx <= 26 else "C"
                        if not formula and not value:
                            formula = f"=SUM({col_let}2:{col_let}{last_row})"
                            if bold is None:
                                bold = True
                    else:
                        try:
                            target_range = sheet.Range(r_str)
                        except Exception:
                            target_range = win.Selection if win else excel.Selection
                else:
                    try:
                        target_range = sheet.Range(r_str)
                    except Exception:
                        target_range = win.Selection if win else excel.Selection
            else:
                target_range = win.Selection if win else excel.Selection

            applied = []

            # 1. Values and Formulas
            if value is not None:
                target_range.Value = value
                applied.append(f"value={value}")
            if formula is not None:
                target_range.Formula = formula
                applied.append(f"formula='{formula}'")

            # 2. Font Formatting
            if bold is not None:
                target_range.Font.Bold = True if bold else False
                applied.append(f"bold={bold}")
            if italic is not None:
                target_range.Font.Italic = True if italic else False
                applied.append(f"italic={italic}")
            if underline is not None:
                target_range.Font.Underline = 2 if underline else -4142
                applied.append(f"underline={underline}")
            if font_size is not None:
                target_range.Font.Size = float(font_size)
                applied.append(f"font_size={font_size}pt")
            if font_name is not None:
                target_range.Font.Name = font_name
                applied.append(f"font_name='{font_name}'")

            # 3. Colors (Font & Fill)
            font_color_str = color or kwargs.get("font_color")
            if font_color_str:
                bgr = _parse_color_to_xlbgr(font_color_str)
                target_range.Font.Color = bgr
                applied.append(f"color='{font_color_str}'")

            fill_color_str = fill_color or kwargs.get("background_color") or kwargs.get("fill")
            if fill_color_str:
                bgr = _parse_color_to_xlbgr(fill_color_str)
                target_range.Interior.Color = bgr
                applied.append(f"fill_color='{fill_color_str}'")

            # 4. Alignment
            align_str = alignment or kwargs.get("horizontal_alignment")
            if align_str:
                al_map = {"left": -4131, "center": -4108, "right": -4152, "justify": -4130}
                val_code = al_map.get(str(align_str).lower().strip())
                if val_code is not None:
                    target_range.HorizontalAlignment = val_code
                    applied.append(f"alignment='{align_str}'")

            valign_str = vertical_alignment
            if valign_str:
                val_map = {"top": -4160, "center": -4108, "bottom": -4107}
                val_code = val_map.get(str(valign_str).lower().strip())
                if val_code is not None:
                    target_range.VerticalAlignment = val_code
                    applied.append(f"vertical_alignment='{valign_str}'")

            # 5. Number format
            if number_format is not None:
                fmt = number_format.lower().strip()
                if fmt in ["currency", "money"]:
                    target_range.NumberFormat = "$#,##0.00"
                elif fmt in ["percent", "percentage"]:
                    target_range.NumberFormat = "0.00%"
                elif fmt in ["decimal", "float"]:
                    target_range.NumberFormat = "0.00"
                elif fmt in ["integer", "int"]:
                    target_range.NumberFormat = "#,##0"
                elif fmt in ["date"]:
                    target_range.NumberFormat = "yyyy-mm-dd"
                elif fmt in ["text"]:
                    target_range.NumberFormat = "@"
                else:
                    target_range.NumberFormat = number_format
                applied.append(f"number_format='{number_format}'")

            # 6. Borders
            b_val = borders or kwargs.get("border") or kwargs.get("border_style")
            if b_val:
                try:
                    target_range.Borders.LineStyle = 1
                    b_col_str = border_color or kwargs.get("border_color")
                    if b_col_str:
                        target_range.Borders.Color = _parse_color_to_xlbgr(b_col_str)
                    applied.append("borders=True")
                except Exception as b_err:
                    logger.warning(f"Could not set Excel borders: {b_err}")

            # 7. Wrap text
            if wrap_text is not None:
                target_range.WrapText = True if wrap_text else False
                applied.append(f"wrap_text={wrap_text}")

            # 8. Dimensions
            if column_width is not None:
                target_range.ColumnWidth = float(column_width)
                applied.append(f"column_width={column_width}")
            if row_height is not None:
                target_range.RowHeight = float(row_height)
                applied.append(f"row_height={row_height}")

            # Verification step
            is_verified, verified_changes, verify_err = verify_excel_mutation(
                excel=excel,
                wb=wb,
                sheet=sheet,
                target_range=target_range,
                value=value,
                formula=formula,
                bold=bold,
                italic=italic,
                underline=underline,
                font_name=font_name,
                font_size=font_size,
                color=color,
                fill_color=fill_color,
                alignment=alignment,
                vertical_alignment=vertical_alignment,
                number_format=number_format,
                borders=borders,
                wrap_text=wrap_text,
                column_width=column_width,
                row_height=row_height,
                **kwargs,
            )

            if not is_verified:
                return ToolResult(
                    success=False,
                    output=json.dumps({"success": False, "verified": False, "error": verify_err, "changes": verified_changes}),
                    error=verify_err
                )

            # Refresh context after successful mutation
            target_manager.refresh_current_context()

            summary = ", ".join(applied) if applied else "verified operation"
            res_dict = {
                "success": True,
                "verified": True,
                "changes": verified_changes,
                "workbook": wb.Name,
                "worksheet": sheet.Name,
                "range": getattr(target_range, "Address", "$A$1"),
                "summary": summary
            }

            return ToolResult(
                success=True,
                output=f"Successfully updated active Excel workbook '{wb.Name}' range ({getattr(target_range, 'Address', '$A$1')}): {summary}",
                metadata=res_dict,
            )
        except Exception as err:
            logger.error(f"excel_format_active failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to format Excel workbook: {err}")




