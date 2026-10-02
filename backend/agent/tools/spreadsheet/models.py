"""Data models for Excel / XLSX spreadsheet automation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SpreadsheetStats:
    path: str
    session_id: str = ""
    sheet_names: list[str] = field(default_factory=list)
    active_sheet: str = ""
    total_sheets: int = 0
    tables: int = 0
    charts: int = 0
    formulas: int = 0
    total_cells_populated: int = 0
    exists: bool = False
    readable: bool = False
    sheet_dimensions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "session_id": self.session_id,
            "sheet_names": self.sheet_names,
            "active_sheet": self.active_sheet,
            "total_sheets": self.total_sheets,
            "tables": self.tables,
            "charts": self.charts,
            "formulas": self.formulas,
            "total_cells_populated": self.total_cells_populated,
            "exists": self.exists,
            "readable": self.readable,
            "sheet_dimensions": self.sheet_dimensions,
        }
