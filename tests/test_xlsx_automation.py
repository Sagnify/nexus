"""Unit tests for NEXUS Excel / XLSX spreadsheet automation capability."""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path

from backend.agent.tools.registry import tool_registry
from backend.agent.tools.spreadsheet import (
    ExcelAdapter,
    excel_adapter,
    verify_spreadsheet,
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
)


class TestExcelAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.adapter = ExcelAdapter()

    def test_session_lifecycle_and_content(self):
        sid, _ = self.adapter.create_session(initial_sheet="Expenses")
        self.assertTrue(sid.startswith("sheet_"))

        # Write data range
        headers = ["Category", "Jan", "Feb", "Mar"]
        rows = [
            ["Food", 500, 650, 700],
            ["Travel", 1200, 800, 950],
            ["Utilities", 300, 310, 320],
        ]
        self.adapter.write_range(sid, start_cell="A1", values=[headers] + rows)

        # Add summary formulas
        self.adapter.add_formula(sid, cell="B5", formula="=SUM(B2:B4)")
        self.adapter.add_formula(sid, cell="C5", formula="=SUM(C2:C4)")
        self.adapter.add_formula(sid, cell="D5", formula="=SUM(D2:D4)")

        # Format header row
        self.adapter.format_range(sid, range_str="A1:D1", bold=True, fill_color="1F4E78", color="FFFFFF")

        # Create secondary sheet
        self.adapter.create_sheet(sid, title="Summary")
        self.adapter.write_cell(sid, cell="A1", value="Executive Report", sheet="Summary")

        # Create Table and Chart on Expenses sheet
        self.adapter.create_table(sid, range_str="A1:D4", name="ExpenseTable", sheet="Expenses")
        self.adapter.create_chart(sid, chart_type="bar", data_range="B1:D4", title="Quarterly Spending", position="F2", categories_range="A2:A4", sheet="Expenses")

        output_path = Path(self.tmp_dir.name) / "expense_report.xlsx"
        saved_sid, saved_path_str = self.adapter.save_session(sid, str(output_path))
        self.assertEqual(saved_sid, sid)
        self.assertTrue(Path(saved_path_str).exists())

        stats = self.adapter.read_spreadsheet(saved_path_str)
        self.assertTrue(stats.exists)
        self.assertTrue(stats.readable)
        self.assertIn("Expenses", stats.sheet_names)
        self.assertIn("Summary", stats.sheet_names)
        self.assertGreaterEqual(stats.tables, 1)
        self.assertGreaterEqual(stats.charts, 1)
        self.assertGreaterEqual(stats.formulas, 3)

    def test_verification_engine(self):
        sid, _ = self.adapter.create_session(initial_sheet="Data")
        self.adapter.write_range(sid, start_cell="A1", values=[["Item", "Cost"], ["Widget A", 100], ["Widget B", 200]])
        self.adapter.add_formula(sid, cell="B4", formula="=SUM(B2:B3)")
        self.adapter.create_table(sid, range_str="A1:B3", name="WidgetTable")

        output_path = Path(self.tmp_dir.name) / "verify_sheet.xlsx"
        _, saved_path = self.adapter.save_session(sid, str(output_path))

        res = verify_spreadsheet(
            saved_path,
            required_sheets=["Data"],
            min_rows=3,
            require_table=True,
            require_formula=True,
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["verified"])

        # Test failure condition for missing sheet
        failed_res = verify_spreadsheet(
            saved_path,
            required_sheets=["NonexistentSheet"],
        )
        self.assertFalse(failed_res["success"])
        self.assertFalse(failed_res["verified"])
        self.assertIn("Missing required sheet", failed_res["error"])


