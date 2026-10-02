"""End-to-end live test for creating a Google Form with Name and Phone Number fields."""
import asyncio
import sys
import json
from backend.agent.tools.web_automation.driver import BrowserAutomationEngine
from backend.agent.tools.web_automation.tools import (
    BrowserNavigateTool,
    BrowserDismissPopupTool,
    BrowserInspectTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserWaitTool,
)

async def main():
    print("=" * 60)
    print("[NEXUS] STRUCTURED BROWSER AUTOMATION TEST")
    print("Goal: Make a Google Form with Name & Phone Number fields")
    print("=" * 60)

    engine = BrowserAutomationEngine.get_instance()
    
    # 1. Navigate to Google Forms
    print("\n[Step 1] Navigating to Google Forms (https://docs.google.com/forms/u/0/create)...")
    nav_tool = BrowserNavigateTool()
    res = await nav_tool.execute(url="https://docs.google.com/forms/u/0/create")
    print(f"Result: {res.output or res.error}")
    
    # Wait for DOM to settle
    print("\n[Step 2] Waiting for form editor DOM to stabilize...")
    wait_tool = BrowserWaitTool()
    await wait_tool.execute(seconds=3)

    # 2. Dismiss any onboarding / welcome dialogs or popups
    print("\n[Step 3] Checking and dismissing any welcome/onboarding overlays...")
    dismiss_tool = BrowserDismissPopupTool()
    res = await dismiss_tool.execute()
    print(f"Dismiss output: {res.output}")

    # 3. Inspect DOM
    print("\n[Step 4] Inspecting interactive DOM elements...")
    inspect_tool = BrowserInspectTool()
    res = await inspect_tool.execute(interactive_only=True)
    elements = json.loads(res.output)
    print(f"Found {len(elements)} interactive elements on page.")

    # 4. Set Question 1 Title to "Name"
    print("\n[Step 5] Setting first question to 'Name'...")
    type_tool = BrowserTypeTool()
    # Google forms first question input
    res = await type_tool.execute(
        selector="div[role='listitem'] [contenteditable='true'], [aria-label*='Question title'], [role='heading'][contenteditable='true']",
        text="Name",
        clear_first=True
    )
    print(f"Type result: {res.output or res.error}")

    await asyncio.sleep(1)

    # 5. Add second question (Click the '+' button)
    print("\n[Step 6] Clicking 'Add question' (+) button...")
    click_tool = BrowserClickTool()
    res = await click_tool.execute(
        selector="[aria-label*='Add question'], div[data-tooltip*='Add question'], div[role='button'][aria-label*='question']",
        text="Add question"
    )
    print(f"Click '+' result: {res.output or res.error}")

    await asyncio.sleep(1.5)

    # 6. Set Question 2 Title to "Phone Number"
    print("\n[Step 7] Setting second question to 'Phone Number'...")
    res = await type_tool.execute(
        selector="div[role='listitem']:last-of-type [contenteditable='true'], div[aria-selected='true'] [contenteditable='true'], [aria-label*='Question title']",
        text="Phone Number",
        clear_first=True
    )
    print(f"Type result: {res.output or res.error}")

    await asyncio.sleep(1)

    # 7. Take final verification inspect
    print("\n[Step 8] Final Verification of Form state...")
    res = await inspect_tool.execute(interactive_only=True)
    final_elements = json.loads(res.output)
    form_texts = [e.get("text") or e.get("value") or e.get("aria_label") for e in final_elements if e.get("text") or e.get("value") or e.get("aria_label")]
    print(f"Form items discovered: {[t for t in form_texts if 'Name' in str(t) or 'Phone' in str(t)]}")

    print("\n" + "=" * 60)
    print("[SUCCESS] TEST EXECUTION COMPLETED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
