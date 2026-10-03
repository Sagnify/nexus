"""Central tool registry for all NEXUS tools."""
from __future__ import annotations
from backend.agent.tools.base import NexusTool
from backend.agent.tools.filesystem.read import ReadFileTool, ListDirectoryTool
from backend.agent.tools.filesystem.write import WriteFileTool, DeleteFileTool
from backend.agent.tools.filesystem.search import SearchFilesTool
from backend.agent.tools.shell.execute import RunCommandTool
from backend.agent.tools.web.search import WebSearchTool
from backend.agent.tools.research import DeepResearchTool
from backend.agent.tools.system.datetime_tool import CurrentTimeTool
from backend.agent.tools.system.media_tool import MediaControlTool, PlayMusicTool
from backend.agent.tools.system.schedule_tool import ScheduleTaskTool
from backend.agent.tools.gui.hardware import (
    PressHotkeyTool,
    TypeTextTool,
    PressKeyTool,
    ClickMouseTool,
    ActivateWindowTool,
)
from backend.agent.tools.gui.screen import InspectScreenTool, DismissOverlayTool
from backend.agent.tools.web_automation import (
    BrowserGetTabsTool,
    BrowserSwitchTabTool,
    BrowserNavigateTool,
    BrowserInspectTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserSelectTool,
    BrowserPressTool,
    BrowserWaitTool,
    BrowserDismissPopupTool,
    BrowserExecuteJsTool,
    BrowserGetSourceTool,
    BrowserScrollTool,
)
from backend.agent.tools.document import (
    DocxCreateTool,
    DocxOpenTool,
    DocxAddTitleTool,
    DocxAddHeadingTool,
    DocxAddParagraphTool,
    DocxAddBulletTool,
    DocxAddNumberedTool,
    DocxAddTableTool,
    DocxAddPageBreakTool,
    DocxAddImageTool,
    DocxSaveTool,
    DocxReadTool,
    DocxVerifyTool,
    WordFormatActiveTool,
)
from backend.agent.tools.spreadsheet import (
    SpreadsheetCreateTool,
    SpreadsheetOpenTool,
    SpreadsheetListSheetsTool,
    SpreadsheetCreateSheetTool,
    SpreadsheetRenameSheetTool,
    SpreadsheetReadCellTool,
    SpreadsheetReadRangeTool,
    SpreadsheetReadSheetTool,
    SpreadsheetWriteCellTool,
    SpreadsheetWriteRangeTool,
    SpreadsheetAddFormulaTool,
    SpreadsheetFormatRangeTool,
    SpreadsheetCreateTableTool,
    SpreadsheetCreateChartTool,
    SpreadsheetSaveTool,
    SpreadsheetReadTool,
    SpreadsheetVerifyTool,
    ExcelFormatActiveTool,
)
from backend.agent.tools.presentation import (
    PresentationCreateTool,
    PresentationSaveTool,
    PresentationReadTool,
    PresentationVerifyTool,
)
from backend.agent.tools.excel_copilot import (
    ExcelFormulaTool,
    ExcelLookupTool,
    ExcelSortFilterTool,
    ExcelPivotTool,
    ExcelConditionalFormatTool,
    ExcelDataCleanupTool,
    ExcelInspectTool,
)
from backend.agent.tools.word_copilot.tools import (
    WordFormatTextTool,
    WordClipboardOpTool,
    WordFindReplaceTool,
    WordFormatParagraphTool,
    WordInsertTool,
    WordPresentationTool,
)



class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, NexusTool] = {}
        self._connector_tools: dict[str, set[str]] = {}

    def register(self, tool: NexusTool) -> None:
        self._tools[tool.name] = tool
        # Also register alias if it has dot notation like github.create_issue
        if hasattr(tool, "connector_id") and tool.connector_id:
            cid = tool.connector_id
            if cid not in self._connector_tools:
                self._connector_tools[cid] = set()
            self._connector_tools[cid].add(tool.name)

    def deregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def deregister_connector_tools(self, connector_id: str) -> None:
        tool_names = self._connector_tools.pop(connector_id, set())
        for name in tool_names:
            self._tools.pop(name, None)

    def get(self, name: str) -> NexusTool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def is_connector_tool(self, name: str) -> bool:
        t = self._tools.get(name)
        return bool(t and hasattr(t, "connector_id"))

    def has_connector(self, connector_id: str) -> bool:
        return bool(self._connector_tools.get(connector_id))

    def all_names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[NexusTool]:
        return list(self._tools.values())

    def all_schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def all_connector_tools(self) -> list[NexusTool]:
        return [t for t in self._tools.values() if hasattr(t, "connector_id")]

    def execute(self, name: str, params: dict | None = None):
        tool = self.get(name)
        if not tool:
            from backend.agent.tools.base import ToolResult
            return ToolResult(success=False, error=f"Tool '{name}' not found in registry.")
        return tool.run(**(params or {}))


