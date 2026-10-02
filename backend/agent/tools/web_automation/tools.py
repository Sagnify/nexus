"""Discrete NEXUS tools for structured browser automation."""
from __future__ import annotations
import json
import logging
import re
from typing import Any
import asyncio
import inspect
from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.web_automation.driver import BrowserAutomationEngine
from backend.agent.tools.web_automation.extension_bridge import extension_bridge
from backend.agent.tools.web_automation.exceptions import BrowserAutomationError

logger = logging.getLogger("nexus.tools.browser")

EXTENSION_OFFLINE_ERROR = """[NEXUS Chrome Extension Not Connected]

The NEXUS Chrome Companion Extension is not connected to the local bridge.

How to fix and connect in 3 seconds:
1. In Chrome, go to: chrome://extensions
2. Click the 🔄 (Reload) button on the 'NEXUS Browser Companion' extension card.
3. Open the extension popup from your Chrome toolbar and click 'Reconnect Bridge' (verify it shows 🟢 Connected).

Debug Details:
• WebSocket Bridge: ws://127.0.0.1:8000/ws/extension (Active)
• Local Extension Path: D:\\Codes\\nexus\\extension"""


async def _check_browser_running(engine) -> bool:
    try:
        fn = getattr(engine, "is_browser_running", None)
        if fn is None:
            return True
        res = fn()
        if asyncio.iscoroutine(res) or inspect.isawaitable(res):
            return await res
        return bool(res)
    except Exception:
        return False


