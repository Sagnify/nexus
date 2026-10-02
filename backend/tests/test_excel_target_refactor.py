"""Tests for Microsoft Excel Live-Formatting Layer Refactor using unittest."""
import unittest
import asyncio
from unittest.mock import MagicMock, patch

from backend.core.targets import TargetManager, Target, TargetType, TargetUnavailableException
from backend.agent.tools.spreadsheet.tools import (
    ExcelFormatActiveTool,
    resolve_excel_target,
    verify_excel_mutation,
)
from backend.agent.tools.base import ToolResult


class TestExcelTargetRefactor(unittest.TestCase):

    def test_verify_excel_mutation_success(self):
        mock_font = MagicMock()
        mock_font.Bold = True
        mock_font.Size = 14.0
        mock_font.Name = "Arial"
        mock_font.Italic = False
        mock_font.Underline = 2

        mock_interior = MagicMock()

        mock_range = MagicMock()
        mock_range.Font = mock_font
        mock_range.Interior = mock_interior
        mock_range.HorizontalAlignment = -4108  # center
        mock_range.VerticalAlignment = -4108    # center
        mock_range.WrapText = True
        mock_range.Value = 100
        mock_range.Formula = None
        mock_range.NumberFormat = "$#,##0.00"

        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_excel = MagicMock()

        is_verified, changes, err = verify_excel_mutation(
            mock_excel,
            mock_wb,
            mock_sheet,
            mock_range,
            value=100,
            bold=True,
            font_size=14.0,
            font_name="Arial",
            alignment="center",
            vertical_alignment="center",
            wrap_text=True,
            number_format="currency",
        )

        self.assertTrue(is_verified)
        self.assertEqual(changes["value"], 100)
        self.assertTrue(changes["bold"])
        self.assertEqual(changes["font_size"], 14.0)
        self.assertEqual(changes["font_name"], "Arial")
        self.assertEqual(changes["alignment"], "center")
        self.assertEqual(changes["vertical_alignment"], "center")
        self.assertTrue(changes["wrap_text"])
        self.assertEqual(changes["number_format"], "$#,##0.00")
        self.assertEqual(err, "")

    def test_verify_excel_mutation_failure(self):
        mock_font = MagicMock()
        mock_font.Bold = False  # Mismatch (expected True)
        mock_font.Size = 11.0   # Mismatch (expected 14)

        mock_range = MagicMock()
        mock_range.Font = mock_font
        mock_range.HorizontalAlignment = -4131 # left
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_excel = MagicMock()

        is_verified, changes, err = verify_excel_mutation(
            mock_excel,
            mock_wb,
            mock_sheet,
            mock_range,
            bold=True,
            font_size=14.0,
        )

        self.assertFalse(is_verified)
        self.assertIn("Excel verification failed", err)

    def test_resolve_excel_target_single_wb(self):
        target = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Budget.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_win = MagicMock()
        mock_win.Hwnd = 1001

        mock_sheet = MagicMock()

        mock_wb = MagicMock()
        mock_wb.Name = "Budget.xlsx"
        mock_wb.Windows = [mock_win]
        mock_wb.ActiveSheet = mock_sheet

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb]

        with patch("win32com.client.GetActiveObject", return_value=mock_excel):
            with patch("os.name", "nt"):
                excel_app, resolved_wb, resolved_sheet, resolved_win = resolve_excel_target(target)
                self.assertEqual(resolved_wb, mock_wb)
                self.assertEqual(resolved_sheet, mock_sheet)
                mock_wb.Activate.assert_called_once()

    def test_resolve_excel_target_multiple_wbs_safety(self):
        target_budget = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Budget.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        target_research = Target(
            id="win_2002",
            application="Microsoft Excel",
            window_title="Research.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="2002",
            target_type=TargetType.EXCEL,
        )

        mock_win_budget = MagicMock()
        mock_win_budget.Hwnd = 1001
        mock_sheet_budget = MagicMock()
        mock_wb_budget = MagicMock()
        mock_wb_budget.Name = "Budget.xlsx"
        mock_wb_budget.Windows = [mock_win_budget]
        mock_wb_budget.ActiveSheet = mock_sheet_budget

        mock_win_research = MagicMock()
        mock_win_research.Hwnd = 2002
        mock_sheet_research = MagicMock()
        mock_wb_research = MagicMock()
        mock_wb_research.Name = "Research.xlsx"
        mock_wb_research.Windows = [mock_win_research]
        mock_wb_research.ActiveSheet = mock_sheet_research

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb_budget, mock_wb_research]

        with patch("win32com.client.GetActiveObject", return_value=mock_excel):
            with patch("os.name", "nt"):
                # Select Budget.xlsx -> resolves Budget.xlsx
                _, res_wb_1, res_sheet_1, _ = resolve_excel_target(target_budget)
                self.assertEqual(res_wb_1, mock_wb_budget)
                self.assertEqual(res_sheet_1, mock_sheet_budget)

                # Select Research.xlsx -> resolves Research.xlsx
                _, res_wb_2, res_sheet_2, _ = resolve_excel_target(target_research)
                self.assertEqual(res_wb_2, mock_wb_research)
                self.assertEqual(res_sheet_2, mock_sheet_research)

    def test_resolve_excel_target_closed_target_error(self):
        target_budget = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Budget.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_win_research = MagicMock()
        mock_win_research.Hwnd = 2002
        mock_wb_research = MagicMock()
        mock_wb_research.Name = "Research.xlsx"
        mock_wb_research.Windows = [mock_win_research]

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb_research]

        with patch("win32com.client.GetActiveObject", return_value=mock_excel):
            with patch("os.name", "nt"):
                with self.assertRaises(TargetUnavailableException) as exc_ctx:
                    resolve_excel_target(target_budget)

                self.assertIn("The selected Excel target is no longer available", str(exc_ctx.exception))

    def test_excel_format_active_tool_closed_target_handling(self):
        tool = ExcelFormatActiveTool()

        target_budget = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Budget.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_budget):
            with patch("os.name", "nt"):
                mock_excel = MagicMock()
                mock_excel.Workbooks = []
                with patch("win32com.client.GetActiveObject", return_value=mock_excel):
                    result: ToolResult = asyncio.run(tool.execute(bold=True))

                    self.assertFalse(result.success)
                    self.assertIn("The selected Excel target is no longer available", result.error)

    def test_excel_format_active_tool_successful_formatting(self):
        tool = ExcelFormatActiveTool()

        target_budget = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Budget.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_font = MagicMock()
        mock_font.Bold = True
        mock_font.Size = 14.0

        mock_range = MagicMock()
        mock_range.Font = mock_font

        mock_sheet = MagicMock()
        mock_sheet.Range.return_value = mock_range

        mock_win = MagicMock()
        mock_win.Hwnd = 1001

        mock_wb = MagicMock()
        mock_wb.Name = "Budget.xlsx"
        mock_wb.Windows = [mock_win]
        mock_wb.ActiveSheet = mock_sheet

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb]
        mock_excel.Selection = mock_range

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_budget):
            with patch("win32com.client.GetActiveObject", return_value=mock_excel):
                with patch("backend.core.targets.target_manager.refresh_current_context"):
                    with patch("os.name", "nt"):
                        result: ToolResult = asyncio.run(
                            tool.execute(range_address="B5", bold=True, font_size=14.0)
                        )

                        self.assertTrue(result.success)
                        self.assertIn("bold=True", result.output)
                        self.assertIn("font_size=14.0", result.output)
                        mock_sheet.Range.assert_called_with("B5")

    def test_spreadsheet_read_sheet_tool_com_reading(self):
        from backend.agent.tools.spreadsheet.tools import SpreadsheetReadSheetTool

        tool = SpreadsheetReadSheetTool()

        target_goals = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Goals.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_used_range = MagicMock()
        mock_used_range.Value = (
            ("Player", "Goals"),
            ("Ronaldo", 140),
            ("Messi", 129),
        )

        mock_sheet = MagicMock()
        mock_sheet.Name = "Sheet1"
        mock_sheet.UsedRange = mock_used_range

        mock_win = MagicMock()
        mock_win.Hwnd = 1001

        mock_wb = MagicMock()
        mock_wb.Name = "Goals.xlsx"
        mock_wb.Windows = [mock_win]
        mock_wb.ActiveSheet = mock_sheet
        mock_wb.Sheets = [mock_sheet]

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb]

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_goals):
            with patch("win32com.client.GetActiveObject", return_value=mock_excel):
                with patch("os.name", "nt"):
                    result: ToolResult = asyncio.run(tool.execute())

                    self.assertTrue(result.success)
                    self.assertIn("Ronaldo", result.output)
                    self.assertIn("140", result.output)
                    self.assertIn("Messi", result.output)

    def test_spreadsheet_save_tool_com_saving(self):
        from backend.agent.tools.spreadsheet.tools import SpreadsheetSaveTool

        tool = SpreadsheetSaveTool()

        target_goals = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Goals.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_sheet = MagicMock()
        mock_win = MagicMock()
        mock_win.Hwnd = 1001

        mock_wb = MagicMock()
        mock_wb.Name = "Goals.xlsx"
        mock_wb.FullName = "C:\\Users\\user\\Desktop\\Goals.xlsx"
        mock_wb.Windows = [mock_win]
        mock_wb.ActiveSheet = mock_sheet

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb]

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_goals):
            with patch("win32com.client.GetActiveObject", return_value=mock_excel):
                with patch("backend.core.targets.target_manager.refresh_current_context"):
                    with patch("os.name", "nt"):
                        result: ToolResult = asyncio.run(tool.execute())

                        self.assertTrue(result.success)
                        mock_wb.Save.assert_called_once()
                        self.assertIn("Saved active Excel workbook", result.output)

    def test_excel_format_active_smart_header_sum(self):
        tool = ExcelFormatActiveTool()

        target_goals = Target(
            id="win_1001",
            application="Microsoft Excel",
            window_title="Goals.xlsx - Excel",
            process_name="EXCEL.EXE",
            window_id="1001",
            target_type=TargetType.EXCEL,
        )

        mock_font = MagicMock()
        mock_font.Bold = True

        mock_target_cell = MagicMock()
        mock_target_cell.Font = mock_font
        mock_target_cell.Address = "$C$12"

        mock_cell_header_1 = MagicMock()
        mock_cell_header_1.Value = "Player"
        mock_cell_header_2 = MagicMock()
        mock_cell_header_2.Value = "Goals"

        def mock_cells(r, c):
            if r == 1 and c == 1:
                return mock_cell_header_1
            if r == 1 and c == 2:
                return mock_cell_header_2
            return mock_target_cell

        mock_sheet = MagicMock()
        mock_sheet.Cells = MagicMock(side_effect=mock_cells)
        mock_sheet.Rows.Count = 1048576

        mock_end_obj = MagicMock()
        mock_end_obj.Row = 11
        mock_sheet.Cells(1048576, 2).End.return_value = mock_end_obj

        mock_win = MagicMock()
        mock_win.Hwnd = 1001

        mock_wb = MagicMock()
        mock_wb.Name = "Goals.xlsx"
        mock_wb.Windows = [mock_win]
        mock_wb.ActiveSheet = mock_sheet

        mock_excel = MagicMock()
        mock_excel.Workbooks = [mock_wb]

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_goals):
            with patch("win32com.client.GetActiveObject", return_value=mock_excel):
                with patch("backend.core.targets.target_manager.refresh_current_context"):
                    with patch("os.name", "nt"):
                        result: ToolResult = asyncio.run(tool.execute(range_address="goals", bold=True))

                        self.assertTrue(result.success)
                        self.assertEqual(mock_target_cell.Formula, "=SUM(B2:B11)")
                        self.assertEqual(mock_target_cell.Font.Bold, True)


if __name__ == "__main__":
    unittest.main()
