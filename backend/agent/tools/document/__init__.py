"""DOCX Document Automation tools and adapter package."""
from __future__ import annotations

from backend.agent.tools.document.adapter import docx_adapter, DocxAdapter
from backend.agent.tools.document.models import DocumentStats
from backend.agent.tools.document.verifier import verify_document
from backend.agent.tools.document.tools import (
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

__all__ = [
    "docx_adapter",
    "DocxAdapter",
    "DocumentStats",
    "verify_document",
    "DocxCreateTool",
    "DocxOpenTool",
    "DocxAddTitleTool",
    "DocxAddHeadingTool",
    "DocxAddParagraphTool",
    "DocxAddBulletTool",
    "DocxAddNumberedTool",
    "DocxAddTableTool",
    "DocxAddPageBreakTool",
    "DocxAddImageTool",
    "DocxSaveTool",
    "DocxReadTool",
    "DocxVerifyTool",
    "WordFormatActiveTool",
]
