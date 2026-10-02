"""NEXUS Structured Browser Automation Subsystem."""
from backend.agent.tools.web_automation.driver import BrowserAutomationEngine, CDPBackend
from backend.agent.tools.web_automation.models import BrowserState, InteractiveElement, TabInfo, FrameInfo
from backend.agent.tools.web_automation.tools import (
    BrowserGetTabsTool,
    BrowserSwitchTabTool,
    BrowserNavigateTool,
    BrowserInspectTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserSelectTool,
    BrowserPressTool,
    BrowserWaitTool,
    BrowserDismissPopupTool,
    BrowserExecuteJsTool,
    BrowserGetSourceTool,
    BrowserScrollTool,
)

__all__ = [
    "BrowserAutomationEngine",
    "CDPBackend",
    "BrowserState",
    "InteractiveElement",
    "TabInfo",
    "FrameInfo",
    "BrowserGetTabsTool",
    "BrowserSwitchTabTool",
    "BrowserNavigateTool",
    "BrowserInspectTool",
    "BrowserClickTool",
    "BrowserTypeTool",
    "BrowserSelectTool",
    "BrowserPressTool",
    "BrowserWaitTool",
    "BrowserDismissPopupTool",
    "BrowserExecuteJsTool",
    "BrowserGetSourceTool",
    "BrowserScrollTool",
]
