"""Data models for structured browser state and element representation."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


@dataclass
class InteractiveElement:
    """Structured representation of a DOM element for the LLM planner."""
    id: str = ""
    tag: str = ""
    type: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    text: Optional[str] = None
    placeholder: Optional[str] = None
    value: Optional[str] = None
    selector: str = ""
    xpath: str = ""
    visible: bool = True
    enabled: bool = True
    aria_label: Optional[str] = None
    href: Optional[str] = None
    frame_id: Optional[str] = None
    shadow_host: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop keys with None or empty default values to keep token usage compact
        return {k: v for k, v in d.items() if v is not None and v != ""}


@dataclass
class TabInfo:
    """Information about an open browser tab/target."""
    id: str
    title: str
    url: str
    type: str = "page"
    webSocketDebuggerUrl: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameInfo:
    """Information about an iframe or frame boundary within a page."""
    id: str
    url: str
    name: Optional[str] = None
    parentId: Optional[str] = None
    securityOrigin: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class BrowserState:
    """High-level structured state of the active browser context."""
    url: str
    title: str
    active_target: str
    tabs: list[TabInfo] = field(default_factory=list)
    frames: list[FrameInfo] = field(default_factory=list)
    interactive_elements: list[InteractiveElement] = field(default_factory=list)
    focused_element: Optional[str] = None
    console_errors: list[str] = field(default_factory=list)
    navigation_state: str = "complete"  # "loading" | "interactive" | "complete"

    def to_compact_dict(self, max_elements: int = 60) -> dict[str, Any]:
        """Convert to a compact dictionary optimized for LLM context."""
        return {
            "url": self.url,
            "title": self.title,
            "active_tab_id": self.active_target,
            "open_tabs": [
                {"id": t.id, "title": t.title, "url": t.url}
                for t in self.tabs
            ],
            "frames_detected": len(self.frames),
            "frame_urls": [f.url for f in self.frames if f.url] if self.frames else [],
            "focused_element": self.focused_element,
            "interactive_elements_count": len(self.interactive_elements),
            "interactive_elements": [
                el.to_dict() for el in self.interactive_elements[:max_elements]
            ],
            "truncated_elements": max(0, len(self.interactive_elements) - max_elements),
            "console_errors": self.console_errors[-5:] if self.console_errors else [],
        }
