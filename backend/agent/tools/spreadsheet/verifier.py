"""Verification engine for Excel / XLSX spreadsheet artifacts."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from backend.agent.tools.spreadsheet.adapter import excel_adapter
from backend.agent.tools.spreadsheet.models import SpreadsheetStats


def verify_spreadsheet(
    path_or_session: str,
    required_sheets: Optional[list[str]] = None,
    min_rows: int = 1,
    require_table: bool = False,
    require_chart: bool = False,
    require_formula: bool = False,
) -> dict[str, Any]:
    """Verify a generated or modified XLSX spreadsheet against quality & structural criteria."""
    stats: SpreadsheetStats = excel_adapter.read_spreadsheet(path_or_session)

    if not stats.exists:
        return {
            "success": False,
            "verified": False,
            "error": f"File does not exist: '{stats.path}'",
            "stats": stats.to_dict(),
        }

    if not stats.readable:
        return {
            "success": False,
            "verified": False,
            "error": f"File is corrupted or not a valid .xlsx workbook: '{stats.path}'",
            "stats": stats.to_dict(),
        }

    failures = []

    if stats.total_cells_populated < min_rows:
        failures.append(f"Populated cells count ({stats.total_cells_populated}) below minimum ({min_rows}).")

    if required_sheets:
        existing_lower = [s.lower() for s in stats.sheet_names]
        for req in required_sheets:
            if req.lower() not in existing_lower:
                failures.append(f"Missing required sheet: '{req}'")

    if require_table and stats.tables < 1:
        failures.append("Spreadsheet missing expected Excel table object.")

    if require_chart and stats.charts < 1:
        failures.append("Spreadsheet missing expected Excel chart object.")

    if require_formula and stats.formulas < 1:
        failures.append("Spreadsheet missing expected calculation formula.")

    if failures:
        return {
            "success": False,
            "verified": False,
            "error": "Spreadsheet verification failed criteria: " + " | ".join(failures),
            "stats": stats.to_dict(),
        }

    return {
        "success": True,
        "verified": True,
        "message": "Spreadsheet verified successfully.",
        "stats": stats.to_dict(),
    }