class TestSpreadsheetToolsInRegistry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_tools_registration(self):
        sheet_tools = [
            "spreadsheet_create", "spreadsheet_open", "spreadsheet_list_sheets",
            "spreadsheet_create_sheet", "spreadsheet_rename_sheet", "spreadsheet_read_cell",
            "spreadsheet_read_range", "spreadsheet_read_sheet", "spreadsheet_write_cell",
            "spreadsheet_write_range", "spreadsheet_add_formula", "spreadsheet_format_range",
            "spreadsheet_create_table", "spreadsheet_create_chart", "spreadsheet_save",
            "spreadsheet_read", "spreadsheet_verify",
        ]
        registered_names = tool_registry.all_names()
        for name in sheet_tools:
            self.assertIn(name, registered_names, f"Tool '{name}' not found in tool_registry")
            tool = tool_registry.get(name)
            self.assertIsNotNone(tool)

    async def test_end_to_end_tool_execution_flow(self):
        create_tool = tool_registry.get("spreadsheet_create")
        write_range_tool = tool_registry.get("spreadsheet_write_range")
        formula_tool = tool_registry.get("spreadsheet_add_formula")
        format_tool = tool_registry.get("spreadsheet_format_range")
        table_tool = tool_registry.get("spreadsheet_create_table")
        chart_tool = tool_registry.get("spreadsheet_create_chart")
        save_tool = tool_registry.get("spreadsheet_save")
        verify_tool = tool_registry.get("spreadsheet_verify")

        # 1. Create workbook
        res_create = await create_tool.execute(initial_sheet="Overview")
        self.assertTrue(res_create.success)
        sid = res_create.metadata["session_id"]

        # 2. Write data grid
        res_write = await write_range_tool.execute(
            session_id=sid,
            start_cell="A1",
            values=[
                ["Metric", "Value"],
                ["Revenue", 50000],
                ["Expenses", 20000],
            ],
        )
        self.assertTrue(res_write.success)

        # 3. Add Net Profit formula
        res_form = await formula_tool.execute(session_id=sid, cell="B4", formula="=B2-B3")
        self.assertTrue(res_form.success)

        # 4. Format header
        res_fmt = await format_tool.execute(session_id=sid, range="A1:B1", bold=True, fill_color="203764", color="FFFFFF")
        self.assertTrue(res_fmt.success)

        # 5. Table and Chart
        res_tbl = await table_tool.execute(session_id=sid, range="A1:B3", name="ProfitTable")
        self.assertTrue(res_tbl.success)

        res_crt = await chart_tool.execute(session_id=sid, chart_type="bar", data_range="B1:B3", title="Financial Summary", position="D2")
        self.assertTrue(res_crt.success)

        # 6. Save file
        target_xlsx = Path(self.tmp_dir.name) / "nexus_e2e_finance.xlsx"
        res_save = await save_tool.execute(session_id=sid, path=str(target_xlsx))
        self.assertTrue(res_save.success)
        self.assertTrue(target_xlsx.exists())

        # 7. Verify file
        res_verify = await verify_tool.execute(
            path=str(target_xlsx),
            required_sheets=["Overview"],
            min_rows=3,
            require_table=True,
            require_chart=True,
            require_formula=True,
        )
        self.assertTrue(res_verify.success)
        self.assertTrue(res_verify.metadata["verified"])


class TestSpreadsheetPlanner(unittest.IsolatedAsyncioTestCase):
    async def test_planner_saves_to_desktop_when_no_path_specified(self):
        from backend.agent.nodes.planner import planner_node
        state = {
            "user_input": "write a excel file of top ten champions league goal scorers with their goal count",
            "goal": "write a excel file of top ten champions league goal scorers with their goal count",
            "intent": "file_op",
        }
        res = await planner_node(state)
        plan = res.get("plan", [])
        self.assertGreaterEqual(len(plan), 4)

        tools = [step["tool"] for step in plan]
        self.assertIn("spreadsheet_create", tools)
        self.assertIn("spreadsheet_write_range", tools)
        self.assertNotIn("ask_user", tools)
        self.assertIn("spreadsheet_save", tools)
        self.assertNotIn("ai_response", tools)
        save_step = next(step for step in plan if step["tool"] == "spreadsheet_save")
        self.assertTrue(save_step["args"]["path"].startswith("Desktop/"))

    async def test_planner_uses_explicit_path_when_specified(self):
        from backend.agent.nodes.planner import planner_node
        state = {
            "user_input": "write a excel file of goal scorers and save to Desktop/scorers.xlsx",
            "goal": "write a excel file of goal scorers and save to Desktop/scorers.xlsx",
            "intent": "file_op",
        }
        res = await planner_node(state)
        plan = res.get("plan", [])
        tools = [step["tool"] for step in plan]
        self.assertIn("spreadsheet_create", tools)
        self.assertIn("spreadsheet_save", tools)
        self.assertNotIn("ask_user", tools)


if __name__ == "__main__":
    unittest.main()
