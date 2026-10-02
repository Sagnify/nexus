"""Verification engine for DOCX document artifacts."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from backend.agent.tools.document.adapter import docx_adapter
from backend.agent.tools.document.models import DocumentStats


def verify_document(
    path_or_session: str,
    min_paragraphs: int = 1,
    required_headings: Optional[list[str]] = None,
    require_table: bool = False,
) -> dict[str, Any]:
    """Verify a generated or modified DOCX document against quality & structural criteria."""
    stats: DocumentStats = docx_adapter.read_document(path_or_session)

    if not stats.exists:
        return {
            "success": False,
            "verified": False,
            "error": f"File does not exist: '{stats.path}'",
            "stats": stats.to_dict(),
        }

    if not stats.readable:
        return {
            "success": False,
            "verified": False,
            "error": f"File is corrupted or not a valid .docx document: '{stats.path}'",
            "stats": stats.to_dict(),
        }

    failures = []

    if stats.paragraphs < min_paragraphs:
        failures.append(f"Paragraph count ({stats.paragraphs}) below required minimum ({min_paragraphs}).")

    if require_table and stats.tables < 1:
        failures.append("Document missing expected data table.")

    if required_headings:
        existing_lower = [h.lower() for h in stats.heading_titles]
        for req in required_headings:
            if not any(req.lower() in title for title in existing_lower):
                failures.append(f"Missing required heading containing: '{req}'")

    if failures:
        return {
            "success": False,
            "verified": False,
            "error": "Document verification failed criteria: " + " | ".join(failures),
            "stats": stats.to_dict(),
        }

    return {
        "success": True,
        "verified": True,
        "message": "Document verified successfully.",
        "stats": stats.to_dict(),
    }
