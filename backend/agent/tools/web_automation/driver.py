"""Asynchronous Chrome DevTools Protocol (CDP) browser driver for NEXUS."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any, Optional
from pathlib import Path
import httpx
import websockets

from backend.agent.tools.web_automation.exceptions import (
    BrowserUnavailable,
    TargetNotFound,
    TabNotFound,
    ElementNotFound,
    ElementAmbiguous,
    ElementNotInteractable,
    NavigationError,
    JavaScriptExecutionError,
    BrowserTimeoutError,
)
from backend.agent.tools.web_automation.models import (
    BrowserState,
    TabInfo,
    FrameInfo,
)
from backend.agent.tools.web_automation.dom import (
    DOM_EXTRACTION_SCRIPT,
    simplify_html,
    parse_interactive_elements_from_dict,
)

logger = logging.getLogger("nexus.browser_automation")


class CDPBackend:
    """Manages low-level WebSocket connection to a CDP target."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._msg_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._console_logs: list[str] = []
        self._page_events: list[str] = []

    async def connect(self, timeout: float = 8.0) -> None:
        """Establish WebSocket connection and start background message pump."""
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.ws_url, max_size=20 * 1024 * 1024),
                timeout=timeout,
            )
            self._reader_task = asyncio.create_task(self._read_loop())
            # Enable standard domains
            await self.send("Page.enable")
            await self.send("Runtime.enable")
            await self.send("DOM.enable")
        except Exception as exc:
            raise BrowserUnavailable(
                f"Failed to connect to browser CDP WebSocket at {self.ws_url}: {exc}",
                {"ws_url": self.ws_url},
            ) from exc

    async def _read_loop(self) -> None:
        """Background loop reading CDP events and responses."""
        try:
            assert self._ws is not None
            async for raw_msg in self._ws:
                try:
                    data = json.loads(raw_msg)
                except Exception:
                    continue

                # Handle response to request
                if "id" in data:
                    req_id = data["id"]
                    if req_id in self._pending_requests:
                        fut = self._pending_requests.pop(req_id)
                        if not fut.done():
                            if "error" in data:
                                fut.set_exception(
                                    JavaScriptExecutionError(
                                        data["error"].get("message", "CDP Error"),
                                        data["error"],
                                    )
                                )
                            else:
                                fut.set_result(data.get("result", {}))

                # Handle events
                method = data.get("method", "")
                if method == "Page.javascriptDialogOpening":
                    # Automatically accept native browser alert/confirm dialogs
                    dialog_type = data.get("params", {}).get("type", "alert")
                    msg = data.get("params", {}).get("message", "")
                    self._console_logs.append(f"Auto-handled native JS {dialog_type}: '{msg}'")
                    asyncio.create_task(self.send("Page.handleJavaScriptDialog", {"accept": True}))
                elif method == "Runtime.consoleAPICalled":
                    args = data.get("params", {}).get("args", [])
                    log_text = " ".join(str(a.get("value", "")) for a in args)
                    self._console_logs.append(log_text)
                elif method == "Runtime.exceptionThrown":
                    details = data.get("params", {}).get("exceptionDetails", {})
                    self._console_logs.append(f"ERROR: {details.get('text', '')}")
                elif method.startswith("Page."):
                    self._page_events.append(method)

        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass
        except Exception as e:
            logger.debug(f"CDP read loop terminated: {e}")

    async def send(self, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        """Send a CDP command and await its response."""
        if not self._ws:
            raise BrowserUnavailable("WebSocket is not connected.")

        self._msg_id += 1
        req_id = self._msg_id
        payload = {"id": req_id, "method": method, "params": params or {}}

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_requests[req_id] = fut

        try:
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise BrowserTimeoutError(f"CDP command '{method}' timed out after {timeout}s.")
        except Exception:
            self._pending_requests.pop(req_id, None)
            raise

    async def evaluate_js(self, expression: str, await_promise: bool = True) -> Any:
        """Evaluate JavaScript inside the current execution context."""
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
            },
        )
        if "exceptionDetails" in res:
            err = res["exceptionDetails"]
            desc = err.get("exception", {}).get("description") or err.get("text", "JS Error")
            raise JavaScriptExecutionError(f"JavaScript evaluation failed: {desc}", err)

        return res.get("result", {}).get("value")

    def get_console_errors(self) -> list[str]:
        return [log for log in self._console_logs if "error" in log.lower() or log.startswith("ERROR:")]

    async def close(self) -> None:
        """Gracefully close WebSocket connection."""
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None


