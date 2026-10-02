"""Rich Excel context acquisition engine.

Extracts deep structural knowledge of the targeted Excel worksheet:
headers, column letters, types, active selection, sample values, tables, and formulas.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from backend.agent.tools.excel_copilot.resolver import resolve_excel_target

logger = logging.getLogger("nexus.excel_copilot.context")


def _col_index_to_letter(col_idx: int) -> str:
    """Convert 1-based column index to Excel column letter (1 -> 'A', 27 -> 'AA')."""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _infer_type(val: Any) -> str:
    if val is None or val == "":
        return "empty"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "numeric"
    val_str = str(val).strip()
    if val_str.startswith("="):
        return "formula"
    # Check currency symbols
    if any(c in val_str for c in ("$", "€", "£", "₹", "¥")):
        return "currency"
    # Check date patterns
    if any(sep in val_str for sep in ("-", "/")) and any(char.isdigit() for char in val_str):
        return "date"
    return "text"


def acquire_deep_excel_context(
    workbook_name: Optional[str] = None,
    hwnd: Optional[int] = None,
    target_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Acquire comprehensive, real-time context for the targeted Excel worksheet.
    Used by the planner to interpret natural-language commands without guesswork.
    """
    excel, wb, ws, win = resolve_excel_target(
        workbook_name=workbook_name,
        hwnd=hwnd,
        target_dict=target_dict,
    )

    context: Dict[str, Any] = {
        "application": "Microsoft Excel",
        "version": str(getattr(excel, "Version", "")),
        "workbook_name": str(wb.Name),
        "workbook_path": str(getattr(wb, "FullName", wb.Name)),
        "worksheet_name": str(ws.Name),
        "sheets": [str(s.Name) for s in wb.Sheets],
        "active_cell": "",
        "selected_range": "",
        "used_range": "",
        "row_count": 0,
        "col_count": 0,
        "headers": [],
        "columns": [],
        "sample_rows": [],
        "tables": [],
        "formulas": [],
    }

    try:
        active_cell = win.ActiveCell if win else getattr(excel, "ActiveCell", None)
        if active_cell:
            context["active_cell"] = str(active_cell.Address).replace("$", "")

        selection = win.Selection if win else getattr(excel, "Selection", None)
        if selection and hasattr(selection, "Address"):
            context["selected_range"] = str(selection.Address).replace("$", "")
    except Exception as e:
        logger.debug(f"Could not read active cell / selection: {e}")

    # Inspect UsedRange
    try:
        used_range = ws.UsedRange
        if used_range:
            addr = str(used_range.Address).replace("$", "")
            context["used_range"] = addr

            rows_count = used_range.Rows.Count
            cols_count = used_range.Columns.Count
            context["row_count"] = rows_count
            context["col_count"] = cols_count

            start_col = used_range.Column
            start_row = used_range.Row

            val_tuple = used_range.Value
            if val_tuple is not None:
                if not isinstance(val_tuple, tuple):
                    raw_grid = [[val_tuple]]
                else:
                    raw_grid = [list(r) if isinstance(r, tuple) else [r] for r in val_tuple]

                # Extract Headers from Row 1 of UsedRange
                if len(raw_grid) > 0:
                    header_row = raw_grid[0]
                    headers_list = []
                    columns_meta = []
                    for c_idx, h_val in enumerate(header_row):
                        actual_col_num = start_col + c_idx
                        col_letter = _col_index_to_letter(actual_col_num)
                        header_str = str(h_val).strip() if h_val is not None else f"Column_{col_letter}"

                        # Determine column type from subsequent rows
                        types_seen = []
                        for r_idx in range(1, min(len(raw_grid), 6)):
                            if c_idx < len(raw_grid[r_idx]):
                                cell_val = raw_grid[r_idx][c_idx]
                                if cell_val is not None and str(cell_val).strip() != "":
                                    types_seen.append(_infer_type(cell_val))

                        col_type = types_seen[0] if types_seen else "text"
                        headers_list.append({
                            "col": col_letter,
                            "index": actual_col_num,
                            "name": header_str,
                            "type": col_type,
                        })
                        columns_meta.append(f"{col_letter}: '{header_str}' ({col_type})")

                    context["headers"] = headers_list
                    context["columns"] = columns_meta

                # Sample data (up to 4 sample rows)
                samples = []
                for r_idx in range(1, min(len(raw_grid), 5)):
                    row_dict = {}
                    for c_idx, h in enumerate(context["headers"]):
                        if c_idx < len(raw_grid[r_idx]):
                            row_dict[h["name"]] = raw_grid[r_idx][c_idx]
                    if row_dict:
                        samples.append(row_dict)
                context["sample_rows"] = samples

            # Find existing formulas
            try:
                formula_tuple = used_range.Formula
                if formula_tuple:
                    if isinstance(formula_tuple, tuple):
                        for r_idx, row_forms in enumerate(formula_tuple):
                            if isinstance(row_forms, tuple):
                                for c_idx, f_val in enumerate(row_forms):
                                    if f_val and str(f_val).startswith("="):
                                        cell_ref = f"{_col_index_to_letter(start_col + c_idx)}{start_row + r_idx}"
                                        context["formulas"].append({
                                            "cell": cell_ref,
                                            "formula": str(f_val),
                                        })
            except Exception:
                pass
    except Exception as ur_err:
        logger.debug(f"Could not read used range details: {ur_err}")

    # Inspect Tables (ListObjects)
    try:
        if hasattr(ws, "ListObjects") and ws.ListObjects.Count > 0:
            for lo in ws.ListObjects:
                t_range = str(lo.Range.Address).replace("$", "") if hasattr(lo, "Range") else ""
                context["tables"].append({
                    "name": str(lo.Name),
                    "range": t_range,
                    "header_row_range": str(lo.HeaderRowRange.Address).replace("$", "") if hasattr(lo, "HeaderRowRange") else "",
                })
    except Exception:
        pass

    return context
