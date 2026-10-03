"""NEXUS Microsoft Word Floating Copilot Tools & Runtime Package."""
from backend.agent.tools.word_copilot.tools import (
    word_format_text_tool,
    word_clipboard_op_tool,
    word_find_replace_tool,
    word_format_paragraph_tool,
    word_insert_tool,
    word_presentation_tool,
)
from backend.agent.tools.word_copilot.resolver import (
    get_open_word_windows,
    resolve_word_target,
    WordTargetError,
)
from backend.agent.tools.word_copilot.context import acquire_deep_word_context
from backend.agent.tools.word_copilot.planner import build_word_copilot_plan

__all__ = [
    "word_format_text_tool",
    "word_clipboard_op_tool",
    "word_find_replace_tool",
    "word_format_paragraph_tool",
    "word_insert_tool",
    "word_presentation_tool",
    "get_open_word_windows",
    "resolve_word_target",
    "WordTargetError",
    "acquire_deep_word_context",
    "build_word_copilot_plan",
]
