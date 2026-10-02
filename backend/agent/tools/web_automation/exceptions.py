"""Structured exceptions for NEXUS Browser Automation Subsystem."""
from __future__ import annotations


class BrowserAutomationError(Exception):
    """Base exception for all browser automation errors."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class BrowserUnavailable(BrowserAutomationError):
    """Chrome/Edge is not running or remote debugging port is inaccessible."""
    pass


class TargetNotFound(BrowserAutomationError):
    """Specified browser target or page could not be found."""
    pass


class TabNotFound(BrowserAutomationError):
    """Specified browser tab could not be found."""
    pass


class ElementNotFound(BrowserAutomationError):
    """Element matching selector, text, or xpath was not found on the page."""
    pass


class ElementAmbiguous(BrowserAutomationError):
    """Multiple elements matched when a unique element was required."""
    pass


class ElementNotInteractable(BrowserAutomationError):
    """Element exists in DOM but is hidden, disabled, or not clickable."""
    pass


class NavigationError(BrowserAutomationError):
    """Browser failed to navigate to the target URL."""
    pass


class JavaScriptExecutionError(BrowserAutomationError):
    """An unhandled error occurred during JavaScript execution in the browser."""
    pass


class BrowserTimeoutError(BrowserAutomationError):
    """Timed out waiting for condition (element, text, URL change)."""
    pass


class FrameNotFound(BrowserAutomationError):
    """Iframe or subframe target ID was not found."""
    pass


class UnsupportedBrowserState(BrowserAutomationError):
    """The current browser state does not support the requested operation."""
    pass
