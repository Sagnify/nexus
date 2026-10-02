"""Deterministic compiler and fast-path planner for natural-language Excel Copilot commands.

Translates user requests directly into structured Excel tool executions:
- Formula (SUM, SUMIF, AVERAGE, AVERAGEIF, COUNT, COUNTA, COUNTIF, IF, IFS)
- Lookup (XLOOKUP, VLOOKUP)
- Sort & Filter (Whole-table sorting, AutoFilter)
- PivotTables (Rows, Cols, Values, Aggregation)
- Conditional Formatting (Highlight cells, Heatmaps, Color Scales)
- Data Cleanup (Remove Duplicates, Text to Columns, Flash Fill, Delete Rows/Cols, Autofit)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.excel_copilot.planner")


def _stem(word: str) -> str:
    """Normalize simple plurals and common suffixes for header matching."""
    w = word.lower().strip()
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("es") and not w.endswith("ses"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _clean_header_name(name: str) -> str:
    """Strip bracketed/parenthesized annotations: 'Goals (2015-2025)' -> 'Goals'."""
    clean = re.sub(r"\(.*?\)|\[.*?\]", "", str(name)).strip()
    return clean or str(name)


def _match_header(token: str, context_headers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Match a token or phrase against known context headers."""
    clean = _stem(token)
    for h in context_headers:
        h_name = str(h.get("name", "")).strip()
        if not h_name:
            continue
        h_stem = _stem(h_name)
        if clean == h_stem or clean == h_name.lower():
            return h

        # Match against cleaned base name (e.g. "Goals" from "Goals (2015-2025)")
        c_base = _clean_header_name(h_name)
        c_stem = _stem(c_base)
        if clean == c_stem or clean == c_base.lower():
            return h

        # Token match within base name (e.g. "total" or "sales" in "Total Sales ($)")
        tokens = [t.lower() for t in re.findall(r"\b[A-Za-z_]+\b", c_base)]
        if clean in tokens or any(_stem(t) == clean for t in tokens):
            return h

    return None