class BrowserGetTabsTool(NexusTool):
    """Lists all open tabs/pages in Chrome/Edge."""
    name = "browser_get_tabs"
    description = "List all open browser tabs and discover their titles, URLs, and target IDs."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, **kwargs) -> ToolResult:
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("get_tabs")
                tabs_data = res.get("tabs", [])
                active_tab_id = res.get("active_tab_id")
                return ToolResult(
                    success=True,
                    output=json.dumps({"tabs_count": len(tabs_data), "active_tab_id": active_tab_id, "tabs": tabs_data}, indent=2),
                    metadata={"tabs": tabs_data, "active_tab_id": active_tab_id},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension error getting tabs: {e}")

        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                tabs = await engine.get_tabs()
                tabs_data = [t.to_dict() for t in tabs]
                return ToolResult(
                    success=True,
                    output=json.dumps({"tabs_count": len(tabs_data), "tabs": tabs_data}, indent=2),
                    metadata={"tabs": tabs_data},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Failed to get tabs: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserSwitchTabTool(NexusTool):
    """Switches the active browser tab by target ID, URL, or page title."""
    name = "browser_switch_tab"
    description = "Switch the active browser focus and CDP connection to a specific tab ID, URL, or title."
    risk_level = RiskLevel.SAFE

    async def execute(self, target_id: Any = "", **kwargs) -> ToolResult:
        tab_id = target_id or kwargs.get("tab_id") or kwargs.get("id") or kwargs.get("target") or ""
        url_match = kwargs.get("url") or kwargs.get("url_match") or ""
        title_match = kwargs.get("title") or kwargs.get("title_match") or ""

        if not tab_id and not url_match and not title_match:
            return ToolResult(
                success=False,
                output="",
                error="Missing required argument: provide 'target_id' (or 'tab_id'), 'url', or 'title' of the tab to switch to.",
            )

        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("switch_tab", {
                    "tab_id": tab_id,
                    "target_id": tab_id,
                    "url": url_match,
                    "title": title_match,
                })
                active_id = res.get("tab_id", tab_id)
                return ToolResult(
                    success=True,
                    output=f"Switched to tab '{res.get('title', 'Unknown')}' ({res.get('url', '')}) [ID: {active_id}].",
                    metadata={"active_tab": res},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension error switching tab: {e}")

        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                target_str = str(tab_id or url_match or title_match)
                tab = await engine.switch_tab(target_str)
                return ToolResult(
                    success=True,
                    output=f"Switched to tab '{tab.title}' ({tab.url}) [ID: {tab.id}].",
                    metadata={"active_tab": tab.to_dict()},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Failed to switch tab: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserNavigateTool(NexusTool):
    """Navigates the browser to a URL or opens a new tab."""
    name = "browser_navigate"
    description = "Navigate the active browser tab or open a new tab to a specific URL."
    risk_level = RiskLevel.SAFE

    async def execute(self, url: str = "", new_tab: bool = False, **kwargs) -> ToolResult:
        if not url:
            return ToolResult(success=False, output="", error="Missing required argument: 'url'.")

        if not url.startswith(("http://", "https://", "file://", "about:", "chrome://")):
            url = f"https://{url}"

        # 1. Wait for Extension Bridge
        if await extension_bridge.wait_for_connection(timeout_seconds=3.0):
            try:
                res = await extension_bridge.send_command("navigate", {"url": url, "new_tab": new_tab})
                action_info = res.get("action", "navigated")
                tab_info = f" [tab: {res.get('tab_id')}]" if res.get("tab_id") else ""
                return ToolResult(
                    success=True,
                    output=f"Successfully navigated to '{url}' via NEXUS Chrome Companion Extension ({action_info}{tab_info}).",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension navigation error: {e}")

        # 2. Try CDP Engine if running
        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.navigate(url=url, new_tab=new_tab)
                return ToolResult(
                    success=True,
                    output=f"Successfully navigated to '{res.get('url', url)}'. Page title: '{res.get('title', '')}'",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"CDP navigation error: {e}")

        # 3. Explicit error if extension is offline
        return ToolResult(
            success=False,
            output="",
            error=EXTENSION_OFFLINE_ERROR,
            metadata={"status": "extension_offline", "url": url}
        )


class BrowserInspectTool(NexusTool):
    """Inspects the live DOM and returns structured interactive elements or clean HTML."""
    name = "browser_inspect"
    description = "Inspect the active webpage to extract structured interactive elements (buttons, inputs, links, forms) or clean HTML."
    risk_level = RiskLevel.READ_ONLY

    async def execute(
        self,
        include_html: bool = False,
        max_elements: int = 60,
        **kwargs,
    ) -> ToolResult:
        # 1. Extension Bridge
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("inspect_dom", {"max_elements": max_elements})
                return ToolResult(
                    success=True,
                    output=json.dumps(res, indent=2),
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension inspection error: {e}")

        # 2. CDP Engine
        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                state = await engine.inspect_page()
                data = state.to_compact_dict(max_elements=max_elements)
                if include_html:
                    data["simplified_html"] = await engine.get_simplified_html(max_chars=20000)

                return ToolResult(
                    success=True,
                    output=json.dumps(data, indent=2),
                    metadata=data,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"CDP inspection error: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


def _clean_target_for_vlm(selector: str = "", text: str = "") -> str:
    if text and text.strip():
        return text.strip()
    if not selector:
        return ""
    # Extract aria-label, data-tooltip, title or placeholder if present
    m = re.search(r'\[(?:aria-label|data-tooltip|title|placeholder)[*^$]?=[\'"]([^\'"]+)[\'"]', selector, re.I)
    if m:
        return m.group(1).strip()
    # Extract ID
    m2 = re.search(r'#([a-zA-Z0-9_-]+)', selector)
    if m2:
        return m2.group(1).replace("_", " ").replace("-", " ")
    # Clean CSS selectors like button.submit-btn -> submit btn
    cleaned = re.sub(r'[\[\]#.>:+*~="]', ' ', selector)
    return " ".join(cleaned.split())


class BrowserClickTool(NexusTool):
    """Clicks a DOM element resolved via CSS selector, XPath, or text, with Secondary Hardware Cursor fallback."""
    name = "browser_click"
    description = "Click a button, link, or interactive element in the active browser tab using a CSS selector, XPath, or visible text. If DOM clicking fails, seamlessly falls back to the secondary hardware cursor with visual VLM hovering and clicking."
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        selector: str = "",
        text: str = "",
        xpath: str = "",
        **kwargs,
    ) -> ToolResult:
        extension_err = None
        # 1. Extension Bridge (With In-Page Secondary Virtual Cursor)
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("click_element", {"selector": selector, "text": text, "xpath": xpath}, timeout=5.0)
                out_msg = f"Clicked '{res.get('text', text or selector)}' via NEXUS Extension (Secondary Virtual Cursor)."
                if res.get("sent_confirmed"):
                    out_msg += f" Email send confirmed: {res.get('confirmation_message', 'Message sent')}."
                elif res.get("already_open"):
                    out_msg += " Compose dialog is already open."
                return ToolResult(
                    success=True,
                    output=out_msg,
                    metadata=res,
                )
            except Exception as e:
                extension_err = e
                logger.warning(f"Extension DOM click failed for '{text or selector}': {e}. Trying CDP or Secondary Hardware Cursor fallback...")

        # 2. CDP Engine
        cdp_err = None
        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.click(selector=selector, text=text, xpath=xpath)
                elem_info = res.get("clicked_element", {})
                output_msg = (
                    f"Clicked <{elem_info.get('tag', 'element')}> "
                    f"'{elem_info.get('text', '')}' (id: '{elem_info.get('id', '')}'). "
                    f"Page URL is now '{res.get('current_url')}' and title is '{res.get('current_title')}'."
                )
                return ToolResult(
                    success=True,
                    output=output_msg,
                    metadata=res,
                )
            except BrowserAutomationError as e:
                return ToolResult(success=False, output="", error=e.message, metadata=e.details)
            except Exception as e:
                cdp_err = e
                logger.warning(f"Failed to click element via CDP: {e}")

        # 3. SECONDARY HARDWARE CURSOR FALLBACK
        # If DOM clicking is not happening (extension offline/failed and CDP offline/failed),
        # use physical mouse with visual VLM perception to locate and click like a normal user
        target_query = _clean_target_for_vlm(selector, text)
        if target_query:
            try:
                from backend.agent.tools.gui.hardware import ClickMouseTool
                logger.info(f"DOM click not happening for '{target_query}'. Engaging Secondary Hardware Cursor (visual VLM mouse hover & click)...")
                mouse_tool = ClickMouseTool()
                mouse_res = await mouse_tool.execute(target=target_query)
                if mouse_res.success:
                    return ToolResult(
                        success=True,
                        output=f"DOM click fallback: Used Secondary Hardware Cursor (VLM visual hover & click) on '{target_query}'. {mouse_res.output}",
                        metadata={"fallback_to_hardware_cursor": True, **(mouse_res.metadata or {})},
                    )
            except Exception as hw_e:
                logger.error(f"Secondary Hardware Cursor error: {hw_e}")

        if extension_err or cdp_err:
            return ToolResult(success=False, output="", error=f"Click failed: {extension_err or cdp_err}")
        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserTypeTool(NexusTool):
    """Types text into an input field or textarea."""
    name = "browser_type"
    description = "Type text into a form input or textarea in the active browser tab with proper framework event dispatching."
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        selector: str = "",
        text: str = "",
        clear_first: bool = True,
        press_enter: bool = False,
        **kwargs,
    ) -> ToolResult:
        if not text:
            return ToolResult(success=True, output="No text provided to type.")

        # Auto-detect search boxes and query inputs to ensure search is submitted
        if not press_enter and any(w in selector.lower() for w in ("search", "query", "input[name='q']", "#search", "searchbox", "search_query", "find")):
            press_enter = True

        # 1. Extension Bridge
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command(
                    "type_text",
                    {"selector": selector, "text": text, "clear_first": clear_first, "press_enter": press_enter},
                    timeout=5.0,
                )
                return ToolResult(
                    success=True,
                    output=f"Typed '{text}' into '{selector}' via NEXUS Companion Extension.",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension typing error: {e}")

        # 2. CDP Engine
        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.type_text(
                    selector=selector,
                    text=text,
                    clear_first=clear_first,
                    press_enter=press_enter,
                )
                return ToolResult(
                    success=True,
                    output=f"Successfully entered text into '{selector}'. Current value: '{res.get('value')}'.",
                    metadata=res,
                )
            except BrowserAutomationError as e:
                return ToolResult(success=False, output="", error=e.message, metadata=e.details)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Failed to type: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserSelectTool(NexusTool):
    """Selects an option in a <select> element."""
    name = "browser_select"
    description = "Select an option in a dropdown <select> element by value, visible text label, or numerical index."
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        selector: str = "",
        value: str = "",
        label: str = "",
        index: int = -1,
        **kwargs,
    ) -> ToolResult:
        if not selector:
            return ToolResult(success=False, output="", error="Missing required argument: 'selector'.")
        if not value and not label and index < 0:
            return ToolResult(success=False, output="", error="Specify at least one of 'value', 'label', or 'index'.")

        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("select_option", {"selector": selector, "value": value, "label": label, "index": index}, timeout=5.0)
                return ToolResult(
                    success=True,
                    output=f"Selected option '{res.get('selected')}' in '{selector}' via Extension.",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension select error: {e}")

        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.select_option(selector=selector, value=value, label=label, index=index)
                return ToolResult(
                    success=True,
                    output=f"Selected option '{res.get('selectedText')}' (value: '{res.get('selectedValue')}') in '{selector}'.",
                    metadata=res,
                )
            except BrowserAutomationError as e:
                return ToolResult(success=False, output="", error=e.message, metadata=e.details)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Failed to select option: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserPressTool(NexusTool):
    """Sends a keyboard action (Enter, Escape, Tab, etc.)."""
    name = "browser_press"
    description = "Send a keyboard key press (Enter, Escape, Tab, Backspace, ArrowDown, etc.) to the browser or focused element."
    risk_level = RiskLevel.SAFE

    async def execute(self, key: str = "Enter", selector: str = "", **kwargs) -> ToolResult:
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("press_key", {"key": key}, timeout=5.0)
                return ToolResult(
                    success=True,
                    output=f"Pressed key '{key}' via Extension.",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension press error: {e}")

        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.press_key(key=key, selector=selector)
                return ToolResult(
                    success=True,
                    output=f"Pressed keyboard key '{key}'.",
                    metadata=res,
                )
            except BrowserAutomationError as e:
                return ToolResult(success=False, output="", error=e.message, metadata=e.details)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Failed to press key: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserWaitTool(NexusTool):
    """Waits for dynamic page condition or specified seconds."""
    name = "browser_wait"
    description = "Wait for a DOM element, text substring, URL change, or seconds before proceeding."
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        seconds: float = 0.0,
        timeout_seconds: float = 0.0,
        selector: str = "",
        text: str = "",
        url_contains: str = "",
        **kwargs,
    ) -> ToolResult:
        wait_time = seconds or timeout_seconds or 2.0
        engine = BrowserAutomationEngine.get_instance()
        if (selector or text or url_contains) and await _check_browser_running(engine):
            try:
                res = await engine.wait_for(
                    selector=selector,
                    text=text,
                    url_contains=url_contains,
                    timeout_seconds=wait_time,
                )
                return ToolResult(
                    success=True,
                    output=f"Condition satisfied ({res.get('condition')}).",
                    metadata=res,
                )
            except Exception:
                pass

        await asyncio.sleep(min(wait_time, 4.0))
        return ToolResult(
            success=True,
            output=f"Waited {wait_time}s for page to settle.",
            metadata={"waited": wait_time},
        )


class BrowserDismissPopupTool(NexusTool):
    """Scans and dismisses blocking modal dialogs, cookie banners, and popups."""
    name = "browser_dismiss_popup"
    description = "Scan the active browser page for blocking modal dialogs, cookie consent banners, or popups, and click their dismiss/close/accept button."
    risk_level = RiskLevel.SAFE

    async def execute(self, **kwargs) -> ToolResult:
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("dismiss_popups", {})
                return ToolResult(
                    success=True,
                    output="Dismissed dialogs via NEXUS Extension." if res.get("dismissed") else "No blocking dialog detected.",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension dismiss error: {e}")

        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                res = await engine.dismiss_popups()
                if res.get("dismissed"):
                    return ToolResult(
                        success=True,
                        output=f"Dismissed popup/modal (matched: '{res.get('target')}').",
                        metadata=res,
                    )
                return ToolResult(
                    success=True,
                    output="No blocking popup or modal dialog was detected.",
                    metadata=res,
                )
            except Exception:
                pass

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserExecuteJsTool(NexusTool):
    """Executes arbitrary JavaScript in the page execution context."""
    name = "browser_execute_js"
    description = "Execute arbitrary JavaScript inside the active page context and return the evaluation result plus any console output."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, script: str = "", **kwargs) -> ToolResult:
        if not script:
            return ToolResult(success=False, output="", error="Missing required argument: 'script'.")

        # 1. Extension Bridge (preferred — runs inside live page context, captures console output)
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("execute_script", {"script": script})
                if res.get("error"):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Script error: {res['error']}",
                        metadata=res,
                    )
                output_parts = []
                if res.get("result") is not None:
                    result_str = json.dumps(res["result"], indent=2) if isinstance(res["result"], (dict, list)) else str(res["result"])
                    output_parts.append(f"Result: {result_str}")
                if res.get("logs"):
                    log_lines = [f"  [{l['level'].upper()}] {l['msg']}" for l in res["logs"]]
                    output_parts.append("Console output:\n" + "\n".join(log_lines))
                return ToolResult(
                    success=True,
                    output="\n".join(output_parts) if output_parts else "Script executed successfully (no return value).",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension script error: {e}")

        # 2. CDP Engine fallback
        engine = BrowserAutomationEngine.get_instance()
        try:
            fn = getattr(engine, "execute_js", None) or getattr(engine, "execute_javascript", None)
            res = await fn(script=script)
            return ToolResult(
                success=True,
                output=json.dumps({"result": res}, indent=2) if isinstance(res, (dict, list)) else str(res),
                metadata={"result": res},
            )
        except BrowserAutomationError as e:
            return ToolResult(success=False, output="", error=e.message, metadata=e.details)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"JavaScript execution failed: {e}")


class BrowserGetSourceTool(NexusTool):
    """Returns the full HTML source of the active page or a scoped element."""
    name = "browser_get_source"
    description = (
        "Fetch the full HTML source of the active browser page (or a specific element via CSS selector). "
        "Use this when you need to understand page structure, read dynamic content, or analyse the DOM deeply."
    )
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, selector: str = "", max_chars: int = 60000, **kwargs) -> ToolResult:
        # 1. Extension Bridge
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                payload = {"max_chars": max_chars}
                if selector:
                    payload["selector"] = selector
                res = await extension_bridge.send_command("get_page_source", payload)
                source = res.get("source", "")
                meta_lines = [
                    f"URL: {res.get('url', '')}",
                    f"Title: {res.get('title', '')}",
                    f"Characters: {res.get('char_count', len(source))}{'  [truncated]' if res.get('truncated') else ''}",
                ]
                return ToolResult(
                    success=True,
                    output="\n".join(meta_lines) + "\n\n" + source,
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Extension source error: {e}")

        # 2. CDP Engine fallback
        engine = BrowserAutomationEngine.get_instance()
        if await _check_browser_running(engine):
            try:
                fn = getattr(engine, "get_simplified_html", None)
                if fn:
                    source = await fn(max_chars=max_chars)
                    return ToolResult(success=True, output=source, metadata={"source": source})
            except Exception as e:
                return ToolResult(success=False, output="", error=f"CDP source error: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)


class BrowserScrollTool(NexusTool):
    """Scrolls the active page to a specific element or position."""
    name = "browser_scroll"
    description = "Scroll the active browser page to a CSS selector element or an (x, y) pixel position."
    risk_level = RiskLevel.SAFE

    async def execute(self, selector: str = "", x: int = 0, y: int = 0, **kwargs) -> ToolResult:
        if await extension_bridge.wait_for_connection(timeout_seconds=2.0):
            try:
                res = await extension_bridge.send_command("scroll_to", {"selector": selector, "x": x, "y": y})
                return ToolResult(
                    success=True,
                    output=f"Scrolled to {'selector ' + selector if selector else f'position ({x},{y})'}.",
                    metadata=res,
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Scroll error: {e}")

        return ToolResult(success=False, output="", error=EXTENSION_OFFLINE_ERROR)
