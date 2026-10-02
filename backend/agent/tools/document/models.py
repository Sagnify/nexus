"""Data models for DOCX document automation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DocumentStats:
    path: str
    session_id: str = ""
    paragraphs: int = 0
    headings: int = 0
    tables: int = 0
    characters: int = 0
    sections: int = 0
    exists: bool = False
    readable: bool = False
    heading_titles: list[str] = field(default_factory=list)
    table_dimensions: list[dict[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "session_id": self.session_id,
            "paragraphs": self.paragraphs,
            "headings": self.headings,
            "tables": self.tables,
            "characters": self.characters,
            "sections": self.sections,
            "exists": self.exists,
            "readable": self.readable,
            "heading_titles": self.heading_titles,
            "table_dimensions": self.table_dimensions,
        }
