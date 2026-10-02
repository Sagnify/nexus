"""NEXUS Floating Excel Copilot & Real-Time Spreadsheet Operations package."""
from backend.agent.tools.excel_copilot.resolver import (
    resolve_excel_target,
    get_open_excel_windows,
    ExcelTargetError,
)
from backend.agent.tools.excel_copilot.context import (
    acquire_deep_excel_context,
)
from backend.agent.tools.excel_copilot.tools import (
    ExcelFormulaTool,
    ExcelLookupTool,
    ExcelSortFilterTool,
    ExcelPivotTool,
    ExcelConditionalFormatTool,
    ExcelDataCleanupTool,
    ExcelInspectTool,
)

__all__ = [
    "resolve_excel_target",
    "get_open_excel_windows",
    "ExcelTargetError",
    "acquire_deep_excel_context",
    "ExcelFormulaTool",
    "ExcelLookupTool",
    "ExcelSortFilterTool",
    "ExcelPivotTool",
    "ExcelConditionalFormatTool",
    "ExcelDataCleanupTool",
    "ExcelInspectTool",
]
