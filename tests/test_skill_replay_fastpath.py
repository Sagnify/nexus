import pytest
from backend.agent.nodes.executor import _react_decide

@pytest.mark.asyncio
async def test_react_decide_skill_replay_fastpath():
    """Verify that skill replay directly executes pre-compiled browser steps with zero LLM calls."""
    plan = [
        {
            "id": "skill-step-1-abcd",
            "title": "Navigate to Google Forms",
            "tool": "browser_navigate",
            "args": {"url": "https://forms.new"},
            "status": "pending",
        },
        {
            "id": "skill-step-2-efgh",
            "title": "Type Form Title",
            "tool": "browser_type",
            "args": {"selector": "input.whsOnd", "text": "Customer Feedback"},
            "status": "pending",
        },
        {
            "id": "skill-step-3-ijkl",
            "title": "Click Add Question",
            "tool": "browser_click",
            "args": {"selector": "div[aria-label='Add question']"},
            "status": "pending",
        },
    ]
    dom = {"url": "https://docs.google.com/forms/d/e/edit", "interactive_elements": []}
    history = []

    # Step 1: Navigate fastpath
    d1 = await _react_decide(
        goal="Create customer feedback form",
        dom=dom,
        history=history,
        plan_guide=plan,
        is_web_task=True,
        current_idx=0,
        is_replay_mode=True,
    )
    assert d1["action"] == "browser_navigate"
    assert d1["args"]["url"] == "https://forms.new"
    assert "[Skill Replay]" in d1["reasoning"]

    # Step 2: Browser type fastpath (historically was blocked and dumped 6000 DOM tokens into Groq)
    history.append({"action": "browser_navigate", "success": True, "result": "navigated"})
    d2 = await _react_decide(
        goal="Create customer feedback form",
        dom=dom,
        history=history,
        plan_guide=plan,
        is_web_task=True,
        current_idx=1,
        is_replay_mode=True,
    )
    assert d2["action"] == "browser_type"
    assert d2["args"]["text"] == "Customer Feedback"
    assert "[Skill Replay]" in d2["reasoning"]

    # Step 3: Browser click fastpath
    history.append({"action": "browser_type", "success": True, "result": "typed"})
    d3 = await _react_decide(
        goal="Create customer feedback form",
        dom=dom,
        history=history,
        plan_guide=plan,
        is_web_task=True,
        current_idx=2,
        is_replay_mode=True,
    )
    assert d3["action"] == "browser_click"
    assert d3["args"]["selector"] == "div[aria-label='Add question']"
    assert "[Skill Replay]" in d3["reasoning"]

    # Completion fastpath
    d_done = await _react_decide(
        goal="Create customer feedback form",
        dom=dom,
        history=history,
        plan_guide=plan,
        is_web_task=True,
        current_idx=3,
        is_replay_mode=True,
    )
    assert d_done["action"] == "goal_achieved"

@pytest.mark.asyncio
async def test_react_decide_intrusive_popup_interception():
    """Verify that an intrusive modal is intercepted and dismissed before step execution in skill replay."""
    plan = [
        {
            "id": "skill-step-1-abcd",
            "title": "Click Next",
            "tool": "browser_click",
            "args": {"selector": "#btn-next"},
            "status": "pending",
        }
    ]
    dom = {
        "url": "https://example.com",
        "active_modal": {
            "title": "Promotional Survey",
            "is_intrusive": True,
            "close_selector": "button.close-modal",
        },
        "interactive_elements": [],
    }
    history = []

    d = await _react_decide(
        goal="Do something",
        dom=dom,
        history=history,
        plan_guide=plan,
        is_web_task=True,
        current_idx=0,
        is_replay_mode=True,
    )
    assert d["action"] == "browser_dismiss_popups"
    assert d.get("is_auxiliary") is True
