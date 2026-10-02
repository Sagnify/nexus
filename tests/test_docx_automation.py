"""Unit tests for NEXUS DOCX document automation capability."""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path

from backend.agent.tools.registry import tool_registry
from backend.agent.tools.document import (
    DocxAdapter,
    docx_adapter,
    verify_document,
    DocxCreateTool,
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
)


class TestDocxAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.adapter = DocxAdapter()

    def test_session_lifecycle_and_content(self):
        sid, _ = self.adapter.create_session()
        self.assertTrue(sid.startswith("doc_"))

        self.adapter.add_title(sid, "Artificial Intelligence in Education")
        self.adapter.add_heading(sid, "1. Executive Summary", level=1)
        self.adapter.add_paragraph(sid, "AI tools are transforming personalized learning.")
        self.adapter.add_bullet(sid, "Automated grading")
        self.adapter.add_numbered_item(sid, "Step 1: Data collection")

        headers = ["Tool Name", "Category", "Impact Score"]
        rows = [
            ["NEXUS Agent", "Automation", "High"],
            ["LLM Evaluator", "Analysis", "Medium"],
        ]
        self.adapter.add_table(sid, headers=headers, rows=rows)
        self.adapter.add_page_break(sid)
        self.adapter.add_heading(sid, "2. References", level=1)

        output_path = Path(self.tmp_dir.name) / "ai_edu_report.docx"
        saved_sid, saved_path_str = self.adapter.save_session(sid, str(output_path))
        self.assertEqual(saved_sid, sid)
        self.assertTrue(Path(saved_path_str).exists())

        stats = self.adapter.read_document(saved_path_str)
        self.assertTrue(stats.exists)
        self.assertTrue(stats.readable)
        self.assertGreaterEqual(stats.paragraphs, 4)
        self.assertEqual(stats.headings, 2)
        self.assertEqual(stats.tables, 1)
        self.assertIn("1. Executive Summary", stats.heading_titles)
        self.assertIn("2. References", stats.heading_titles)

    def test_verification_engine(self):
        sid, _ = self.adapter.create_session()
        self.adapter.add_title(sid, "Verification Test Document")
        self.adapter.add_heading(sid, "Introduction", level=1)
        self.adapter.add_paragraph(sid, "Sample content line for verification testing.")
        self.adapter.add_table(sid, headers=["Col A", "Col B"], rows=[["Val 1", "Val 2"]])

        output_path = Path(self.tmp_dir.name) / "verify_test.docx"
        _, saved_path = self.adapter.save_session(sid, str(output_path))

        res = verify_document(
            saved_path,
            min_paragraphs=2,
            required_headings=["Introduction"],
            require_table=True,
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["verified"])

        # Test failure condition for missing heading
        failed_res = verify_document(
            saved_path,
            required_headings=["Nonexistent Section Header"],
        )
        self.assertFalse(failed_res["success"])
        self.assertFalse(failed_res["verified"])
        self.assertIn("Missing required heading", failed_res["error"])


class TestDocxToolsInRegistry(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_tools_registration(self):
        doc_tools = [
            "document_create", "document_open", "document_add_title",
            "document_add_heading", "document_add_paragraph", "document_add_bullet",
            "document_add_numbered_item", "document_add_table", "document_add_page_break",
            "document_add_image", "document_save", "document_read", "document_verify",
        ]
        registered_names = tool_registry.all_names()
        for name in doc_tools:
            self.assertIn(name, registered_names, f"Tool '{name}' not found in tool_registry")
            tool = tool_registry.get(name)
            self.assertIsNotNone(tool)

    async def test_end_to_end_tool_execution_flow(self):
        create_tool = tool_registry.get("document_create")
        title_tool = tool_registry.get("document_add_title")
        heading_tool = tool_registry.get("document_add_heading")
        para_tool = tool_registry.get("document_add_paragraph")
        bullet_tool = tool_registry.get("document_add_bullet")
        table_tool = tool_registry.get("document_add_table")
        save_tool = tool_registry.get("document_save")
        verify_tool = tool_registry.get("document_verify")

        # 1. Create document
        res_create = await create_tool.execute()
        self.assertTrue(res_create.success)
        sid = res_create.metadata["session_id"]

        # 2. Populate contents
        res_title = await title_tool.execute(session_id=sid, text="NEXUS Autonomous Research")
        self.assertTrue(res_title.success)

        res_h1 = await heading_tool.execute(session_id=sid, text="1. Overview", level=1)
        self.assertTrue(res_h1.success)

        res_p1 = await para_tool.execute(session_id=sid, text="This report was generated autonomously by NEXUS.")
        self.assertTrue(res_p1.success)

        res_b1 = await bullet_tool.execute(session_id=sid, text="Feature A: Programmatic DOCX editing")
        self.assertTrue(res_b1.success)

        res_tbl = await table_tool.execute(
            session_id=sid,
            headers=["Feature", "Status"],
            rows=[["DOCX Automation", "Verified"]],
        )
        self.assertTrue(res_tbl.success)

        # 3. Save file
        target_docx = Path(self.tmp_dir.name) / "nexus_e2e_report.docx"
        res_save = await save_tool.execute(session_id=sid, path=str(target_docx))
        self.assertTrue(res_save.success)
        self.assertTrue(target_docx.exists())

        # 4. Verify file
        res_verify = await verify_tool.execute(
            path=str(target_docx),
            min_paragraphs=2,
            required_headings=["1. Overview"],
            require_table=True,
        )
        self.assertTrue(res_verify.success)
        self.assertTrue(res_verify.metadata["verified"])


if __name__ == "__main__":
    unittest.main()
