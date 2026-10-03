import pytest
from backend.agent.tools.word_copilot.planner import build_word_copilot_plan
from backend.agent.tools.registry import tool_registry
from backend.agent.tools.word_copilot.tools import (
    WordFormatTextTool,
    WordClipboardOpTool,
    WordFindReplaceTool,
    WordFormatParagraphTool,
    WordInsertTool,
    WordPresentationTool,
)


def plan(instruction: str):
    return build_word_copilot_plan(instruction, {}, {})


def get_params(step):
    return step.get("args") or step.get("parameters") or {}


def test_word_tools_registered():
    """Verify all Word Copilot tools are correctly registered in the global registry."""
    assert tool_registry.get("word_format_text") is not None
    assert isinstance(tool_registry.get("word_format_text"), WordFormatTextTool)

    assert tool_registry.get("word_clipboard_op") is not None
    assert isinstance(tool_registry.get("word_clipboard_op"), WordClipboardOpTool)

    assert tool_registry.get("word_find_replace") is not None
    assert isinstance(tool_registry.get("word_find_replace"), WordFindReplaceTool)

    assert tool_registry.get("word_format_paragraph") is not None
    assert isinstance(tool_registry.get("word_format_paragraph"), WordFormatParagraphTool)

    assert tool_registry.get("word_insert") is not None
    assert isinstance(tool_registry.get("word_insert"), WordInsertTool)

    assert tool_registry.get("word_create_presentation") is not None
    assert isinstance(tool_registry.get("word_create_presentation"), WordPresentationTool)


def test_planner_feature_1_text_formatting():
    """Verify deterministic planning for Text Formatting features."""
    # Bold
    plan_bold = plan("Make the selected text bold")
    assert plan_bold is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("bold") is True for step in plan_bold)

    # Italic
    plan_italic = plan("italicize the selected text")
    assert plan_italic is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("italic") is True for step in plan_italic)

    # Underline
    plan_underline = plan("Underline the current line")
    assert plan_underline is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("underline") is True for step in plan_underline)

    # Font Size
    plan_size = plan("Change font size to 16")
    assert plan_size is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("font_size") == 16.0 for step in plan_size)

    # Font Color
    plan_color = plan("Change color to blue")
    assert plan_color is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("font_color") == "blue" for step in plan_color)

    # Highlight
    plan_highlight = plan("Highlight yellow")
    assert plan_highlight is not None
    assert any(step["tool"] == "word_format_text" and get_params(step).get("highlight_color") == "yellow" for step in plan_highlight)


def test_planner_feature_2_clipboard_operations():
    """Verify deterministic planning for Copy, Cut, Paste, and Duplicate features."""
    # Copy
    plan_copy = plan("Copy the selected text to clipboard")
    assert plan_copy is not None
    assert any(step["tool"] == "word_clipboard_op" and get_params(step).get("operation") == "copy" for step in plan_copy)

    # Cut
    plan_cut = plan("Cut this text")
    assert plan_cut is not None
    assert any(step["tool"] == "word_clipboard_op" and get_params(step).get("operation") == "cut" for step in plan_cut)

    # Paste
    plan_paste = plan("Paste clipboard content here")
    assert plan_paste is not None
    assert any(step["tool"] == "word_clipboard_op" and get_params(step).get("operation") == "paste" for step in plan_paste)

    # Duplicate
    plan_dup = plan("Duplicate current paragraph")
    assert plan_dup is not None
    assert any(step["tool"] == "word_clipboard_op" and get_params(step).get("operation") == "duplicate" for step in plan_dup)


def test_planner_feature_3_find_replace():
    """Verify deterministic planning for Find & Replace features."""
    plan_replace = plan('Replace all occurrences of "draft" with "final"')
    assert plan_replace is not None
    assert any(
        step["tool"] == "word_find_replace"
        and get_params(step).get("find_text") == "draft"
        and get_params(step).get("replace_with") == "final"
        for step in plan_replace
    )


def test_planner_feature_4_paragraph_formatting():
    """Verify deterministic planning for Paragraph Formatting features."""
    # Center alignment
    plan_center = plan("Center align this paragraph")
    assert plan_center is not None
    assert any(step["tool"] == "word_format_paragraph" and get_params(step).get("alignment") == "center" for step in plan_center)

    # Justify alignment
    plan_justify = plan("Justify the text")
    assert plan_justify is not None
    assert any(step["tool"] == "word_format_paragraph" and get_params(step).get("alignment") == "justify" for step in plan_justify)

    # Line spacing
    plan_spacing = plan("Set line spacing to 1.5")
    assert plan_spacing is not None
    assert any(step["tool"] == "word_format_paragraph" and get_params(step).get("line_spacing") == 1.5 for step in plan_spacing)

    # Bullets
    plan_bullets = plan("Convert selection to bullet list")
    assert plan_bullets is not None
    assert any(step["tool"] == "word_format_paragraph" and get_params(step).get("bullets") == "bullet" for step in plan_bullets)

    # Numbering
    plan_numbering = plan("Make numbered list")
    assert plan_numbering is not None
    assert any(step["tool"] == "word_format_paragraph" and get_params(step).get("bullets") == "number" for step in plan_numbering)


