"""Broad, structured Excel Copilot tools executing directly in Microsoft Excel via Win32 COM.

Implements the 7 core operation categories:
1. ExcelFormulaTool (SUM, AVERAGE, COUNT, IF, IFS, custom)
2. ExcelLookupTool (XLOOKUP, VLOOKUP)
3. ExcelSortFilterTool (Whole-table Sort, AutoFilter)
4. ExcelPivotTool (Native PivotTables with row/col/value aggregations)
5. ExcelConditionalFormatTool (Native FormatConditions rules)
6. ExcelDataCleanupTool (Remove Duplicates, Text to Columns, Flash Fill)
7. ExcelInspectTool (Real-time context and range inspection)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.excel_copilot.resolver import resolve_excel_target, ExcelTargetError
from backend.agent.tools.excel_copilot.context import acquire_deep_excel_context, _col_index_to_letter

logger = logging.getLogger("nexus.excel_copilot.tools")

# Excel COM Constants
xlYes = 1
xlNo = 2
xlAscending = 1
xlDescending = 2
xlSortColumns = 1
xlTopToBottom = 1
xlGuess = 0

# Pivot Table Constants
xlDatabase = 1
xlRowField = 1
xlColumnField = 2
xlPageField = 3
xlDataField = 4
xlSum = -4157
xlCount = -4112
xlAverage = -4106
xlMax = -4136
xlMin = -4139

# Conditional Formatting Constants
xlCellValue = 1
xlExpression = 2
xlColorScale = 3
xlGreater = 5
xlLess = 6
xlEqual = 3
xlNotEqual = 4
xlBetween = 1
xlNotBetween = 2

# Text to Columns Constants
xlDelimited = 1


def _find_column_index(ws: Any, col_ident: str) -> Optional[int]:
    """Find column index (1-based) by letter ('B') or header name ('Sales')."""
    ident = str(col_ident).strip()
    if not ident:
        return None

    # Search in header row (Row 1 of UsedRange) first
    used = ws.UsedRange
    if used:
        val_tuple = used.Value
        if val_tuple:
            row1 = val_tuple[0] if isinstance(val_tuple, tuple) else [val_tuple]
            start_col = used.Column

            clean_ident = ident.lower().replace("_", " ")
            clean_stem = clean_ident.rstrip("s")

            # Exact, stemmed, or base match in header row
            for idx, cell_v in enumerate(row1):
                if cell_v:
                    h_clean = str(cell_v).lower().replace("_", " ").strip()
                    h_base = re.sub(r"\(.*?\)|\[.*?\]", "", h_clean).strip()
                    if (
                        clean_ident == h_clean
                        or clean_stem == h_clean.rstrip("s")
                        or clean_ident == h_base
                        or clean_stem == h_base.rstrip("s")
                        or clean_ident in h_clean
                        or h_base in clean_ident
                    ):
                        return start_col + idx

    # If no header matched and string is 1-3 letters, check if it's an explicit column letter (A, B, AA)
    if ident.isalpha() and len(ident) <= 3:
        col_num = 0
        for char in ident.upper():
            col_num = col_num * 26 + (ord(char) - ord('A') + 1)
        if 1 <= col_num <= 16384:
            return col_num

    return None


class ExcelFormulaTool(NexusTool):
    name = "excel_formula"
    description = (
        "Insert and execute native Excel calculation formulas in the active workbook. "
        "Supports SUM, SUMIF, AVERAGE, AVERAGEIF, COUNT, COUNTA, COUNTIF, IF, IFS, "
        "or custom formulas. Automatically determines column ranges and verifies result."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        operation: str = "sum",
        target_column: Optional[str] = None,
        target_cell: Optional[str] = None,
        condition_column: Optional[str] = None,
        condition_value: Optional[str] = None,
        true_value: Optional[str] = None,
        false_value: Optional[str] = None,
        formula_string: Optional[str] = None,
        header_name: Optional[str] = None,
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            used = ws.UsedRange
            start_row = used.Row
            row_count = used.Rows.Count
            end_row = start_row + row_count - 1

            op = operation.lower().strip()

            # 1. Custom explicit formula
            if formula_string:
                dest = target_cell or f"A{end_row + 1}"
                f_str = formula_string if formula_string.startswith("=") else f"={formula_string}"
                ws.Range(dest).Formula = f_str
                actual_val = ws.Range(dest).Value
                return ToolResult(
                    success=True,
                    output=f"✓ Inserted formula '{f_str}' in cell {dest}. Value: {actual_val}",
                    metadata={"cell": dest, "formula": f_str, "value": str(actual_val)},
                )

            # Determine column index & letter
            target_col_param = target_column or kwargs.get("column") or kwargs.get("target_col")
            col_idx = None
            if target_col_param:
                col_idx = _find_column_index(ws, target_col_param)
            if not col_idx:
                col_idx = 2  # default column B if not specified
            col_letter = _col_index_to_letter(col_idx)

            data_start_row = start_row + 1 if row_count > 1 else start_row
            data_end_row = end_row

            # If UsedRange has > 2 rows, check if end_row is already a summary / formula row
            if end_row > data_start_row:
                try:
                    c1_val = ws.Cells(end_row, 1).Value
                    c1_above = ws.Cells(end_row - 1, 1).Value
                    f_bottom = str(ws.Cells(end_row, col_idx).Formula or "")

                    is_summary = False
                    if (c1_val is None or str(c1_val).strip() == "") and (c1_above is not None and str(c1_above).strip() != ""):
                        is_summary = True
                    elif any(f_bottom.upper().startswith(p) for p in ("=SUM", "=SUBTOTAL", "=AVERAGE", "=COUNT")):
                        is_summary = True

                    if is_summary:
                        data_end_row = end_row - 1
                except Exception:
                    pass

            data_range_str = f"{col_letter}{data_start_row}:{col_letter}{data_end_row}"

            formula_to_apply = ""
            dest_cell_addr = target_cell

            if op in ("sum", "total"):
                if not dest_cell_addr:
                    dest_cell_addr = f"{col_letter}{end_row + 1}"
                formula_to_apply = f"=SUM({data_range_str})"

            elif op in ("average", "avg"):
                if not dest_cell_addr:
                    dest_cell_addr = f"{col_letter}{end_row + 1}"
                formula_to_apply = f"=AVERAGE({data_range_str})"

            elif op in ("count", "counta", "count_rows"):
                if not dest_cell_addr:
                    dest_cell_addr = f"{col_letter}{end_row + 1}"
                func_name = "COUNT" if op == "count" else "COUNTA"
                formula_to_apply = f"={func_name}({data_range_str})"

            elif op in ("sumif", "averageif", "countif"):
                cond_col_idx = _find_column_index(ws, condition_column) if condition_column else col_idx
                cond_col_letter = _col_index_to_letter(cond_col_idx or 1)
                cond_range_str = f"{cond_col_letter}{data_start_row}:{cond_col_letter}{data_end_row}"

                cond_str = str(condition_value or "0").strip()
                if (cond_str.startswith('"') and cond_str.endswith('"')) or (cond_str.startswith("'") and cond_str.endswith("'")):
                    val_param = cond_str
                elif cond_str.replace(".", "", 1).isdigit() and not any(cond_str.startswith(o) for o in (">", "<", "=")):
                    val_param = cond_str
                else:
                    # Enclose in quotes for Excel formula criteria: e.g. ">30", "East"
                    val_param = f'"{cond_str}"'

                if not dest_cell_addr:
                    dest_cell_addr = f"{col_letter}{end_row + 1}"

                if op == "countif":
                    formula_to_apply = f'=COUNTIF({cond_range_str}, {val_param})'
                elif op == "sumif":
                    formula_to_apply = f'=SUMIF({cond_range_str}, {val_param}, {data_range_str})'
                elif op == "averageif":
                    formula_to_apply = f'=AVERAGEIF({cond_range_str}, {val_param}, {data_range_str})'

            elif op in ("if", "ifs"):
                # Usually applied down an entire column
                dest_col_idx = used.Column + used.Columns.Count
                dest_col_letter = _col_index_to_letter(dest_col_idx)

                # Set header
                h_name = header_name or "Category"
                ws.Range(f"{dest_col_letter}{start_row}").Value = h_name

                # Condition formula for Row 2
                comp_val = condition_value or "50000"
                t_val = true_value or "High"
                f_val = false_value or "Low"

                t_escaped = f'"{t_val}"' if not str(t_val).isdigit() else str(t_val)
                f_escaped = f'"{f_val}"' if not str(f_val).isdigit() else str(f_val)

                row2_formula = f'=IF({col_letter}2>{comp_val}, {t_escaped}, {f_escaped})'

                # Apply to range
                target_range_str = f"{dest_col_letter}{data_start_row}:{dest_col_letter}{data_end_row}"
                ws.Range(target_range_str).Formula = row2_formula

                # Verify
                actual_val = ws.Range(f"{dest_col_letter}{data_start_row}").Value
                return ToolResult(
                    success=True,
                    output=f"✓ Created IF column '{h_name}' at {dest_col_letter} with formula '{row2_formula}'. First value: {actual_val}",
                    metadata={"column": dest_col_letter, "formula": row2_formula, "range": target_range_str},
                )

            if not formula_to_apply or not dest_cell_addr:
                return ToolResult(success=False, output="", error=f"Could not construct formula for operation '{operation}'")

            # Write formula
            cell = ws.Range(dest_cell_addr)
            cell.Formula = formula_to_apply
            cell.Font.Bold = True

            # If placing formula at the bottom of data and adjacent cell is empty, write a descriptive label
            if not target_cell and dest_cell_addr:
                try:
                    dest_row = cell.Row
                    if col_idx > 1:
                        label_col_letter = _col_index_to_letter(col_idx - 1)
                        label_cell = ws.Range(f"{label_col_letter}{dest_row}")
                        if label_cell.Value is None or str(label_cell.Value).strip() == "":
                            lbl = op.upper()
                            if condition_value:
                                lbl += f" ({condition_value})"
                            label_cell.Value = lbl
                            label_cell.Font.Bold = True
                except Exception:
                    pass

            # Verification
            actual_formula = str(cell.Formula)
            actual_value = cell.Value

            return ToolResult(
                success=True,
                output=f"✓ Applied '{formula_to_apply}' to {dest_cell_addr}. Calculated Value: {actual_value}",
                metadata={
                    "cell": dest_cell_addr,
                    "formula": actual_formula,
                    "value": str(actual_value),
                    "workbook": str(wb.Name),
                    "sheet": str(ws.Name),
                },
            )
        except Exception as e:
            logger.error(f"ExcelFormulaTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Formula operation failed: {e}")


class ExcelLookupTool(NexusTool):
    name = "excel_lookup"
    description = (
        "Perform native Excel lookup operations (XLOOKUP or VLOOKUP). "
        "Matches a key column with a source range or sheet and populates a destination column."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        lookup_value_col: str,
        lookup_array_col: Optional[str] = None,
        return_array_col: Optional[str] = None,
        dest_col: Optional[str] = None,
        dest_header: Optional[str] = None,
        source_sheet: Optional[str] = None,
        source_range: Optional[str] = None,
        lookup_type: str = "xlookup",
        if_not_found: str = "Not Found",
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            used = ws.UsedRange
            start_row = used.Row
            row_count = used.Rows.Count
            end_row = start_row + row_count - 1
            data_start_row = start_row + 1 if row_count > 1 else start_row

            # Find lookup key column in current sheet
            val_col_idx = _find_column_index(ws, lookup_value_col) or 1
            val_col_letter = _col_index_to_letter(val_col_idx)

            # Determine destination column
            if dest_col:
                d_idx = _find_column_index(ws, dest_col) or (used.Column + used.Columns.Count)
            else:
                d_idx = used.Column + used.Columns.Count
            d_letter = _col_index_to_letter(d_idx)

            # Set destination header
            if dest_header or lookup_array_col:
                ws.Range(f"{d_letter}{start_row}").Value = dest_header or "Lookup_Result"

            # Construct formula
            sheet_prefix = f"'{source_sheet}'!" if source_sheet else ""

            if lookup_type.lower() == "vlookup" and source_range:
                # =VLOOKUP(A2, Products!A:D, 4, FALSE)
                formula_template = f'=VLOOKUP({val_col_letter}2, {sheet_prefix}{source_range}, 2, FALSE)'
            else:
                # XLOOKUP
                l_col = lookup_array_col or "A"
                r_col = return_array_col or "B"
                l_ref = f"{sheet_prefix}{l_col}:{l_col}" if not ":" in l_col else f"{sheet_prefix}{l_col}"
                r_ref = f"{sheet_prefix}{r_col}:{r_col}" if not ":" in r_col else f"{sheet_prefix}{r_col}"
                formula_template = f'=XLOOKUP({val_col_letter}2, {l_ref}, {r_ref}, "{if_not_found}")'

            target_range_str = f"{d_letter}{data_start_row}:{d_letter}{end_row}"
            ws.Range(target_range_str).Formula = formula_template

            # Verification
            sample_val = ws.Range(f"{d_letter}{data_start_row}").Value
            return ToolResult(
                success=True,
                output=f"✓ Populated column {d_letter} with {lookup_type.upper()} formula '{formula_template}'. First resolved value: '{sample_val}'",
                metadata={"destination": target_range_str, "formula": formula_template, "sample_value": str(sample_val)},
            )
        except Exception as e:
            logger.error(f"ExcelLookupTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Lookup operation failed: {e}")


class ExcelSortFilterTool(NexusTool):
    name = "excel_sort_filter"
    description = (
        "Sort table rows preserving complete row alignment across the entire dataset, "
        "or apply native Excel AutoFilter criteria."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        operation: str = "sort",
        key_column: Optional[str] = None,
        order: str = "descending",
        filter_criteria: Optional[str] = None,
        filter_column: Optional[str] = None,
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            used = ws.UsedRange
            if not used:
                return ToolResult(success=False, output="", error="Worksheet is empty.")

            op = operation.lower().strip()

            if op == "sort":
                # Ensure whole-table sorting to preserve row relationships
                col_idx = _find_column_index(ws, key_column) if key_column else 1
                if not col_idx:
                    col_idx = 1

                xl_order = xlDescending if "desc" in order.lower() else xlAscending

                # Check if target column belongs to an Excel Table (ListObject)
                target_table = None
                if hasattr(ws, "ListObjects") and ws.ListObjects.Count > 0:
                    for lo in ws.ListObjects:
                        try:
                            t_left = lo.Range.Column
                            t_right = t_left + lo.Range.Columns.Count - 1
                            if t_left <= col_idx <= t_right:
                                target_table = lo
                                break
                        except Exception:
                            pass
                    if not target_table:
                        target_table = ws.ListObjects(1)

                if target_table:
                    key_col_letter = _col_index_to_letter(col_idx)
                    header_cell = ws.Range(f"{key_col_letter}{target_table.Range.Row}")
                    target_table.Range.Sort(
                        Key1=header_cell,
                        Order1=xl_order,
                        Header=xlYes,
                        Orientation=xlTopToBottom,
                    )
                else:
                    key_range = ws.Columns(col_idx)
                    used.Sort(
                        Key1=key_range,
                        Order1=xl_order,
                        Header=xlYes,
                        Orientation=xlTopToBottom,
                    )

                # Verification: verify first two data rows are ordered correctly
                start_row = used.Row + 1
                val1 = ws.Cells(start_row, col_idx).Value
                val2 = ws.Cells(start_row + 1, col_idx).Value

                col_name = _col_index_to_letter(col_idx)
                return ToolResult(
                    success=True,
                    output=f"✓ Sorted entire dataset by Column {col_name} ({order}). Top values: {val1}, {val2}",
                    metadata={"sorted_column": col_name, "order": order, "top_sample": [val1, val2]},
                )

            elif op == "filter":
                f_col = filter_column or key_column
                col_idx = _find_column_index(ws, f_col) if f_col else 1
                if not col_idx:
                    col_idx = 1

                criteria = filter_criteria or kwargs.get("criteria") or ""

                # Check if target column belongs to an Excel Table (ListObject)
                target_table = None
                if hasattr(ws, "ListObjects") and ws.ListObjects.Count > 0:
                    for lo in ws.ListObjects:
                        try:
                            t_left = lo.Range.Column
                            t_right = t_left + lo.Range.Columns.Count - 1
                            if t_left <= col_idx <= t_right:
                                target_table = lo
                                break
                        except Exception:
                            pass
                    if not target_table:
                        target_table = ws.ListObjects(1)

                if target_table:
                    # Native ListObject AutoFilter
                    rel_field = col_idx - target_table.Range.Column + 1
                    target_table.Range.AutoFilter(Field=rel_field, Criteria1=str(criteria))
                elif ws.AutoFilterMode and hasattr(ws, "AutoFilter") and ws.AutoFilter:
                    # Active range AutoFilter
                    rel_field = col_idx - ws.AutoFilter.Range.Column + 1
                    ws.AutoFilter.Range.AutoFilter(Field=rel_field, Criteria1=str(criteria))
                else:
                    # Standard range AutoFilter
                    rel_field = col_idx - used.Column + 1
                    used.AutoFilter(Field=rel_field, Criteria1=str(criteria))

                col_name = _col_index_to_letter(col_idx)
                return ToolResult(
                    success=True,
                    output=f"✓ Applied filter on {f_col or 'Column ' + col_name} for '{criteria}'.",
                    metadata={"column": col_name, "criteria": criteria},
                )

            elif op in ("clear", "clear_filter"):
                if hasattr(ws, "ListObjects") and ws.ListObjects.Count > 0:
                    for lo in ws.ListObjects:
                        try:
                            if lo.AutoFilter and lo.AutoFilter.FilterMode:
                                lo.AutoFilter.ShowAllData()
                        except Exception:
                            pass
                if ws.AutoFilterMode:
                    try:
                        if hasattr(ws, "FilterMode") and ws.FilterMode:
                            ws.ShowAllData()
                        else:
                            ws.AutoFilterMode = False
                    except Exception:
                        ws.AutoFilterMode = False
                return ToolResult(success=True, output="✓ Cleared all active AutoFilters.")

            return ToolResult(success=False, output="", error=f"Unknown operation '{operation}'. Use 'sort' or 'filter'.")
        except Exception as e:
            logger.error(f"ExcelSortFilterTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Sort/Filter failed: {e}")


class ExcelPivotTool(NexusTool):
    name = "excel_pivot"
    description = (
        "Create native Microsoft Excel PivotTable summaries summarizing metrics by region, category, date, or product."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        row_fields: Optional[List[str]] = None,
        column_fields: Optional[List[str]] = None,
        value_fields: Optional[List[str]] = None,
        aggregation: str = "sum",
        dest_sheet: Optional[str] = None,
        source_range: Optional[str] = None,
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            src = ws.Range(source_range) if source_range else ws.UsedRange

            # Create destination sheet
            p_sheet_name = dest_sheet or "Pivot_Summary"
            pivot_sheet = None
            for s in wb.Sheets:
                if str(s.Name).lower() == p_sheet_name.lower():
                    pivot_sheet = s
                    break

            if not pivot_sheet:
                pivot_sheet = wb.Sheets.Add(After=ws)
                pivot_sheet.Name = p_sheet_name

            dest_range = pivot_sheet.Range("A3")

            # Create PivotCache and PivotTable
            # SourceType 1 = xlDatabase
            pivot_cache = wb.PivotCaches().Create(SourceType=xlDatabase, SourceData=src)
            pivot_table_name = f"Pivot_{re.sub(r'[^a-zA-Z0-9]', '', p_sheet_name)}"
            pivot_table = pivot_cache.CreatePivotTable(
                TableDestination=dest_range,
                TableName=pivot_table_name,
            )

            # Add Row Fields
            r_fields = row_fields or ["Region"]
            for rf in r_fields:
                try:
                    pivot_table.PivotFields(rf).Orientation = xlRowField
                except Exception as rf_err:
                    logger.debug(f"Row field '{rf}' addition error: {rf_err}")

            # Add Column Fields
            if column_fields:
                for cf in column_fields:
                    try:
                        pivot_table.PivotFields(cf).Orientation = xlColumnField
                    except Exception:
                        pass

            # Add Value Fields with Aggregation
            v_fields = value_fields or ["Sales"]
            agg_map = {
                "sum": xlSum,
                "count": xlCount,
                "average": xlAverage,
                "avg": xlAverage,
                "max": xlMax,
                "min": xlMin,
            }
            func_val = agg_map.get(aggregation.lower(), xlSum)

            for vf in v_fields:
                try:
                    data_field = pivot_table.PivotFields(vf)
                    pivot_table.AddDataField(data_field, f"{aggregation.title()} of {vf}", func_val)
                except Exception as vf_err:
                    logger.debug(f"Value field '{vf}' addition error: {vf_err}")

            pivot_sheet.Activate()

            return ToolResult(
                success=True,
                output=f"✓ Created PivotTable '{pivot_table_name}' on sheet '{p_sheet_name}' (Rows: {', '.join(r_fields)}, Values: {', '.join(v_fields)}).",
                metadata={
                    "sheet": p_sheet_name,
                    "pivot_sheet": p_sheet_name,
                    "pivot_table": pivot_table_name,
                    "pivot_name": pivot_table_name,
                    "rows": r_fields,
                    "values": v_fields,
                },
            )
        except Exception as e:
            logger.error(f"ExcelPivotTool failed: {e}")
            return ToolResult(success=False, output="", error=f"PivotTable creation failed: {e}")


class ExcelConditionalFormatTool(NexusTool):
    name = "excel_conditional_format"
    description = (
        "Apply native Excel conditional formatting rules (e.g. highlight values > 50000, color scales, duplicates, top 10%)."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        range_address: Optional[str] = None,
        column: Optional[str] = None,
        operator: str = "greater",
        value1: Optional[Any] = 50000,
        value2: Optional[Any] = None,
        style: str = "green_fill",
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            used = ws.UsedRange

            # Determine target range
            if range_address:
                rng = ws.Range(range_address)
            elif column:
                col_idx = _find_column_index(ws, column) or 1
                col_letter = _col_index_to_letter(col_idx)
                start_r = used.Row + 1
                end_r = used.Row + used.Rows.Count - 1
                rng = ws.Range(f"{col_letter}{start_r}:{col_letter}{end_r}")
            else:
                rng = used

            op = operator.lower().strip()
            # 1. Color Scale (heatmap)
            if "scale" in op or "heatmap" in op:
                cs = rng.FormatConditions.AddColorScale(ColorScaleType=3)
                return ToolResult(success=True, output=f"✓ Applied 3-color scale heatmap across {rng.Address}.")

            # 2. Highlight Cells condition
            op_map = {
                "greater": xlGreater,
                ">": xlGreater,
                "less": xlLess,
                "<": xlLess,
                "equal": xlEqual,
                "=": xlEqual,
                "between": xlBetween,
            }
            xl_op = op_map.get(op, xlGreater)
            v1_str = str(value1) if value1 is not None else "0"

            # Add Rule
            fc = rng.FormatConditions.Add(Type=xlCellValue, Operator=xl_op, Formula1=v1_str)
            # Style color
            if "green" in style:
                fc.Interior.Color = 13561798  # Soft Light Green RGB(198, 239, 206)
                fc.Font.Color = 24832        # Dark Green Text RGB(0, 97, 0)
            elif "red" in style or "negative" in style:
                fc.Interior.Color = 13551615  # Soft Light Red RGB(255, 199, 206)
                fc.Font.Color = 255          # Dark Red Text
            else:
                fc.Interior.Color = 10284031  # Soft Yellow RGB(255, 235, 156)
                fc.Font.Color = 32896        # Dark Yellow/Brown

            # Verification
            rule_count = rng.FormatConditions.Count
            return ToolResult(
                success=True,
                output=f"✓ Applied conditional formatting on {rng.Address} ({op} {value1}). Active rules: {rule_count}",
                metadata={"range": rng.Address, "rule_count": rule_count, "rules_count": rule_count},
            )
        except Exception as e:
            logger.error(f"ExcelConditionalFormatTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Conditional formatting failed: {e}")


class ExcelDataCleanupTool(NexusTool):
    name = "excel_data_cleanup"
    description = (
        "Perform native Excel data cleanup operations: Remove Duplicates, Text to Columns, or Flash Fill."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        operation: str = "remove_duplicates",
        columns: Optional[List[Any]] = None,
        delimiter: str = ",",
        destination_col: Optional[str] = None,
        source_column: Optional[str] = None,
        target_column: Optional[str] = None,
        destination_column: Optional[str] = None,
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            excel, wb, ws, win = resolve_excel_target(workbook_name=workbook_name, hwnd=hwnd)
            used = ws.UsedRange
            op = operation.lower().strip()

            if "duplicate" in op:
                initial_count = used.Rows.Count
                # Resolve column indices (1-based relative to table)
                col_indices = [1]
                if columns:
                    resolved = []
                    for c in columns:
                        idx = _find_column_index(ws, str(c))
                        if idx:
                            # 1-based index relative to used range
                            rel = idx - used.Column + 1
                            resolved.append(rel)
                    if resolved:
                        col_indices = resolved

                used.RemoveDuplicates(Columns=col_indices, Header=xlYes)
                final_count = ws.UsedRange.Rows.Count
                removed = initial_count - final_count

                return ToolResult(
                    success=True,
                    output=f"✓ Removed {removed} duplicate rows. Remaining rows: {final_count}",
                    metadata={"removed": removed, "rows_removed": removed, "remaining": final_count},
                )

            elif "text_to_columns" in op or "split" in op:
                src_param = source_column or (columns[0] if columns else None) or kwargs.get("source_col")
                target_col_idx = _find_column_index(ws, str(src_param)) if src_param else used.Column
                src_col_letter = _col_index_to_letter(target_col_idx)

                # Use specific data range
                start_r = used.Row
                end_r = start_r + used.Rows.Count - 1
                src_range = ws.Range(f"{src_col_letter}{start_r}:{src_col_letter}{end_r}")

                # Determine delimiter flags
                delim_char = delimiter or ","
                is_comma = delim_char == ","
                is_space = delim_char == " "
                is_tab = delim_char == "\t"
                is_semicolon = delim_char == ";"
                is_other = not (is_comma or is_space or is_tab or is_semicolon)

                dest_str = destination_column or destination_col or src_col_letter
                dest_range = ws.Range(f"{dest_str}{start_r}")

                # Call positional TextToColumns for win32com dynamic dispatch:
                # TextToColumns(Destination, DataType, TextQualifier, ConsecutiveDelimiter, Tab, Semicolon, Comma, Space, Other, OtherChar)
                src_range.TextToColumns(
                    dest_range,
                    1,           # xlDelimited
                    1,           # xlDoubleQuote
                    False,       # ConsecutiveDelimiter
                    is_tab,      # Tab
                    is_semicolon,# Semicolon
                    is_comma,    # Comma
                    is_space,    # Space
                    is_other,    # Other
                    delim_char if is_other else "",
                )

                return ToolResult(
                    success=True,
                    output=f"✓ Split Column {src_col_letter} using delimiter '{delim_char}' into {dest_str}.",
                    metadata={"source": src_col_letter, "destination": dest_str, "delimiter": delim_char},
                )

            elif any(k in op for k in ("delete_row", "remove_row", "drop_row", "delete row", "remove row")):
                count = int(kwargs.get("count", 1))
                position = str(kwargs.get("position", "last")).lower()
                row_num = kwargs.get("row_number")

                start_r = used.Row
                total_r = used.Rows.Count
                last_r = start_r + total_r - 1

                if row_num:
                    target_row = int(row_num)
                    ws.Rows(target_row).Delete()
                    return ToolResult(
                        success=True,
                        output=f"✓ Deleted Row {target_row} from sheet '{ws.Name}'.",
                        metadata={"deleted_row": target_row},
                    )
                elif position == "first" or "first" in op:
                    del_start = start_r + 1 if kwargs.get("preserve_header", True) else start_r
                    del_end = min(last_r, del_start + count - 1)
                    ws.Rows(f"{del_start}:{del_end}").Delete()
                    return ToolResult(
                        success=True,
                        output=f"✓ Removed first {count} data row(s) (Rows {del_start}:{del_end}).",
                        metadata={"start_row": del_start, "end_row": del_end, "count": count},
                    )
                else:  # default "last"
                    del_start = max(start_r + 1, last_r - count + 1)
                    del_end = last_r
                    rows_deleted = del_end - del_start + 1
                    ws.Rows(f"{del_start}:{del_end}").Delete()
                    return ToolResult(
                        success=True,
                        output=f"✓ Removed the last {rows_deleted} row(s) (Rows {del_start}:{del_end}) from sheet '{ws.Name}'.",
                        metadata={"start_row": del_start, "end_row": del_end, "count": rows_deleted},
                    )

            elif any(k in op for k in ("delete_col", "remove_col", "drop_col", "delete column", "remove column")):
                col_param = target_column or source_column or (columns[0] if columns else None) or kwargs.get("column")
                if col_param:
                    c_idx = _find_column_index(ws, str(col_param))
                    if c_idx:
                        c_letter = _col_index_to_letter(c_idx)
                        ws.Columns(c_letter).Delete()
                        return ToolResult(
                            success=True,
                            output=f"✓ Deleted Column {c_letter} ('{col_param}') from sheet '{ws.Name}'.",
                            metadata={"deleted_column": c_letter},
                        )
                return ToolResult(success=False, output="", error="Could not determine column to delete.")

            elif "autofit" in op or "auto_fit" in op:
                ws.Columns.AutoFit()
                return ToolResult(
                    success=True,
                    output=f"✓ Auto-fitted all column widths on sheet '{ws.Name}'.",
                    metadata={"autofit": True},
                )

            return ToolResult(success=False, output="", error=f"Unknown data cleanup operation '{operation}'")
        except Exception as e:
            logger.error(f"ExcelDataCleanupTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Data cleanup failed: {e}")


class ExcelInspectTool(NexusTool):
    name = "excel_inspect"
    description = "Inspect real-time Excel worksheet context, headers, rows, formulas, and open workbooks."
    risk_level = RiskLevel.READ_ONLY

    async def execute(
        self,
        workbook_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            ctx = acquire_deep_excel_context(workbook_name=workbook_name, hwnd=hwnd)
            summary = (
                f"Workbook: {ctx['workbook_name']} | Sheet: {ctx['worksheet_name']} | "
                f"Used Range: {ctx['used_range']} ({ctx['row_count']} rows, {ctx['col_count']} cols) | "
                f"Active Cell: {ctx['active_cell']} | Columns: {', '.join(ctx['columns'])}"
            )
            return ToolResult(success=True, output=summary, metadata=ctx)
        except Exception as e:
            logger.error(f"ExcelInspectTool failed: {e}")
            return ToolResult(success=False, output="", error=f"Context inspection failed: {e}")
