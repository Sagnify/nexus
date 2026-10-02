"""PowerPoint presentation automation package."""
from __future__ import annotations

from backend.agent.tools.presentation.adapter import presentation_adapter, PresentationAdapter
from backend.agent.tools.presentation.models import SlideItem, PresentationData, PresentationStats
from backend.agent.tools.presentation.verifier import verify_presentation
from backend.agent.tools.presentation.tools import (
    PresentationCreateTool,
    PresentationSaveTool,
    PresentationReadTool,
    PresentationVerifyTool,
)

__all__ = [
    "presentation_adapter",
    "PresentationAdapter",
    "SlideItem",
    "PresentationData",
    "PresentationStats",
    "verify_presentation",
    "PresentationCreateTool",
    "PresentationSaveTool",
    "PresentationReadTool",
    "PresentationVerifyTool",
]
