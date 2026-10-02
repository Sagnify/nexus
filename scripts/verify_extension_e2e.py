import asyncio
import json
import sys
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"

async def main():
    print("==================================================")
    print("  NEXUS Extension End-to-End Functional Test")
    print("==================================================")
    
    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Check WebSocket status
        r = await client.get(f"{BASE}/api/extension/status")
        status = r.json()
        print(f"[1] Bridge Status: connected={status.get('connected')}")
        if not status.get("connected"):
            print("❌ Extension is not connected to backend WebSocket!")
            return False

        # 2. Navigate to test harness
        test_url = f"{BASE}/test-harness"
        print(f"[2] Navigating to test harness: {test_url}")
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "navigate",
            "payload": {"url": test_url}
        })
        nav_res = r.json()
        print(f"    Navigation result: {nav_res}")
        await asyncio.sleep(1.5)

        # 3. Ping content script
        print("[3] Pinging Content Script in active tab...")
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "ping",
            "payload": {}
        })
        ping_res = r.json()
        print(f"    Ping response: {ping_res}")
        if not (ping_res.get("success") and ping_res.get("data", {}).get("pong")):
            print("❌ Content script did not respond to ping!")
            return False

        # 4. Inspect DOM
        print("[4] Inspecting DOM elements...")
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "inspect_dom",
            "payload": {"max_elements": 20}
        })
        dom_res = r.json()
        elements = dom_res.get("data", {}).get("interactive_elements", [])
        print(f"    Found {len(elements)} interactive elements:")
        for el in elements:
            print(f"      - tag={el.get('tag')} id={el.get('id')} text={el.get('text')} type={el.get('type')}")
        
        has_input = any(el.get("id") == "test-input" or "test-input" in el.get("selector", "") for el in elements)
        has_button = any(el.get("id") == "test-btn" or "test-btn" in el.get("selector", "") for el in elements)
        if not (has_input and has_button):
            print(f"❌ Could not find expected test elements! has_input={has_input}, has_button={has_button}")
            return False

        # 5. Type into #test-input
        print("[5] Typing text into #test-input...")
        type_text = "NEXUS 100% Verified!"
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "type_text",
            "payload": {"selector": "#test-input", "text": type_text, "clear": True}
        })
        type_res = r.json()
        print(f"    Type result: {type_res}")

        # 6. Click #test-btn
        print("[6] Clicking #test-btn...")
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "click_element",
            "payload": {"selector": "#test-btn"}
        })
        click_res = r.json()
        print(f"    Click result: {click_res}")
        await asyncio.sleep(0.5)

        # 7. Check page source / DOM state
        print("[7] Verifying DOM state post-actions...")
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "get_page_source",
            "payload": {"max_chars": 20000, "selector": "body"}
        })
        source_res = r.json()
        source = source_res.get("data", {}).get("source", "")
        
        # Check button click mutation
        button_clicked = "BUTTON_CLICKED_SUCCESS" in source or "Clicked!" in source
        print(f"    Status 'BUTTON_CLICKED_SUCCESS' in DOM: {button_clicked}")
        
        # Also inspect DOM again to check input value
        r = await client.post(f"{BASE}/api/extension/command", json={
            "action": "inspect_dom",
            "payload": {"max_elements": 10}
        })
        dom2_res = r.json()
        elements2 = dom2_res.get("data", {}).get("interactive_elements", [])
        input_value = None
        for el in elements2:
            if el.get("id") == "test-input":
                input_value = el.get("value")
                break
        print(f"    Input field current value: '{input_value}'")

        success = button_clicked and (input_value == type_text)
        print("==================================================")
        if success:
            print("  🎉 100% VERIFIED: Extension is fully functioning!")
            print("     - Navigation: PASS")
            print("     - Content script injection: PASS")
            print("     - DOM inspection: PASS")
            print("     - Typing into inputs: PASS")
            print("     - Clicking elements: PASS")
            print("     - Reactive page updates: PASS")
        else:
            print(f"  ⚠️ Some checks failed: button_clicked={button_clicked}, input_value={input_value}")
        print("==================================================")
        return success

if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
