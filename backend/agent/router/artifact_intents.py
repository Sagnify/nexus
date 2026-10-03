"""Deterministic intent helpers for generated office files."""
from __future__ import annotations

import re


_ARTIFACT_CREATION_RE = re.compile(
    r"\b(?:word\s+(?:file|doc|document|report)|report\s+in\s+word|docx?|excel\s+(?:file|sheet|workbook|spreadsheet)|"
    r"spreadsheet|xlsx|csv|powerpoint|power\s+point|pptx?|presentation|slide\s+deck|slides?)\b",
    re.IGNORECASE,
)
_CREATION_ACTION_RE = re.compile(
    r"\b(?:create|make|generate|write|build|produce|prepare|export|save)\b",
    re.IGNORECASE,
)


def is_artifact_creation_request(text: str) -> bool:
    """Recognize direct Word, Excel, or PowerPoint file-generation requests."""
    return bool(text and _ARTIFACT_CREATION_RE.search(text) and _CREATION_ACTION_RE.search(text))