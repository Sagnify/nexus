"""
Skill Execution Router
Detects skill composition and routes to appropriate UI overlay (extension pill vs desktop pill).
"""
from __future__ import annotations
import logging
from typing import Optional
from backend.agent.state import PlanStep
from backend.core.policies import RiskLevel

logger = logging.getLogger("nexus.skill_executor")

# Browser-only tools that work exclusively in the extension pill
BROWSER_TOOLS = {
    "browser_navigate", "browser_inspect", "browser_click", "browser_type",
    "browser_select", "browser_press", "browser_wait", "browser_get_tabs",
    "browser_switch_tab", "browser_dismiss_popup", "browser_execute_js",
    "browser_get_source", "browser_scroll",
}

# Desktop/system tools that require the desktop pill
DESKTOP_TOOLS = {
    "inspect_screen", "press_hotkey", "type_text", "press_key",
    "click_mouse", "activate_window", "dismiss_overlay",
    "play_music", "media_control", "run_command",
    "read_file", "write_file", "delete_file", "list_directory", "search_files",
    "docx_create", "docx_open", "docx_add_title", "docx_add_heading",
    "docx_add_paragraph", "docx_add_bullet", "docx_add_numbered",
    "docx_add_table", "docx_add_page_break", "docx_add_image",
    "docx_save", "docx_read", "docx_verify", "word_format_active",
    "spreadsheet_create", "spreadsheet_open", "spreadsheet_list_sheets",
    "spreadsheet_create_sheet", "spreadsheet_rename_sheet", "spreadsheet_read_cell",
    "spreadsheet_read_range", "spreadsheet_read_sheet", "spreadsheet_write_cell",
    "spreadsheet_write_range", "spreadsheet_add_formula", "spreadsheet_format_range",
    "spreadsheet_create_table", "spreadsheet_create_chart", "spreadsheet_save",
    "spreadsheet_read", "spreadsheet_verify", "excel_format_active",
}

# AI/system tools that work with desktop pill
SYSTEM_TOOLS = {
    "ai_response", "ask_user", "web_search", "get_current_time",
}


class SkillCompositionAnalyzer:
    """Analyzes skill steps to determine execution environment."""

    @staticmethod
    def analyze_plan(plan: list[dict]) -> dict:
        """
        Analyze plan steps and determine:
        - is_web_only: True if all steps are browser tools
        - is_desktop_only: True if all steps are desktop tools
        - is_mixed: True if both browser and desktop tools present
        - recommended_pill: "extension" | "desktop"
        """
        if not plan:
            return {
                "is_web_only": False,
                "is_desktop_only": False,
                "is_mixed": False,
                "recommended_pill": "desktop",
                "browser_tool_count": 0,
                "desktop_tool_count": 0,
                "system_tool_count": 0,
            }

        browser_count = 0
        desktop_count = 0
        system_count = 0

        for step in plan:
            tool = step.get("tool", "").lower()
            if tool in BROWSER_TOOLS:
                browser_count += 1
            elif tool in DESKTOP_TOOLS:
                desktop_count += 1
            elif tool in SYSTEM_TOOLS:
                system_count += 1

        is_web_only = browser_count > 0 and desktop_count == 0
        is_desktop_only = desktop_count > 0 and browser_count == 0
        is_mixed = browser_count > 0 and desktop_count > 0

        # Recommendation logic
        if is_web_only:
            recommended_pill = "extension"
        elif is_desktop_only or is_mixed:
            recommended_pill = "desktop"
        else:
            recommended_pill = "desktop"  # Default fallback

        return {
            "is_web_only": is_web_only,
            "is_desktop_only": is_desktop_only,
            "is_mixed": is_mixed,
            "recommended_pill": recommended_pill,
            "browser_tool_count": browser_count,
            "desktop_tool_count": desktop_count,
            "system_tool_count": system_count,
        }

    @staticmethod
    def should_use_extension_pill(plan: list[dict]) -> bool:
        """Returns True if skill should use extension pill (web-only)."""
        analysis = SkillCompositionAnalyzer.analyze_plan(plan)
        return analysis["recommended_pill"] == "extension"


def get_skill_execution_context(plan: list[dict]) -> dict:
    """
    Returns execution context for a skill, including which pill to use.
    """
    analysis = SkillCompositionAnalyzer.analyze_plan(plan)

    return {
        "use_extension_pill": analysis["recommended_pill"] == "extension",
        "use_desktop_pill": analysis["recommended_pill"] == "desktop",
        "composition": analysis,
        "pill_type": analysis["recommended_pill"],
    }