def test_planner_feature_5_insert_operations():
    """Verify deterministic planning for Insert Operations features."""
    # Table insertion
    plan_table = plan("Insert a table with 3 rows and 4 columns")
    assert plan_table is not None
    assert any(
        step["tool"] == "word_insert"
        and get_params(step).get("item_type") == "table"
        and get_params(step).get("rows") == 3
        and get_params(step).get("cols") == 4
        for step in plan_table
    )

    # Page Break
    plan_break = plan("Insert a page break")
    assert plan_break is not None
    assert any(
        step["tool"] == "word_insert"
        and get_params(step).get("item_type") == "page_break"
        for step in plan_break
    )

    # Header / Footer
    plan_header = plan("Add document header with page number")
    assert plan_header is not None
    assert any(
        step["tool"] == "word_insert"
        and get_params(step).get("item_type") == "header"
        for step in plan_header
    )

    # Hyperlink
    plan_link = plan("Insert a link to https://github.com with text Github")
    assert plan_link is not None
    assert any(
        step["tool"] == "word_insert"
        and get_params(step).get("item_type") == "hyperlink"
        and "https://github.com" in get_params(step).get("url", "")
        for step in plan_link
    )


def test_planner_feature_6_powerpoint_presentation():
    """Verify deterministic planning for PowerPoint presentation generation from Word context."""
    # The user's exact prompt
    plan_ppt = plan("take the context from the word file and make a powerpoint presentation on that context or topic and save it in desktop")
    assert plan_ppt is not None
    assert any(
        step["tool"] == "word_create_presentation"
        and get_params(step).get("output_path") == "Desktop"
        for step in plan_ppt
    )

    # Shorter prompt with custom topic
    plan_topic = plan("Create a PowerPoint presentation on Artificial Intelligence and save to desktop")
    assert plan_topic is not None
    assert any(
        step["tool"] == "word_create_presentation"
        and get_params(step).get("topic") == "Artificial Intelligence"
        and get_params(step).get("output_path") == "Desktop"
        for step in plan_topic
    )


def test_word_api_endpoints():
    """Verify Word Copilot FastAPI endpoints respond with valid schemas."""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # 1. GET /api/nexus/word/windows
    res_win = client.get("/api/nexus/word/windows")
    assert res_win.status_code == 200
    data_win = res_win.json()
    assert "windows" in data_win
    assert isinstance(data_win["windows"], list)

    # 2. GET /api/nexus/word/context (when no Word window is bound)
    res_ctx = client.get("/api/nexus/word/context")
    assert res_ctx.status_code in (200, 404)

    # 3. POST /api/nexus/word/execute with invalid / empty prompt
    res_exec = client.post("/api/nexus/word/execute", json={"instruction": ""})
    # Either 400 bad request or handled failure
    assert res_exec.status_code in (200, 400)


def test_presentation_safe_filename_and_context_synthesis():
    """Verify that multi-line topic strings and newlines are sanitized and produce valid pptx."""
    from backend.agent.tools.presentation.adapter import sanitize_safe_filename, presentation_adapter

    dirty_topic = (
        "Agentic_Ai_And_Explain_It_Executive_Summary\n\nDocument_Context\n"
        "Source_Document_Agentic_Ai_And_Explain_It\n"
        "Key_Headings_Executive_Summary_Detailed_Analysis__Findings_Key_Recommendations\n"
        "Content_Excerpts:\n- Report: Agentic Ai\n"
    )
    safe = sanitize_safe_filename(dirty_topic)
    assert "\n" not in safe
    assert "\r" not in safe
    assert len(safe) <= 50
    assert safe == "Agentic_Ai_And_Explain_It_Executive_Summary"

    # Verify fallback presentation synthesis with headings and bullets
    data = presentation_adapter.synthesize_fallback_presentation_data(
        topic=dirty_topic,
        headings=["Executive Summary", "Detailed Analysis", "Key Recommendations"],
        bullets=["Point 1: High operational efficiency", "Point 2: Autonomous reasoning", "Point 3: Resilient fallback"],
    )
    assert "\n" not in data.topic
    assert "\n" not in data.title
    assert len(data.slides) == 6
    assert data.slides[0].title == "Agentic Ai And Explain It Executive Summary"