def _extract_all_headers_in_text(text: str, context_headers: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """Find all occurrences of context headers within text, ordered by their character position."""
    matches = []
    tokens = list(re.finditer(r"\b[A-Za-z_]+\b", text))
    for t in tokens:
        word = t.group(0)
        h = _match_header(word, context_headers)
        if h:
            matches.append((t.start(), h))
    return sorted(matches, key=lambda x: x[0])


def _extract_column_reference(text: str, context_headers: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """Attempt to extract primary column name or letter from instruction text."""
    # 1. Look for explicit column mentions: e.g. "column F", "column B", "Sales column"
    m_col = re.search(r"\bcolumn\s+([A-Za-z]+)\b", text, re.IGNORECASE)
    if m_col:
        return m_col.group(1).upper()

    m_name_col = re.search(r"\b([A-Za-z_]+)\s+column\b", text, re.IGNORECASE)
    if m_name_col:
        return m_name_col.group(1).strip()

    # 2. Match from context headers
    if context_headers:
        matches = _extract_all_headers_in_text(text, context_headers)
        if matches:
            # Prefer numeric column if not explicit
            for _, h in matches:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    return h.get("name")
            return matches[0][1].get("name")

    # 3. Look for common finance/sales column names
    common_cols = ("sales", "goals", "revenue", "profit", "cost", "price", "amount", "customer", "region", "category", "date", "status", "name", "id", "email")
    for c in common_cols:
        if re.search(rf"\b{c}\b", text, re.IGNORECASE):
            return c.title()

    return None


def _extract_condition_info(text: str, context_headers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract numeric or text criteria and associate with the appropriate column."""
    lower = text.lower()
    clean = lower.replace(",", "")

    # 1. Numeric comparisons: e.g. "more than 30", "> 30", "at least 30", "< 15", "above 50"
    m_gt = re.search(r"(?:more than|greater than|above|over|exceeding|higher than|at least|>=|>)\s*(\d+(?:\.\d+)?)", clean)
    if m_gt:
        num_val = m_gt.group(1)
        # Check if immediately followed by header: e.g. "30 goals"
        m_after = re.search(r"(?:more than|greater than|above|over|exceeding|higher than|at least|>=|>)\s*" + re.escape(num_val) + r"\s*([a-zA-Z_]+)", clean)
        cond_col = None
        if m_after:
            h = _match_header(m_after.group(1), context_headers)
            if h:
                cond_col = h["name"]

        # Check if immediately preceded by header: e.g. "goals > 30", "goals more than 30"
        if not cond_col:
            m_before = re.search(r"([a-zA-Z_]+)\s*(?:more than|greater than|above|over|exceeding|higher than|at least|>=|>)", clean)
            if m_before:
                h = _match_header(m_before.group(1), context_headers)
                if h:
                    cond_col = h["name"]

        # Default to first numeric header if not explicitly attached
        if not cond_col:
            for h in context_headers:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    cond_col = h["name"]
                    break

        return {
            "operator": ">",
            "number": float(num_val) if "." in num_val else int(num_val),
            "excel_condition": f">{num_val}",
            "condition_column": cond_col or "Goals",
        }

    m_lt = re.search(r"(?:less than|fewer than|below|under|smaller than|at most|<=|<)\s*(\d+(?:\.\d+)?)", clean)
    if m_lt:
        num_val = m_lt.group(1)
        m_after = re.search(r"(?:less than|fewer than|below|under|smaller than|at most|<=|<)\s*" + re.escape(num_val) + r"\s*([a-zA-Z_]+)", clean)
        cond_col = None
        if m_after:
            h = _match_header(m_after.group(1), context_headers)
            if h:
                cond_col = h["name"]

        if not cond_col:
            m_before = re.search(r"([a-zA-Z_]+)\s*(?:less than|fewer than|below|under|smaller than|at most|<=|<)", clean)
            if m_before:
                h = _match_header(m_before.group(1), context_headers)
                if h:
                    cond_col = h["name"]

        if not cond_col:
            for h in context_headers:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    cond_col = h["name"]
                    break

        return {
            "operator": "<",
            "number": float(num_val) if "." in num_val else int(num_val),
            "excel_condition": f"<{num_val}",
            "condition_column": cond_col or "Goals",
        }

    # 2. Text conditions: e.g. "where region is East", "for Ronaldo"
    m_txt = re.search(r"\b(?:for\s+the|for|where|in|is|equal to)\s+([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?)\b", text)
    if m_txt:
        val = m_txt.group(1).strip()
        cond_col = None
        for h in context_headers:
            if h.get("type") == "text":
                cond_col = h["name"]
                break
        return {
            "operator": "=",
            "number": None,
            "excel_condition": val.title(),
            "condition_column": cond_col or "Player",
        }

    return None


def _extract_number(text: str) -> Optional[float]:
    """Extract numeric threshold value from instruction text."""
    clean = text.replace(",", "")
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", clean)
    if m:
        try:
            return float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        except ValueError:
            pass
    return None


def build_excel_copilot_plan(
    goal: str,
    active_target: Optional[Dict[str, Any]] = None,
    active_context: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Translate natural language Excel request into a structured execution plan.
    Returns None if the instruction is ambiguous or requires generic LLM planning.
    """
    lower = goal.lower().strip()

    # Extract target identifiers
    hwnd = None
    wb_name = None
    if active_target:
        wid = active_target.get("window_id")
        if wid and str(wid).isdigit():
            hwnd = int(wid)
        wb_name = active_target.get("window_title")

    context_headers = []
    if active_context and "details" in active_context:
        context_headers = active_context["details"].get("headers", [])
    elif active_context and "headers" in active_context:
        context_headers = active_context.get("headers", [])

    matched_headers = _extract_all_headers_in_text(goal, context_headers)
    cond = _extract_condition_info(goal, context_headers)
    col = _extract_column_reference(goal, context_headers)
    num = _extract_number(goal)

    # ---------------------------------------------------------
    # 1. PIVOT TABLE
    # ---------------------------------------------------------
    if any(w in lower for w in ("pivot", "pivottable", "pivot table")):
        row_fields = ["Region"]
        val_fields = ["Sales"]
        agg = "sum"

        if "average" in lower or "avg" in lower:
            agg = "average"
        elif "count" in lower:
            agg = "count"

        m_by = re.search(r"\bby\s+([A-Za-z_]+)\b", lower)
        if m_by:
            h = _match_header(m_by.group(1), context_headers)
            row_fields = [h["name"] if h else m_by.group(1).title()]
        else:
            # Use first text column
            for h in context_headers:
                if h.get("type") == "text":
                    row_fields = [h["name"]]
                    break

        # Value fields: prefer numeric
        for h in context_headers:
            if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                val_fields = [h["name"]]
                break

        return [
            {
                "title": f"Create PivotTable",
                "description": f"Create native Excel PivotTable by {', '.join(row_fields)} summarizing {', '.join(val_fields)}",
                "tool": "excel_pivot",
                "args": {
                    "row_fields": row_fields,
                    "value_fields": val_fields,
                    "aggregation": agg,
                    "dest_sheet": "Pivot_Summary",
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 2. CONDITIONAL FORMATTING / HIGHLIGHT
    # ---------------------------------------------------------
    if any(w in lower for w in ("highlight", "color scale", "heatmap", "format conditions", "stand out", "color cells", "red", "green")):
        operator = "greater"
        val = (cond["number"] if cond and cond.get("number") is not None else num) or 50000
        target_c = cond["condition_column"] if cond else (col or "Sales")
        style = "green_fill"

        if any(w in lower for w in ("less", "below", "under", "smaller", "negative", "fewer")):
            operator = "less"
            style = "red_fill"
            if "negative" in lower and not num:
                val = 0
        elif any(w in lower for w in ("equal", "matches")):
            operator = "equal"
        elif any(w in lower for w in ("color scale", "heatmap", "gradient")):
            operator = "color_scale"

        return [
            {
                "title": f"Apply Conditional Formatting",
                "description": f"Highlight cells in {target_c} ({operator} {val})",
                "tool": "excel_conditional_format",
                "args": {
                    "column": target_c,
                    "operator": operator,
                    "value1": val,
                    "style": style,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 3. FILTER
    # ---------------------------------------------------------
    is_filter_verb = any(w in lower for w in ("filter", "show only", "display only", "show", "display", "list", "view", "find", "keep only", "get"))
    has_agg_keyword = any(w in lower for w in ("total", "sum", "add up", "average", "avg", "mean", "count", "how many", "highlight", "color", "of", "pivot", "order by", "sort"))
    is_entity_filter = bool(cond and not has_agg_keyword)

    if is_filter_verb or is_entity_filter:
        crit = cond["excel_condition"] if cond else "East"
        filter_col = cond["condition_column"] if cond else (col or "Region")

        return [
            {
                "title": f"Filter Table",
                "description": f"Apply filter on {filter_col} for '{crit}'",
                "tool": "excel_sort_filter",
                "args": {
                    "operation": "filter",
                    "filter_column": filter_col,
                    "filter_criteria": crit,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 4. SORT
    # ---------------------------------------------------------
    if any(w in lower for w in ("sort", "order by", "arrange")):
        order = "descending" if any(w in lower for w in ("highest", "descending", "desc", "largest", "biggest", "top to bottom")) else "ascending"
        sort_key = None
        m_by = re.search(r"\bby\s+([A-Za-z_]+)\b", lower)
        if m_by:
            h = _match_header(m_by.group(1), context_headers)
            if h:
                sort_key = h["name"]
            else:
                sort_key = m_by.group(1).title()

        if not sort_key and cond:
            sort_key = cond["condition_column"]

        if not sort_key:
            # Prefer first numeric column in matched headers
            for _, h in matched_headers:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    sort_key = h["name"]
                    break

        if not sort_key:
            sort_key = col or "Sales"

        return [
            {
                "title": f"Sort Table",
                "description": f"Sort entire dataset by {sort_key} ({order})",
                "tool": "excel_sort_filter",
                "args": {
                    "operation": "sort",
                    "key_column": sort_key,
                    "order": order,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 5. XLOOKUP / VLOOKUP
    # ---------------------------------------------------------
    if any(w in lower for w in ("xlookup", "vlookup", "lookup", "match these customer", "bring the")):
        l_type = "vlookup" if "vlookup" in lower else "xlookup"
        dest_c = "F"
        m_dest = re.search(r"\bcolumn\s+([A-Za-z])\b", lower)
        if m_dest:
            dest_c = m_dest.group(1).upper()

        return [
            {
                "title": f"Execute {l_type.upper()}",
                "description": f"Populate column {dest_c} using {l_type.upper()}",
                "tool": "excel_lookup",
                "args": {
                    "lookup_type": l_type,
                    "lookup_value_col": col or "Customer ID",
                    "dest_col": dest_c,
                    "dest_header": col or "Category",
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 6. DATA CLEANUP (Duplicates, Delete Rows/Columns, Text to Columns, Flash Fill)
    # ---------------------------------------------------------
    if any(w in lower for w in ("remove row", "delete row", "drop row", "remove the last", "delete the last", "remove last", "delete last", "remove the first", "delete the first", "clear the last")):
        count = 1
        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        for word, val in word_to_num.items():
            if f"{word} row" in lower or f"{word} rows" in lower:
                count = val
                break
        else:
            m_cnt = re.search(r"\b(\d+)\s+rows?\b", lower)
            if m_cnt:
                count = int(m_cnt.group(1))

        m_specific = re.search(r"\brow\s+(\d+)\b", lower)
        specific_row = int(m_specific.group(1)) if m_specific and not any(w in lower for w in ("last", "first")) else None
        position = "first" if "first" in lower else "last"

        return [
            {
                "title": f"Delete Row(s)",
                "description": f"Remove {count} row(s) ({position})" if not specific_row else f"Remove row {specific_row}",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "delete_rows",
                    "count": count,
                    "position": position,
                    "row_number": specific_row,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    if any(w in lower for w in ("remove column", "delete column", "drop column")):
        col_to_del = col or "D"
        return [
            {
                "title": f"Delete Column",
                "description": f"Delete column {col_to_del}",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "delete_columns",
                    "target_column": col_to_del,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    if any(w in lower for w in ("autofit", "auto-fit", "fit columns", "adjust column width")):
        return [
            {
                "title": "AutoFit Columns",
                "description": "Auto-fit all column widths in active sheet",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "autofit",
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    if any(w in lower for w in ("remove duplicate", "drop duplicate", "delete duplicate", "deduplicate")):
        return [
            {
                "title": f"Remove Duplicate Rows",
                "description": f"Deduplicate table based on {col or 'key columns'}",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "remove_duplicates",
                    "columns": [col] if col else None,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    if any(w in lower for w in ("split", "text to column", "separate")):
        delim = ","
        if "comma" in lower:
            delim = ","
        elif "space" in lower:
            delim = " "
        elif "hyphen" in lower or "dash" in lower:
            delim = "-"
        return [
            {
                "title": f"Text to Columns",
                "description": f"Split {col or 'column'} using delimiter '{delim}'",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "text_to_columns",
                    "columns": [col] if col else None,
                    "delimiter": delim,
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    if any(w in lower for w in ("flash fill", "extract the first", "extract first name", "extract username", "format these names")):
        return [
            {
                "title": "Execute Flash Fill",
                "description": "Trigger native Excel Flash Fill to extract pattern",
                "tool": "excel_data_cleanup",
                "args": {
                    "operation": "flash_fill",
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 7. IF / IFS
    # ---------------------------------------------------------
    if (re.search(r"\b(if|when|case|classify)\b", lower) or "otherwise" in lower) and any(w in lower for w in ("column", "create a column", "new column", "says", "classify", "otherwise")):
        cond_val = str((cond["number"] if cond and cond.get("number") is not None else num) or 50000)
        t_val = "High"
        f_val = "Low"
        m_tf = re.search(r"\bsays?\s+([A-Za-z0-9_]+)\b.*?\b(?:and\s+)?([A-Za-z0-9_]+)\s+otherwise\b", lower)
        if m_tf:
            t_val = m_tf.group(1).title()
            f_val = m_tf.group(2).title()

        target_c = cond["condition_column"] if cond else (col or "Sales")

        return [
            {
                "title": f"Add Conditional IF Column",
                "description": f"Create IF column based on {target_c} (>{cond_val} ? {t_val} : {f_val})",
                "tool": "excel_formula",
                "args": {
                    "operation": "if",
                    "target_column": target_c,
                    "condition_value": cond_val,
                    "true_value": t_val,
                    "false_value": f_val,
                    "header_name": "Category",
                    "hwnd": hwnd,
                    "workbook_name": wb_name,
                },
            }
        ]

    # ---------------------------------------------------------
    # 8. COUNT / COUNTA / COUNTIF
    # ---------------------------------------------------------
    if any(w in lower for w in ("count", "how many", "number of")):
        if cond:
            return [
                {
                    "title": "Calculate COUNTIF",
                    "description": f"Count entries where {cond['condition_column']} is {cond['excel_condition']}",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "countif",
                        "condition_column": cond["condition_column"],
                        "condition_value": cond["excel_condition"],
                        "target_column": cond["condition_column"],
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]
        else:
            return [
                {
                    "title": f"Calculate Count",
                    "description": f"Count entries in {col or 'target column'}",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "counta" if any(w in lower for w in ("customer", "player", "order", "entry", "non-empty")) else "count",
                        "target_column": col or "A",
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]

    # ---------------------------------------------------------
    # 9. AVERAGE / AVERAGEIF
    # ---------------------------------------------------------
    if any(w in lower for w in ("average", "avg", "mean")):
        # Determine target numeric column
        target_col = None
        for _, h in matched_headers:
            if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                target_col = h["name"]
                break
        if not target_col and cond and cond.get("condition_column"):
            for h in context_headers:
                if h.get("name") == cond["condition_column"] and h.get("type") == "numeric":
                    target_col = h["name"]
                    break
        if not target_col:
            for h in context_headers:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    target_col = h["name"]
                    break
        if not target_col and matched_headers:
            target_col = matched_headers[0][1]["name"]
        target_col = target_col or col or "Sales"

        if cond:
            return [
                {
                    "title": "Calculate AVERAGEIF",
                    "description": f"Calculate average {target_col} for {cond['condition_column']} {cond['excel_condition']}",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "averageif",
                        "target_column": target_col,
                        "condition_column": cond["condition_column"],
                        "condition_value": cond["excel_condition"],
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]
        else:
            return [
                {
                    "title": "Calculate Average",
                    "description": f"Calculate average of {target_col} with native AVERAGE formula",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "average",
                        "target_column": target_col,
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]

    # ---------------------------------------------------------
    # 10. SUM / SUMIF
    # ---------------------------------------------------------
    # Triggers on:
    # - explicit verbs: "total", "sum", "add up", "calculate sum"
    # - OR implicit aggregation requests with condition: e.g. "goals of players with more than 30 goals"
    # - OR query mentioning a numeric header followed by condition
    is_sum_verb = any(w in lower for w in ("total", "sum", "add up", "calculate sum"))
    first_header_numeric = bool(matched_headers and matched_headers[0][1].get("type") == "numeric")
    has_of_structure = bool(re.search(r"\b[A-Za-z_]+\s+of\s+[A-Za-z_]+\b", lower))

    if is_sum_verb or (cond and (first_header_numeric or has_of_structure or any(w in lower for w in ("goals", "sales", "revenue", "amount", "profit")))):
        target_col = None
        for _, h in matched_headers:
            if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                target_col = h["name"]
                break
        if not target_col and cond and cond.get("condition_column"):
            for h in context_headers:
                if h.get("name") == cond["condition_column"] and h.get("type") == "numeric":
                    target_col = h["name"]
                    break
        if not target_col:
            for h in context_headers:
                if h.get("type") == "numeric" and h.get("name", "").lower() not in ("rank", "id"):
                    target_col = h["name"]
                    break
        if not target_col and matched_headers:
            target_col = matched_headers[0][1]["name"]
        target_col = target_col or col or "Sales"

        if cond:
            return [
                {
                    "title": "Calculate SUMIF",
                    "description": f"Calculate total {target_col} where {cond['condition_column']} {cond['excel_condition']}",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "sumif",
                        "target_column": target_col,
                        "condition_column": cond["condition_column"],
                        "condition_value": cond["excel_condition"],
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]
        else:
            return [
                {
                    "title": "Calculate Total",
                    "description": f"Calculate total {target_col} with native SUM formula",
                    "tool": "excel_formula",
                    "args": {
                        "operation": "sum",
                        "target_column": target_col,
                        "hwnd": hwnd,
                        "workbook_name": wb_name,
                    },
                }
            ]

    return None