class BrowserAutomationEngine:
    """High-level browser automation engine connected via Chrome DevTools Protocol."""

    _instance: Optional[BrowserAutomationEngine] = None

    def __init__(self, cdp_host: str = "127.0.0.1", cdp_port: int = 9222):
        self.cdp_host = cdp_host
        self.cdp_port = cdp_port
        self.base_url = f"http://{cdp_host}:{cdp_port}"
        self.active_target_id: Optional[str] = None
        self._active_backend: Optional[CDPBackend] = None

    @classmethod
    def get_instance(cls) -> BrowserAutomationEngine:
        """Singleton instance provider."""
        if cls._instance is None:
            cls._instance = BrowserAutomationEngine()
        return cls._instance

    async def is_browser_running(self) -> bool:
        """Check if Chrome/Edge is listening on the remote debugging port."""
        try:
            async with httpx.AsyncClient(timeout=0.3) as client:
                res = await client.get(f"{self.base_url}/json/version")
                return res.status_code == 200
        except Exception:
            return False

    async def launch_or_connect(self) -> None:
        """Ensure browser is running with remote debugging enabled."""
        if not await self.is_browser_running():
            try:
                # Find Chrome or Edge executable if standard command fails
                candidates = [
                    "chrome",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    "msedge",
                ]
                
                launched = False
                for exe in candidates:
                    if os.path.isabs(exe) and not os.path.exists(exe):
                        continue
                    try:
                        args = [
                            exe,
                            f"--remote-debugging-port={self.cdp_port}",
                            '--profile-directory="Default"',
                            "--no-first-run",
                            "--no-default-browser-check",
                        ]
                        subprocess.Popen(args)
                        launched = True
                        break
                    except Exception:
                        continue

                if not launched:
                    cmd = f'start chrome --remote-debugging-port={self.cdp_port} --profile-directory="Default" --no-first-run --no-default-browser-check'
                    subprocess.Popen(["cmd.exe", "/c", cmd], shell=True)

                # Wait up to 5 seconds for browser startup
                for _ in range(20):
                    await asyncio.sleep(0.25)
                    if await self.is_browser_running():
                        break
            except Exception as e:
                logger.debug(f"Could not auto-launch Chrome: {e}")

        if not await self.is_browser_running():
            raise BrowserUnavailable(
                f"NEXUS requires Chrome to be started with remote debugging enabled so it can interact with your opened tabs and logged-in accounts.\n"
                f"To connect to your existing Chrome profile, launch Chrome with:\n"
                f"  chrome.exe --remote-debugging-port={self.cdp_port}",
                {"port": self.cdp_port},
            )

    async def get_tabs(self) -> list[TabInfo]:
        """Discover all open pages/tabs in the browser."""
        await self.launch_or_connect()
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(f"{self.base_url}/json/list")
                targets = res.json()
        except Exception as exc:
            raise BrowserUnavailable(f"Failed to query browser tabs: {exc}") from exc

        tabs: list[TabInfo] = []
        for t in targets:
            if t.get("type") == "page":
                tabs.append(
                    TabInfo(
                        id=t.get("id", ""),
                        title=t.get("title", "Untitled"),
                        url=t.get("url", ""),
                        type=t.get("type", "page"),
                        webSocketDebuggerUrl=t.get("webSocketDebuggerUrl"),
                    )
                )
        return tabs

    async def get_or_attach_backend(self, target_id: Optional[str] = None) -> CDPBackend:
        """Get or establish WebSocket connection to the active tab."""
        tabs = await self.get_tabs()
        if not tabs:
            # Create a new tab if none exist
            async with httpx.AsyncClient(timeout=4.0) as client:
                new_tab = (await client.put(f"{self.base_url}/json/new?about:blank")).json()
                tabs = [
                    TabInfo(
                        id=new_tab.get("id", ""),
                        title=new_tab.get("title", ""),
                        url=new_tab.get("url", ""),
                        webSocketDebuggerUrl=new_tab.get("webSocketDebuggerUrl"),
                    )
                ]

        target_tab: Optional[TabInfo] = None
        if target_id:
            target_tab = next((t for t in tabs if t.id == target_id), None)
            if not target_tab:
                raise TabNotFound(f"Tab with ID '{target_id}' not found.", {"available_tabs": [t.id for t in tabs]})
        elif self.active_target_id:
            target_tab = next((t for t in tabs if t.id == self.active_target_id), None)

        if not target_tab:
            # Pick first active page tab
            target_tab = tabs[0]

        # If switching tabs or connecting for the first time
        if self._active_backend is None or self.active_target_id != target_tab.id:
            if self._active_backend:
                await self._active_backend.close()

            if not target_tab.webSocketDebuggerUrl:
                raise BrowserUnavailable(f"Tab '{target_tab.id}' has no WebSocket debugger URL.")

            backend = CDPBackend(target_tab.webSocketDebuggerUrl)
            await backend.connect()
            self._active_backend = backend
            self.active_target_id = target_tab.id

        return self._active_backend

    async def switch_tab(self, target_id: str) -> TabInfo:
        """Switch active target tab by ID, URL, or page title."""
        tabs = await self.get_tabs()
        target = next((t for t in tabs if str(t.id) == str(target_id)), None)
        if not target and target_id:
            tid_lower = str(target_id).lower()
            target = next((t for t in tabs if (t.url and tid_lower in t.url.lower()) or (t.title and tid_lower in t.title.lower())), None)
        if not target:
            raise TabNotFound(
                f"Cannot switch to tab '{target_id}'. Tab does not exist.",
                {"tabs": [t.to_dict() for t in tabs]},
            )

        # Activate via HTTP
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.get(f"{self.base_url}/json/activate/{target.id}")
        except Exception:
            pass

        await self.get_or_attach_backend(target.id)
        return target

    async def navigate(self, url: str, new_tab: bool = False, wait_until: str = "load") -> dict:
        """Navigate active tab or open new tab without overwriting existing user tab URLs."""
        if not url.startswith(("http://", "https://", "about:", "file://")):
            url = f"https://{url}"

        # 1. User explicitly requested a new tab
        if new_tab:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = (await client.put(f"{self.base_url}/json/new?{url}")).json()
                new_id = res.get("id")
                await self.switch_tab(new_id)
                await asyncio.sleep(1.0)
                return {
                    "success": True,
                    "action": "open_new_tab",
                    "tab_id": new_id,
                    "url": url,
                }

        # 2. Check if an existing open tab already matches the target URL or web service
        try:
            tabs = await self.get_tabs()
            clean_target = url.split("#")[0].rstrip("/").lower()
            matching_tab = next((t for t in tabs if t.url and t.url.split("#")[0].rstrip("/").lower() == clean_target), None)
            if not matching_tab:
                from urllib.parse import urlparse
                target_parsed = urlparse(url)
                if target_parsed.path in ("", "/"):
                    target_host = (target_parsed.hostname or "").replace("www.", "").lower()
                    if target_host:
                        matching_tab = next(
                            (t for t in tabs if t.url and target_host in (urlparse(t.url).hostname or "").lower()),
                            None
                        )
            if matching_tab:
                await self.switch_tab(matching_tab.id)
                await asyncio.sleep(0.5)
                return {
                    "success": True,
                    "action": "switched_to_tab",
                    "tab_id": matching_tab.id,
                    "url": matching_tab.url,
                    "title": matching_tab.title,
                }
        except Exception:
            pass

        # 3. Check current active tab: if it has user content, preserve it and open a new tab
        backend = await self.get_or_attach_backend()
        try:
            state = await self.inspect_page()
            cur_url = (state.url or "").lower()
            is_blank = not cur_url or cur_url in ("about:blank", "chrome://newtab/", "chrome://welcome/")

            if not is_blank:
                # Active tab has existing user content — open a fresh tab so user's work is never lost!
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = (await client.put(f"{self.base_url}/json/new?{url}")).json()
                    new_id = res.get("id")
                    await self.switch_tab(new_id)
                    await asyncio.sleep(1.0)
                    return {
                        "success": True,
                        "action": "open_new_tab",
                        "tab_id": new_id,
                        "url": url,
                        "reason": "preserved_existing_tab",
                    }

            # If current tab is genuinely blank, navigate it directly
            await backend.send("Page.navigate", {"url": url})
            await asyncio.sleep(1.2)
            new_state = await self.inspect_page()
            return {
                "success": True,
                "action": "navigate",
                "url": new_state.url,
                "title": new_state.title,
            }
        except Exception as exc:
            raise NavigationError(f"Failed to navigate to '{url}': {exc}", {"url": url}) from exc

    async def inspect_page(self, simplified_html: bool = False) -> BrowserState:
        """Inspect the live DOM and return a structured representation."""
        backend = await self.get_or_attach_backend()
        tabs = await self.get_tabs()

        try:
            raw_data = await backend.evaluate_js(DOM_EXTRACTION_SCRIPT)
        except Exception as exc:
            raise BrowserUnavailable(f"Failed to inspect DOM: {exc}") from exc

        if not isinstance(raw_data, dict):
            raw_data = {}

        url = raw_data.get("url", "")
        title = raw_data.get("title", "")
        focused = raw_data.get("focused_element")
        interactive = parse_interactive_elements_from_dict(raw_data.get("interactive_elements", []))

        frames: list[FrameInfo] = [
            FrameInfo(id=f.get("id", ""), url=f.get("src", ""), name=f.get("name"))
            for f in raw_data.get("iframes", [])
        ]

        console_errors = backend.get_console_errors()

        return BrowserState(
            url=url,
            title=title,
            active_target=self.active_target_id or "",
            tabs=tabs,
            frames=frames,
            interactive_elements=interactive,
            focused_element=focused,
            console_errors=console_errors,
            navigation_state="complete",
        )

    async def get_simplified_html(self, max_chars: int = 25000) -> str:
        """Fetch page outerHTML and return a cleaned, simplified version."""
        backend = await self.get_or_attach_backend()
        raw_html = await backend.evaluate_js("document.documentElement.outerHTML")
        return simplify_html(str(raw_html or ""), max_chars=max_chars)

    async def dismiss_popups(self) -> dict:
        """
        Scan page for blocking modal dialogs, cookie consent banners, tour prompts, or popups,
        and click their dismiss/close/accept buttons.
        """
        backend = await self.get_or_attach_backend()
        dismiss_js = """(() => {
            let selectors = [
                '[role="dialog"] button[aria-label*="close" i]',
                '[role="dialog"] button[aria-label*="dismiss" i]',
                '[role="alertdialog"] button[aria-label*="close" i]',
                '[role="alertdialog"] button[aria-label*="dismiss" i]',
                '[aria-modal="true"] button[aria-label*="close" i]',
                '[aria-modal="true"] button[aria-label*="dismiss" i]',
                '.quantumWizDialogPaperdialogClose',
                '.modal [data-dismiss="modal"]',
                '.modal button.close',
                '.modal .modal-close',
                '.popup [data-dismiss="modal"]',
                '.popup-close',
                '#cookie-accept',
                '.cookie-banner button',
                '#onetrust-accept-btn-handler',
                'button[id*="cookie" i]',
                'button[class*="cookie" i]',
                'button[id*="consent" i]',
                'button[class*="consent" i]'
            ];
            
            for (let s of selectors) {
                let btn = document.querySelector(s);
                if (btn && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                    btn.click();
                    return { dismissed: true, target: s, text: (btn.innerText || btn.textContent || '').trim() };
                }
            }

            let buttons = Array.from(document.querySelectorAll('button, [role="button"], a.btn'));
            let generalWords = ['accept all', 'allow all', 'i agree', 'got it', 'maybe later', "let's start creating"];
            for (let btn of buttons) {
                let t = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                if (generalWords.includes(t) && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                    btn.click();
                    return { dismissed: true, target: t, text: (btn.innerText || btn.textContent || '').trim() };
                }
                if (['close', 'dismiss', 'no thanks'].includes(t) && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                    let inModal = btn.closest('[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog, .modal, .popup, [class*="banner" i], [class*="cookie" i], [id*="cookie" i]');
                    if (inModal) {
                        btn.click();
                        return { dismissed: true, target: t, text: (btn.innerText || btn.textContent || '').trim() };
                    }
                }
            }

            return { dismissed: false };
        })()"""
        res = await backend.evaluate_js(dismiss_js)
        await asyncio.sleep(0.3)
        return res if isinstance(res, dict) else {"dismissed": False}

    async def click(
        self,
        selector: str = "",
        text: str = "",
        xpath: str = "",
        timeout_ms: int = 5000,
        auto_dismiss_overlay: bool = True,
    ) -> dict:
        """
        Deterministic element click:
        1. Resolves element by CSS selector, XPath, or exact/fuzzy text matching.
        2. Validates visibility and interactability.
        3. If blocked or not found, automatically attempts to dismiss any popups and retries.
        4. Dispatches focus, mousedown, mouseup, and click events.
        """
        backend = await self.get_or_attach_backend()

        click_js = f"""(() => {{
            let selector = {json.dumps(selector)};
            let text = {json.dumps(text)};
            let xpath = {json.dumps(xpath)};

            let target = null;
            let candidates = [];

            if (selector) {{
                let matched = Array.from(document.querySelectorAll(selector));
                if (matched.length === 1) {{
                    target = matched[0];
                }} else if (matched.length > 1) {{
                    candidates = matched.map(el => (el.innerText || el.textContent || el.tagName).trim());
                    return {{ success: false, error: "AMBIGUOUS_SELECTOR", count: matched.length, candidates: candidates.slice(0, 5) }};
                }}
            }}

            if (!target && xpath) {{
                let result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                target = result.singleNodeValue;
            }}

            if (!target && text) {{
                let search = text.toLowerCase().trim();
                let all = Array.from(document.querySelectorAll(
                    'button, a, input[type=submit], input[type=button], [role=button], [role=link], [role=listitem], [role=row], [role=gridcell], [role=option], [role=tab], summary, label, span[title], div[title], [data-testid*="cell" i], [data-testid*="chat" i], [data-testid*="list-item" i], [tabindex], p, span, div'
                ));

                // 1. Exact match on title or aria-label
                target = all.find(el => {{
                    let title = (el.getAttribute('title') || '').trim().toLowerCase();
                    let aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                    return title === search || aria === search;
                }});

                // 2. Exact match on text or value
                if (!target) {{
                    target = all.find(el => (el.innerText || el.textContent || el.value || '').trim().toLowerCase() === search);
                }}

                // 3. Partial match on title or aria-label
                if (!target) {{
                    target = all.find(el => {{
                        let title = (el.getAttribute('title') || '').trim().toLowerCase();
                        let aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        return title.includes(search) || aria.includes(search);
                    }});
                }}

                // 4. Partial match on innerText (prefer leaf/smaller element)
                if (!target) {{
                    let matching = all.filter(el => (el.innerText || el.textContent || el.value || '').toLowerCase().includes(search));
                    if (matching.length > 0) {{
                        matching.sort((a, b) => (a.innerText?.length || 9999) - (b.innerText?.length || 9999));
                        target = matching[0];
                    }}
                }}
            }}

            if (!target) {{
                return {{ success: false, error: "NOT_FOUND" }};
            }}

            // Resolve interactive ancestor if target is an inner span/icon/svg or list row
            let interactiveAncestor = target.closest(
                'button, [role="button"], a, [role="link"], [role="listitem"], [role="row"], [role="gridcell"], [role="option"], [role="tab"], [data-testid*="cell" i], [data-testid*="chat" i], [data-testid*="list-item" i], [tabindex]'
            );
            let primaryTarget = interactiveAncestor || target;

            // Check interactability
            let rect = primaryTarget.getBoundingClientRect();
            let style = window.getComputedStyle(primaryTarget);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {{
                return {{ success: false, error: "NOT_VISIBLE" }};
            }}
            if (primaryTarget.hasAttribute('disabled') || primaryTarget.getAttribute('aria-disabled') === 'true') {{
                return {{ success: false, error: "DISABLED" }};
            }}

            // Scroll into view & click
            primaryTarget.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
            if (typeof primaryTarget.focus === 'function') primaryTarget.focus();
            if (target !== primaryTarget && typeof target.focus === 'function') target.focus();

            // Dispatch mouse sequence with buttons for rich JS frameworks (React/Angular/Vue/Meta Lexical)
            let x = rect.left + rect.width / 2;
            let y = rect.top + rect.height / 2;
            const opts = {{ bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0, buttons: 1, which: 1 }};
            primaryTarget.dispatchEvent(new MouseEvent('mouseover', opts));
            primaryTarget.dispatchEvent(new MouseEvent('mousedown', opts));
            primaryTarget.dispatchEvent(new MouseEvent('mouseup', opts));
            primaryTarget.dispatchEvent(new MouseEvent('click', opts));
            if (typeof primaryTarget.click === 'function') primaryTarget.click();

            if (target !== primaryTarget) {{
                try {{
                    target.dispatchEvent(new MouseEvent('click', opts));
                    if (typeof target.click === 'function') target.click();
                }} catch (_) {{}}
            }}

            return {{
                success: true,
                tag: primaryTarget.tagName.toLowerCase(),
                id: primaryTarget.id || null,
                text: (primaryTarget.innerText || primaryTarget.textContent || target.innerText || target.textContent || '').trim().substring(0, 60),
                x: Math.round(x),
                y: Math.round(y)
            }};
        }})()"""

        res = await backend.evaluate_js(click_js)
        if not isinstance(res, dict):
            raise JavaScriptExecutionError("Invalid click execution response.")

        if not res.get("success") and auto_dismiss_overlay:
            err_code = res.get("error")
            if err_code in ("NOT_FOUND", "NOT_VISIBLE"):
                # Attempt to dismiss blocking modal/dialog and retry click once
                pop_res = await self.dismiss_popups()
                if pop_res.get("dismissed"):
                    await asyncio.sleep(0.4)
                    res = await backend.evaluate_js(click_js)
        if not isinstance(res, dict):
            raise JavaScriptExecutionError("Invalid click execution response.")

        # Dispatch native CDP mouse events for authentic isTrusted browser input
        if res.get("success") and res.get("x") is not None and res.get("y") is not None:
            try:
                cx = float(res["x"])
                cy = float(res["y"])
                await backend.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy})
                await backend.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1})
                await asyncio.sleep(0.04)
                await backend.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1})
            except Exception:
                pass

        if not res.get("success"):
            err_code = res.get("error")
            if err_code == "NOT_FOUND":
                raise ElementNotFound(
                    f"Could not find element to click with selector='{selector}', text='{text}', xpath='{xpath}'.",
                    {"selector": selector, "text": text, "xpath": xpath},
                )
            elif err_code in ("AMBIGUOUS_SELECTOR", "AMBIGUOUS_TEXT"):
                raise ElementAmbiguous(
                    f"Found {res.get('count')} matching elements. Please specify a more specific selector.",
                    {"candidates": res.get("candidates")},
                )
            elif err_code in ("NOT_VISIBLE", "DISABLED"):
                raise ElementNotInteractable(
                    f"Element is {err_code.lower()} and cannot receive clicks.",
                    {"error_code": err_code},
                )

        # Allow DOM events / potential navigation to settle
        await asyncio.sleep(0.5)

        # Collect post-action observation
        after_state = await self.inspect_page()
        return {
            "success": True,
            "clicked_element": res,
            "current_url": after_state.url,
            "current_title": after_state.title,
        }

    async def type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        press_enter: bool = False,
    ) -> dict:
        """
        Type text into an input or textarea with full React/Vue change event dispatch.
        """
        backend = await self.get_or_attach_backend()

        type_js = f"""(() => {{
            let selector = {json.dumps(selector)};
            let text = {json.dumps(text)};
            let clearFirst = {json.dumps(clear_first)};
            let pressEnter = {json.dumps(press_enter)};

            let el = document.querySelector(selector);
            if (!el) {{
                if (/to/i.test(selector)) {{
                    el = document.querySelector('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[aria-label*="To" i] input, input[name="to"]');
                }} else if (/cc/i.test(selector)) {{
                    el = document.querySelector('input[aria-label*="Cc recipients" i], input[aria-label*="Cc" i], div[aria-label*="Cc" i] input, input[name="cc"]');
                }} else if (/bcc/i.test(selector)) {{
                    el = document.querySelector('input[aria-label*="Bcc recipients" i], input[aria-label*="Bcc" i], div[aria-label*="Bcc" i] input, input[name="bcc"]');
                }} else if (/subject/i.test(selector)) {{
                    el = document.querySelector('input[name="subjectbox"], input[aria-label*="Subject" i], input[placeholder*="Subject" i]');
                }} else if (/body|message/i.test(selector)) {{
                    el = document.querySelector('div[role="textbox"][aria-label*="Message Body" i], div[contenteditable="true"][aria-label*="Body" i], div[g_editable="true"]');
                }}
            }}

            if (!el) {{
                el = document.activeElement;
            }}

            if (!el || el === document.body) {{
                return {{ success: false, error: "NOT_FOUND" }};
            }}

            // Resolve inner editable if container was targeted
            if (!["input", "textarea"].includes(el.tagName.toLowerCase()) && !el.isContentEditable && el.getAttribute("role") !== "textbox") {{
                let editable = el.querySelector('input, textarea, [contenteditable="true"], [role="textbox"]');
                if (editable) el = editable;
            }}

            el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            el.focus();

            // Handle rich contenteditable elements (Gmail Body, Google Forms, Notion, Docs, Slack)
            if (el.isContentEditable || el.getAttribute('contenteditable') === 'true' || (el.getAttribute('role') === 'textbox' && el.tagName.toLowerCase() !== 'input' && el.tagName.toLowerCase() !== 'textarea')) {{
                if (clearFirst) {{
                    el.innerText = '';
                    el.innerHTML = '';
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                }}
                el.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, cancelable: true, inputType: 'insertText', data: text }}));
                document.execCommand('insertText', false, text);
                if (el.innerText.trim() !== text.trim() && !el.innerText.includes(text.trim())) {{
                    el.innerText = text;
                }}
                el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: text }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));

                if (pressEnter) {{
                    document.execCommand('insertParagraph', false, null);
                    el.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                }}

                return {{
                    success: true,
                    selector: selector,
                    value: el.innerText || el.textContent
                }};
            }}

            // Set native value setter for React/Vue synthetic events
            let proto = el.tagName.toLowerCase() === 'textarea' 
                ? window.HTMLTextAreaElement.prototype 
                : window.HTMLInputElement.prototype;
            let nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;

            if (clearFirst) {{
                if (nativeSetter) {{
                    nativeSetter.call(el, '');
                }} else {{
                    el.value = '';
                }}
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}

            if (nativeSetter) {{
                nativeSetter.call(el, text);
            }} else {{
                el.value = text;
            }}

            // Dispatch full input & change lifecycle
            el.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, cancelable: true, inputType: 'insertText', data: text }}));
            el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: text }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));

            let isRecipientField = /to|cc|bcc|recipient/i.test(el.getAttribute('aria-label') || el.name || el.id || selector || '');
            if (pressEnter || (isRecipientField && text.includes('@'))) {{
                el.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                el.dispatchEvent(new KeyboardEvent('keypress', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                el.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                el.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Tab', code: 'Tab', keyCode: 9, which: 9, bubbles: true }}));
                el.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Tab', code: 'Tab', keyCode: 9, which: 9, bubbles: true }}));
                if (el.form && pressEnter) {{
                    el.form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
                }}
            }}

            return {{
                success: true,
                selector: selector,
                value: el.value
            }};
        }})()"""

        res = await backend.evaluate_js(type_js)
        if not isinstance(res, dict) or not res.get("success"):
            raise ElementNotFound(f"Element '{selector}' not found for typing.", {"selector": selector})

        await asyncio.sleep(0.3)
        return res

    async def select_option(
        self,
        selector: str,
        value: str = "",
        label: str = "",
        index: int = -1,
    ) -> dict:
        """Select an option in a <select> element by value, visible text, or index."""
        backend = await self.get_or_attach_backend()

        select_js = f"""(() => {{
            let selector = {json.dumps(selector)};
            let val = {json.dumps(value)};
            let lbl = {json.dumps(label)};
            let idx = {json.dumps(index)};

            let el = document.querySelector(selector);
            if (!el || el.tagName.toLowerCase() !== 'select') {{
                return {{ success: false, error: "NOT_A_SELECT" }};
            }}

            let matched = false;
            let options = Array.from(el.options);

            if (idx >= 0 && idx < options.length) {{
                el.selectedIndex = idx;
                matched = true;
            }} else if (val) {{
                for (let opt of options) {{
                    if (opt.value === val) {{
                        opt.selected = true;
                        matched = true;
                        break;
                    }}
                }}
            }} else if (lbl) {{
                for (let opt of options) {{
                    if (opt.text.trim().toLowerCase() === lbl.toLowerCase().trim()) {{
                        opt.selected = true;
                        matched = true;
                        break;
                    }}
                }}
            }}

            if (!matched) {{
                return {{ success: false, error: "OPTION_NOT_FOUND" }};
            }}

            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return {{
                success: true,
                selectedIndex: el.selectedIndex,
                selectedValue: el.value,
                selectedText: options[el.selectedIndex]?.text
            }};
        }})()"""

        res = await backend.evaluate_js(select_js)
        if not isinstance(res, dict) or not res.get("success"):
            raise ElementNotFound(
                f"Could not select option in '{selector}'. Error: {res.get('error') if isinstance(res, dict) else 'Unknown'}",
                {"selector": selector, "value": value, "label": label},
            )

        return res

    async def press_key(self, key: str, selector: str = "") -> dict:
        """Send a keyboard key action (Enter, Escape, Tab, ArrowDown, etc.)."""
        backend = await self.get_or_attach_backend()

        key_js = f"""(() => {{
            let key = {json.dumps(key)};
            let selector = {json.dumps(selector)};
            let target = selector ? document.querySelector(selector) : document.activeElement || document.body;

            let keyCodes = {{
                'Enter': 13,
                'Escape': 27,
                'Tab': 9,
                'Backspace': 8,
                'ArrowDown': 40,
                'ArrowUp': 38,
                'ArrowLeft': 37,
                'ArrowRight': 39,
                'Space': 32
            }};

            let code = keyCodes[key] || 0;
            const opts = {{ key: key, code: key, keyCode: code, which: code, bubbles: true, cancelable: true }};

            target.dispatchEvent(new KeyboardEvent('keydown', opts));
            target.dispatchEvent(new KeyboardEvent('keypress', opts));
            target.dispatchEvent(new KeyboardEvent('keyup', opts));

            return {{ success: true, key: key, target_tag: target.tagName.toLowerCase() }};
        }})()"""

        res = await backend.evaluate_js(key_js)
        await asyncio.sleep(0.3)
        return res

    async def wait_for(
        self,
        selector: str = "",
        text: str = "",
        url_contains: str = "",
        timeout_seconds: float = 10.0,
    ) -> dict:
        """Wait for an element, text, or URL change condition to be met."""
        backend = await self.get_or_attach_backend()
        start = time.time()

        while time.time() - start < timeout_seconds:
            state = await self.inspect_page()

            if url_contains and url_contains in state.url:
                return {"success": True, "condition": "url_contains", "url": state.url}

            if selector:
                exists = await backend.evaluate_js(f"Boolean(document.querySelector({json.dumps(selector)}))")
                if exists:
                    return {"success": True, "condition": "selector_exists", "selector": selector}

            if text:
                text_exists = await backend.evaluate_js(
                    f"document.body ? document.body.innerText.includes({json.dumps(text)}) : false"
                )
                if text_exists:
                    return {"success": True, "condition": "text_found", "text": text}

            await asyncio.sleep(0.4)

        raise BrowserTimeoutError(
            f"Timed out waiting for condition after {timeout_seconds}s.",
            {"selector": selector, "text": text, "url_contains": url_contains},
        )

    async def execute_js(self, script: str) -> Any:
        """Execute arbitrary JavaScript inside page console context."""
        backend = await self.get_or_attach_backend()
        return await backend.evaluate_js(script)

    async def take_screenshot(self) -> bytes | None:
        """
        Capture a JPEG screenshot of the current tab via CDP Page.captureScreenshot.
        Returns raw JPEG bytes, or None if CDP is unavailable (extension-only mode).
        JPEG quality 65 gives ~30-80KB — fast to encode, fast to send to VLM.
        """
        try:
            backend = self._active_backend
            if backend is None:
                return None
            result = await backend.send(
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": 65, "fromSurface": True},
                timeout=6.0,
            )
            data_b64 = result.get("data")
            if not data_b64:
                return None
            import base64
            return base64.b64decode(data_b64)
        except Exception as exc:
            logger.debug("CDP screenshot failed: %s", exc)
            return None

