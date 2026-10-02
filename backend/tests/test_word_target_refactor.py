"""Tests for Microsoft Word Live-Editing Layer Refactor using unittest."""
import unittest
import asyncio
from unittest.mock import MagicMock, patch

from backend.core.targets import TargetManager, Target, TargetType, TargetUnavailableException
from backend.agent.tools.document.tools import (
    WordFormatActiveTool,
    resolve_word_target,
    verify_word_mutation,
)
from backend.agent.tools.base import ToolResult


class TestWordTargetRefactor(unittest.TestCase):

    def test_verify_word_mutation_success(self):
        mock_font = MagicMock()
        mock_font.Size = 20.0
        mock_font.Bold = True
        mock_font.Name = "Arial"
        mock_font.Italic = False

        mock_para = MagicMock()
        mock_para.Range.Font = mock_font
        mock_para.Format.Alignment = 1  # center

        mock_doc = MagicMock()
        mock_doc.Paragraphs = [mock_para]
        mock_doc.Content.Font = mock_font

        mock_win = MagicMock()
        mock_win.Selection.Font = mock_font
        mock_win.Selection.Paragraphs = [mock_para]

        mock_word = MagicMock()

        is_verified, changes, err = verify_word_mutation(
            word=mock_word,
            doc=mock_doc,
            win=mock_win,
            scope="selection",
            font_size=20.0,
            bold=True,
            font_name="Arial",
            alignment="center",
        )

        self.assertTrue(is_verified)
        self.assertEqual(changes["font_size"], 20.0)
        self.assertTrue(changes["bold"])
        self.assertEqual(changes["font_name"], "Arial")
        self.assertEqual(changes["alignment"], "center")
        self.assertEqual(err, "")

    def test_verify_word_mutation_failure(self):
        mock_font = MagicMock()
        mock_font.Size = 12.0  # Mismatch (expected 20)
        mock_font.Bold = False  # Mismatch (expected True)

        mock_doc = MagicMock()
        mock_win = MagicMock()
        mock_win.Selection.Font = mock_font
        mock_win.Selection.Paragraphs = []
        mock_word = MagicMock()

        is_verified, changes, err = verify_word_mutation(
            word=mock_word,
            doc=mock_doc,
            win=mock_win,
            scope="selection",
            font_size=20.0,
            bold=True,
        )

        self.assertFalse(is_verified)
        self.assertIn("Mutation verification failed", err)

    def test_resolve_word_target_single_doc(self):
        target = Target(
            id="win_1001",
            application="Microsoft Word",
            window_title="Report.docx - Word",
            process_name="WINWORD.EXE",
            window_id="1001",
            target_type=TargetType.WORD,
        )

        mock_doc = MagicMock()
        mock_doc.Name = "Report.docx"
        mock_win = MagicMock()
        mock_win.Hwnd = 1001
        mock_doc.Windows = [mock_win]

        mock_word = MagicMock()
        mock_word.Documents = [mock_doc]

        with patch("win32com.client.GetActiveObject", return_value=mock_word):
            with patch("os.name", "nt"):
                word_app, resolved_doc, resolved_win = resolve_word_target(target)
                self.assertEqual(resolved_doc, mock_doc)
                self.assertEqual(resolved_win, mock_win)
                mock_doc.Activate.assert_called_once()

    def test_resolve_word_target_multiple_docs_safety(self):
        target_report = Target(
            id="win_1001",
            application="Microsoft Word",
            window_title="Report.docx - Word",
            process_name="WINWORD.EXE",
            window_id="1001",
            target_type=TargetType.WORD,
        )

        target_research = Target(
            id="win_2002",
            application="Microsoft Word",
            window_title="Research.docx - Word",
            process_name="WINWORD.EXE",
            window_id="2002",
            target_type=TargetType.WORD,
        )

        mock_doc_report = MagicMock()
        mock_doc_report.Name = "Report.docx"
        mock_win_report = MagicMock()
        mock_win_report.Hwnd = 1001
        mock_doc_report.Windows = [mock_win_report]

        mock_doc_research = MagicMock()
        mock_doc_research.Name = "Research.docx"
        mock_win_research = MagicMock()
        mock_win_research.Hwnd = 2002
        mock_doc_research.Windows = [mock_win_research]

        mock_word = MagicMock()
        mock_word.Documents = [mock_doc_report, mock_doc_research]

        with patch("win32com.client.GetActiveObject", return_value=mock_word):
            with patch("os.name", "nt"):
                # Select Report.docx -> resolves Report.docx
                _, res_doc_1, _ = resolve_word_target(target_report)
                self.assertEqual(res_doc_1, mock_doc_report)

                # Select Research.docx -> resolves Research.docx
                _, res_doc_2, _ = resolve_word_target(target_research)
                self.assertEqual(res_doc_2, mock_doc_research)

    def test_resolve_word_target_closed_target_error(self):
        target_report = Target(
            id="win_1001",
            application="Microsoft Word",
            window_title="Report.docx - Word",
            process_name="WINWORD.EXE",
            window_id="1001",
            target_type=TargetType.WORD,
        )

        mock_doc_research = MagicMock()
        mock_doc_research.Name = "Research.docx"
        mock_win_research = MagicMock()
        mock_win_research.Hwnd = 2002
        mock_doc_research.Windows = [mock_win_research]

        mock_word = MagicMock()
        mock_word.Documents = [mock_doc_research]

        with patch("win32com.client.GetActiveObject", return_value=mock_word):
            with patch("os.name", "nt"):
                with self.assertRaises(TargetUnavailableException) as exc_ctx:
                    resolve_word_target(target_report)

                self.assertIn("The selected Word document is no longer available", str(exc_ctx.exception))

    def test_word_format_active_tool_closed_target_handling(self):
        tool = WordFormatActiveTool()

        target_report = Target(
            id="win_1001",
            application="Microsoft Word",
            window_title="Report.docx - Word",
            process_name="WINWORD.EXE",
            window_id="1001",
            target_type=TargetType.WORD,
        )

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_report):
            with patch("os.name", "nt"):
                mock_word = MagicMock()
                mock_word.Documents = []
                with patch("win32com.client.GetActiveObject", return_value=mock_word):
                    result: ToolResult = asyncio.run(tool.execute(bold=True))

                    self.assertFalse(result.success)
                    self.assertIn("The selected Word document is no longer available", result.error)

    def test_word_format_active_tool_header_footer_page_number(self):
        tool = WordFormatActiveTool()

        target_report = Target(
            id="win_1001",
            application="Microsoft Word",
            window_title="Report.docx - Word",
            process_name="WINWORD.EXE",
            window_id="1001",
            target_type=TargetType.WORD,
        )

        mock_section = MagicMock()
        mock_doc = MagicMock()
        mock_doc.Name = "Report.docx"
        mock_doc.Sections = [mock_section]

        mock_win = MagicMock()
        mock_win.Hwnd = 1001
        mock_doc.Windows = [mock_win]

        mock_word = MagicMock()
        mock_word.Documents = [mock_doc]

        with patch("backend.core.targets.TargetManager.get_active_target", return_value=target_report):
            with patch("win32com.client.GetActiveObject", return_value=mock_word):
                with patch("backend.core.targets.target_manager.refresh_current_context"):
                    with patch("os.name", "nt"):
                        result: ToolResult = asyncio.run(
                            tool.execute(header="Document Header", footer="Document Footer", page_number=True)
                        )

                        self.assertTrue(result.success)
                        self.assertIn("header='Document Header'", result.output)
                        self.assertIn("footer='Document Footer'", result.output)
                        self.assertIn("page_number=True", result.output)


if __name__ == "__main__":
    unittest.main()