def create_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ReadFileTool())
    r.register(ListDirectoryTool())
    r.register(WriteFileTool())
    r.register(DeleteFileTool())
    r.register(SearchFilesTool())
    r.register(RunCommandTool())
    r.register(WebSearchTool())
    r.register(DeepResearchTool())
    r.register(CurrentTimeTool())
    r.register(ScheduleTaskTool())
    r.register(MediaControlTool())
    r.register(PlayMusicTool())
    # Structured Browser Automation Tools (CDP & Live DOM)
    r.register(BrowserGetTabsTool())
    r.register(BrowserSwitchTabTool())
    r.register(BrowserNavigateTool())
    r.register(BrowserInspectTool())
    r.register(BrowserClickTool())
    r.register(BrowserTypeTool())
    r.register(BrowserSelectTool())
    r.register(BrowserPressTool())
    r.register(BrowserWaitTool())
    r.register(BrowserDismissPopupTool())
    r.register(BrowserExecuteJsTool())
    r.register(BrowserGetSourceTool())
    r.register(BrowserScrollTool())
    # DOCX Document Automation Tools
    r.register(DocxCreateTool())
    r.register(DocxOpenTool())
    r.register(DocxAddTitleTool())
    r.register(DocxAddHeadingTool())
    r.register(DocxAddParagraphTool())
    r.register(DocxAddBulletTool())
    r.register(DocxAddNumberedTool())
    r.register(DocxAddTableTool())
    r.register(DocxAddPageBreakTool())
    r.register(DocxAddImageTool())
    r.register(DocxSaveTool())
    r.register(DocxReadTool())
    r.register(DocxVerifyTool())
    r.register(WordFormatActiveTool())
    # XLSX Spreadsheet Automation Tools
    r.register(SpreadsheetCreateTool())
    r.register(SpreadsheetOpenTool())
    r.register(SpreadsheetListSheetsTool())
    r.register(SpreadsheetCreateSheetTool())
    r.register(SpreadsheetRenameSheetTool())
    r.register(SpreadsheetReadCellTool())
    r.register(SpreadsheetReadRangeTool())
    r.register(SpreadsheetReadSheetTool())
    r.register(SpreadsheetWriteCellTool())
    r.register(SpreadsheetWriteRangeTool())
    r.register(SpreadsheetAddFormulaTool())
    r.register(SpreadsheetFormatRangeTool())
    r.register(SpreadsheetCreateTableTool())
    r.register(SpreadsheetCreateChartTool())
    r.register(SpreadsheetSaveTool())
    r.register(SpreadsheetReadTool())
    r.register(SpreadsheetVerifyTool())
    r.register(ExcelFormatActiveTool())
    # PowerPoint / PPTX Presentation Automation Tools
    r.register(PresentationCreateTool())
    r.register(PresentationSaveTool())
    r.register(PresentationReadTool())
    r.register(PresentationVerifyTool())
    # Floating Excel Copilot Tools
    r.register(ExcelFormulaTool())
    r.register(ExcelLookupTool())
    r.register(ExcelSortFilterTool())
    r.register(ExcelPivotTool())
    r.register(ExcelConditionalFormatTool())
    r.register(ExcelDataCleanupTool())
    r.register(ExcelInspectTool())
    # Floating Word Copilot Tools
    r.register(WordFormatTextTool())
    r.register(WordClipboardOpTool())
    r.register(WordFindReplaceTool())
    r.register(WordFormatParagraphTool())
    r.register(WordInsertTool())
    r.register(WordPresentationTool())
    # Hardware & GUI Automation Tools (Fallback / OS Controls)
    r.register(PressHotkeyTool())
    r.register(TypeTextTool())
    r.register(PressKeyTool())
    r.register(ClickMouseTool())
    r.register(ActivateWindowTool())
    r.register(InspectScreenTool())
    r.register(DismissOverlayTool())
    return r




tool_registry = create_registry()
