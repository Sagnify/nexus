"""Unit and integration tests for NEXUS Structured Browser Automation Subsystem."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.tools.web_automation.models import (
    InteractiveElement,
    BrowserState,
    TabInfo,
    FrameInfo,
)
from backend.agent.tools.web_automation.exceptions import (
    BrowserUnavailable,
    ElementNotFound,
    ElementAmbiguous,
    ElementNotInteractable,
    NavigationError,
    JavaScriptExecutionError,
    BrowserTimeoutError,
)
from backend.agent.tools.web_automation.dom import (
    simplify_html,
    parse_interactive_elements_from_dict,
)
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
    BrowserExecuteJsTool,
)
from backend.agent.tools.registry import tool_registry
from backend.core.policies import RiskLevel, classify_browser_op
from backend.agent.nodes.intent import intent_node
from backend.agent.nodes.planner import planner_node


class TestBrowserModels(unittest.TestCase):

    def test_interactive_element_serialization(self):
        elem = InteractiveElement(
            id="login-btn",
            tag="button",
            role="button",
            text="Log In",
            selector="#login-btn",
            visible=True,
            enabled=True,
        )
        d = elem.to_dict()
        self.assertEqual(d["id"], "login-btn")
        self.assertEqual(d["tag"], "button")
        self.assertEqual(d["text"], "Log In")
        self.assertEqual(d["selector"], "#login-btn")
        self.assertNotIn("placeholder", d)

    def test_browser_state_compact_dict(self):
        state = BrowserState(
            url="https://example.com/dashboard",
            title="Dashboard",
            active_target="tab-123",
            tabs=[TabInfo(id="tab-123", title="Dashboard", url="https://example.com/dashboard")],
            frames=[FrameInfo(id="frame-1", url="https://example.com/embed")],
            interactive_elements=[
                InteractiveElement(id="btn-1", tag="button", text="Save"),
                InteractiveElement(id="input-1", tag="input", type="text", placeholder="Search"),
            ],
            focused_element="#input-1",
            console_errors=[],
        )
        compact = state.to_compact_dict()
        self.assertEqual(compact["url"], "https://example.com/dashboard")
        self.assertEqual(compact["title"], "Dashboard")
        self.assertEqual(compact["active_tab_id"], "tab-123")
        self.assertEqual(compact["frames_detected"], 1)
        self.assertEqual(compact["interactive_elements_count"], 2)
        self.assertEqual(len(compact["interactive_elements"]), 2)


class TestDOMInspection(unittest.TestCase):

    def test_simplify_html(self):
        raw_html = """
        <html>
            <head>
                <script>var tracker = 123;</script>
                <style>.header { color: red; }</style>
            </head>
            <body>
                <header><h1>Welcome</h1></header>
                <form action="/login">
                    <input type="text" name="user" id="user" placeholder="Username" />
                    <button type="submit">Submit</button>
                </form>
                <svg width="500" height="500"><path d="M10 10 H 90 V 90 H 10 L 10 10"/></svg>
                <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" />
            </body>
        </html>
        """
        cleaned = simplify_html(raw_html)
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("<style", cleaned)
        self.assertNotIn("base64", cleaned)
        self.assertIn("<form", cleaned)
        self.assertIn("Username", cleaned)
        self.assertIn("Submit", cleaned)
        self.assertIn("<svg>[icon]</svg>", cleaned)

    def test_parse_interactive_elements(self):
        raw = [
            {"id": "submit-btn", "tag": "button", "text": "Submit", "selector": "#submit-btn", "visible": True},
            {"id": "email-input", "tag": "input", "type": "email", "selector": "#email-input", "visible": True},
        ]
        parsed = parse_interactive_elements_from_dict(raw)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].id, "submit-btn")
        self.assertEqual(parsed[0].tag, "button")
        self.assertEqual(parsed[1].type, "email")


class TestToolRegistryAndPolicies(unittest.TestCase):

    def test_browser_tools_registered(self):
        expected_tools = [
            ("browser_get_tabs", RiskLevel.READ_ONLY),
            ("browser_switch_tab", RiskLevel.SAFE),
            ("browser_navigate", RiskLevel.SAFE),
            ("browser_inspect", RiskLevel.READ_ONLY),
            ("browser_click", RiskLevel.SAFE),
            ("browser_type", RiskLevel.SAFE),
            ("browser_select", RiskLevel.SAFE),
            ("browser_press", RiskLevel.SAFE),
            ("browser_wait", RiskLevel.SAFE),
            ("browser_dismiss_popup", RiskLevel.SAFE),
            ("browser_execute_js", RiskLevel.MODIFYING),
        ]
        for name, expected_risk in expected_tools:
            tool = tool_registry.get(name)
            self.assertIsNotNone(tool, f"Tool '{name}' not found in registry")
            self.assertEqual(tool.risk_level, expected_risk, f"Tool '{name}' risk level mismatch")
            schema = tool.schema()
            self.assertEqual(schema["name"], name)
            self.assertEqual(schema["risk_level"], expected_risk.value)

    def test_classify_browser_op(self):
        self.assertEqual(classify_browser_op("browser_inspect"), RiskLevel.READ_ONLY)
        self.assertEqual(classify_browser_op("browser_get_tabs"), RiskLevel.READ_ONLY)
        self.assertEqual(classify_browser_op("browser_click"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_type"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_select"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_press"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_wait"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_dismiss_popup"), RiskLevel.SAFE)
        self.assertEqual(classify_browser_op("browser_execute_js"), RiskLevel.MODIFYING)


class TestBrowserToolExecution(unittest.IsolatedAsyncioTestCase):

    async def test_browser_dismiss_popup_execution(self):
        from backend.agent.tools.web_automation.tools import BrowserDismissPopupTool
        tool = BrowserDismissPopupTool()
        mock_engine = MagicMock()
        mock_engine.dismiss_popups = AsyncMock(return_value={"dismissed": True, "target": "button.close"})

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute()
            self.assertTrue(res.success)
            self.assertIn("Dismissed popup/modal", res.output)

    async def test_browser_click_tool_execution(self):
        tool = BrowserClickTool()
        mock_engine = MagicMock()
        mock_engine.click = AsyncMock(return_value={
            "success": True,
            "clicked_element": {"tag": "button", "id": "btn", "text": "Login"},
            "current_url": "https://example.com/home",
            "current_title": "Home Page",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector="#btn")
            self.assertTrue(res.success)
            self.assertIn("Clicked <button>", res.output)
            self.assertIn("Home Page", res.output)
            self.assertEqual(res.metadata["current_url"], "https://example.com/home")

    async def test_browser_type_tool_execution(self):
        tool = BrowserTypeTool()
        mock_engine = MagicMock()
        mock_engine.type_text = AsyncMock(return_value={
            "success": True,
            "selector": "input[name='q']",
            "value": "Nexus AI",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector="input[name='q']", text="Nexus AI")
            self.assertTrue(res.success)
            self.assertIn("Nexus AI", res.output)
            self.assertEqual(res.metadata["value"], "Nexus AI")

    async def test_browser_inspect_tool_execution(self):
        tool = BrowserInspectTool()
        mock_engine = MagicMock()
        mock_state = BrowserState(
            url="https://example.com",
            title="Example",
            active_target="tab-1",
            interactive_elements=[InteractiveElement(id="link-1", tag="a", text="More info", selector="#link-1")],
        )
        mock_engine.inspect_page = AsyncMock(return_value=mock_state)

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute()
            self.assertTrue(res.success)
            data = json.loads(res.output)
            self.assertEqual(data["url"], "https://example.com")
            self.assertEqual(len(data["interactive_elements"]), 1)

    async def test_browser_navigate_tool_execution(self):
        tool = BrowserNavigateTool()
        mock_engine = MagicMock()
        mock_engine.navigate = AsyncMock(return_value={
            "success": True,
            "url": "https://news.ycombinator.com",
            "title": "Hacker News",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(url="https://news.ycombinator.com")
            self.assertTrue(res.success)
            self.assertIn("Hacker News", res.output)

    async def test_browser_select_tool_execution(self):
        tool = BrowserSelectTool()
        mock_engine = MagicMock()
        mock_engine.select_option = AsyncMock(return_value={
            "success": True,
            "selectedText": "Option B",
            "selectedValue": "opt_b",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector="#dropdown", value="opt_b")
            self.assertTrue(res.success)
            self.assertIn("Option B", res.output)

    async def test_browser_press_tool_execution(self):
        tool = BrowserPressTool()
        mock_engine = MagicMock()
        mock_engine.press_key = AsyncMock(return_value={
            "success": True,
            "key": "Enter",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(key="Enter")
            self.assertTrue(res.success)
            self.assertIn("Pressed keyboard key 'Enter'", res.output)

    async def test_browser_wait_tool_execution(self):
        tool = BrowserWaitTool()
        mock_engine = MagicMock()
        mock_engine.wait_for = AsyncMock(return_value={
            "success": True,
            "condition": "selector_exists",
            "selector": ".dashboard",
        })

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector=".dashboard")
            self.assertTrue(res.success)
            self.assertIn("Condition satisfied", res.output)

    async def test_browser_execute_js_tool_execution(self):
        tool = BrowserExecuteJsTool()
        mock_engine = MagicMock()
        mock_engine.execute_js = AsyncMock(return_value={"count": 42})

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(script="return {count: 42};")
            self.assertTrue(res.success)
            self.assertIn("42", res.output)

    async def test_browser_switch_tab_tool_execution(self):
        tool = BrowserSwitchTabTool()
        mock_engine = MagicMock()
        mock_tab = TabInfo(id="tab-99", title="GitHub", url="https://github.com")
        mock_engine.switch_tab = AsyncMock(return_value=mock_tab)

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            # Test target_id
            res = await tool.execute(target_id="tab-99")
            self.assertTrue(res.success)
            self.assertIn("GitHub", res.output)
            self.assertIn("tab-99", res.output)

            # Test tab_id in kwargs
            res2 = await tool.execute(tab_id="tab-99")
            self.assertTrue(res2.success)
            self.assertIn("GitHub", res2.output)

            # Test url in kwargs
            res3 = await tool.execute(url="github.com")
            self.assertTrue(res3.success)
            self.assertIn("GitHub", res3.output)

    async def test_browser_switch_tab_extension_bridge(self):
        tool = BrowserSwitchTabTool()
        mock_bridge = MagicMock()
        mock_bridge.wait_for_connection = AsyncMock(return_value=True)
        mock_bridge.send_command = AsyncMock(return_value={"tab_id": 42, "title": "Google Forms", "url": "https://docs.google.com/forms"})

        with patch("backend.agent.tools.web_automation.tools.extension_bridge", mock_bridge):
            res = await tool.execute(tab_id=42)
            self.assertTrue(res.success)
            self.assertIn("Google Forms", res.output)
            self.assertIn("42", res.output)

    async def test_browser_element_not_found_handling(self):
        tool = BrowserClickTool()
        mock_engine = MagicMock()
        mock_engine.click = AsyncMock(side_effect=ElementNotFound("Could not find button '#missing'"))

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector="#missing")
            self.assertFalse(res.success)
            self.assertIn("Could not find button", res.error)

    async def test_browser_ambiguous_element_handling(self):
        tool = BrowserClickTool()
        mock_engine = MagicMock()
        mock_engine.click = AsyncMock(side_effect=ElementAmbiguous("Found 3 matching elements."))

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute(selector=".button-class")
            self.assertFalse(res.success)
            self.assertIn("Found 3 matching elements", res.error)

    async def test_browser_unavailable_handling(self):
        tool = BrowserGetTabsTool()
        mock_engine = MagicMock()
        mock_engine.get_tabs = AsyncMock(side_effect=BrowserUnavailable("Chrome is not listening on port 9222"))

        with patch("backend.agent.tools.web_automation.tools.BrowserAutomationEngine.get_instance", return_value=mock_engine):
            res = await tool.execute()
            self.assertFalse(res.success)
            self.assertIn("Chrome is not listening", res.error)


class TestIntentAndPlanner(unittest.IsolatedAsyncioTestCase):

    async def test_web_automation_fallback_planning(self):
        state = {
            "user_input": "Inspect the open browser tab DOM and source code",
            "goal": "Inspect the open browser tab DOM and source code",
            "intent": "web_automation",
            "observations": [],
        }
        with patch("backend.agent.nodes.planner.get_groq_api_key", return_value=None), \
             patch("backend.agent.nodes.planner._build_active_connector_priority_plan", return_value=[]):
            result = await planner_node(state)
            plan = result["plan"]
            self.assertGreaterEqual(len(plan), 1)
            self.assertIn(plan[0]["tool"], ("browser_inspect", "browser_get_tabs"))
            self.assertEqual(plan[0]["risk_level"], RiskLevel.READ_ONLY.value)


class TestExtensionBridgeAndInstaller(unittest.IsolatedAsyncioTestCase):

    def test_extension_path_and_manifest(self):
        from backend.core.extension_installer import get_extension_path, ensure_installed
        ext_dir = get_extension_path()
        self.assertTrue(ext_dir.exists())
        self.assertTrue((ext_dir / "manifest.json").exists())
        self.assertTrue((ext_dir / "background.js").exists())
        self.assertTrue((ext_dir / "content.js").exists())
        self.assertTrue(ensure_installed())

    async def test_extension_bridge_command_dispatch(self):
        from backend.agent.tools.web_automation.extension_bridge import ExtensionBridge
        bridge = ExtensionBridge()
        self.assertFalse(bridge.is_connected())

        mock_ws = AsyncMock()
        await bridge.register_socket(mock_ws)
        self.assertTrue(bridge.is_connected())

        # Simulate async command response
        async def mock_send(msg_text):
            msg = json.loads(msg_text)
            bridge.handle_incoming_message(json.dumps({
                "id": msg["id"],
                "success": True,
                "data": {"status": "ok", "url": "https://forms.new"}
            }))

        mock_ws.send_text = AsyncMock(side_effect=mock_send)
        res = await bridge.send_command("navigate", {"url": "https://forms.new"})
        self.assertEqual(res["url"], "https://forms.new")

        await bridge.unregister_socket(mock_ws)
        self.assertFalse(bridge.is_connected())


if __name__ == "__main__":
    unittest.main()
