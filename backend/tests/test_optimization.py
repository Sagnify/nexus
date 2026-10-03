import pytest
import os
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from backend.agent.nodes import planner
from backend.agent.nodes.intent import intent_node
from backend.agent.skills.matcher import SkillMatcher, SkillRepository
from backend.agent.router.fastpath_router import match_fastpath_plan
from backend.agent.router.plan_cache import get_cached_plan, extract_template_signature
from backend.agent.validation.outcome_validator import (
    validate_task_outcome,
    verify_filesystem_outcome,
    verify_process_outcome,
    verify_command_outcome
)


def test_fastpath_app_launcher():
    """Verify deterministic routing for app launching (0 LLM calls)."""
    res = match_fastpath_plan("open chrome")
    assert res is not None
    assert len(res.plan) == 1
    assert res.plan[0]["tool"] == "run_command"
    assert "chrome" in res.plan[0]["args"]["command"].lower()

    res_notepad = match_fastpath_plan("launch notepad")
    assert res_notepad is not None
    assert res_notepad.plan[0]["tool"] == "run_command"
    assert "notepad" in res_notepad.plan[0]["args"]["command"].lower()


def test_fastpath_filesystem_folders():
    """Verify deterministic routing for system folder opening."""
    res_dl = match_fastpath_plan("open downloads folder")
    assert res_dl is not None
    assert res_dl.plan[0]["tool"] == "run_command"
    assert "Downloads" in res_dl.plan[0]["args"]["command"]

    res_dt = match_fastpath_plan("open desktop")
    assert res_dt is not None
    assert "Desktop" in res_dt.plan[0]["args"]["command"]


def test_fastpath_math_and_system():
    """Verify deterministic routing for calculator and system utilities."""
    res_calc = match_fastpath_plan("calculate 125 * 8")
    assert res_calc is not None
    assert res_calc.plan[0]["tool"] == "ai_response"
    assert "1000" in res_calc.plan[0]["args"]["answer"]

    res_time = match_fastpath_plan("what time is it")
    assert res_time is not None
    assert res_time.plan[0]["tool"] == "get_current_time"

    res_ss = match_fastpath_plan("take screenshot")
    assert res_ss is not None
    assert res_ss.plan[0]["tool"] == "inspect_screen"


def test_plan_cache_word_template():
    """Verify normalized template retrieval for docx creation."""
    cached_plan = get_cached_plan("create a word report template on AI Agents")
    assert cached_plan is not None
    assert len(cached_plan) >= 3
    tools = [s["tool"] for s in cached_plan]
    assert "document_create" in tools
    assert "document_add_title" in tools
    assert "document_save" in tools


def test_plan_cache_excel_template():
    """Verify normalized template retrieval for excel sheet creation."""
    cached_plan = get_cached_plan("create an excel spreadsheet template for Budget 2026")
    assert cached_plan is not None
    assert len(cached_plan) >= 2
    tools = [s["tool"] for s in cached_plan]
    assert "spreadsheet_create" in tools
    assert "spreadsheet_save" in tools


def test_plan_cache_signature():
    """Verify runtime signature extraction."""
    sig, params = extract_template_signature("create a word document template on Quantum Computing")
    assert sig == "create_word_report"
    assert "Quantum" in params.get("topic", "")


@pytest.mark.asyncio
async def test_word_file_request_generates_and_saves_docx_without_automation(monkeypatch):
    prompt = "make a word file on AI agent of about 3 pages"
    llm_call = AsyncMock(return_value=SimpleNamespace(content=(
        "# AI Agents\n\n## Overview\nAI agents perceive and act on their environment.\n\n"
        "## Architecture\nAn agent combines a model, tools, memory, and an execution loop."
    )))
    monkeypatch.setattr(planner, "_try_match_user_skill", AsyncMock(return_value=None))
    monkeypatch.setattr(planner, "_build_active_connector_priority_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(planner, "get_groq_api_key", lambda: "test-key")
    monkeypatch.setattr(planner, "get_gemma_api_key", lambda: None)
    monkeypatch.setattr(planner, "ainvoke_with_dynamic_switch", llm_call)
    monkeypatch.setattr(
        "backend.services.schedule_parser.schedule_parser.parse",
        AsyncMock(return_value=None),
    )

    result = await planner.planner_node({"goal": prompt, "user_input": prompt, "intent": "file_op"})
    tools = [step["tool"] for step in result["plan"]]

    assert llm_call.await_count == 1
    assert "approximately 1200 words" in llm_call.await_args.args[0][1].content
    assert tools[0] == "document_create"
    assert "document_add_title" in tools
    assert "document_add_heading" in tools
    assert "document_add_paragraph" in tools
    assert tools[-2:] == ["document_save", "document_verify"]
    assert not any(tool.startswith(("browser_", "click_", "type_", "press_")) for tool in tools)


@pytest.mark.asyncio
async def test_ppt_file_request_generates_and_saves_without_ui_automation(monkeypatch):
    prompt = "make a ppt file about AI agents"
    monkeypatch.setattr(planner, "_try_match_user_skill", AsyncMock(return_value=None))
    monkeypatch.setattr(planner, "_build_active_connector_priority_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(planner, "get_groq_api_key", lambda: "test-key")
    monkeypatch.setattr(planner, "get_gemma_api_key", lambda: None)
    monkeypatch.setattr(
        "backend.services.schedule_parser.schedule_parser.parse",
        AsyncMock(return_value=None),
    )

    result = await planner.planner_node({"goal": prompt, "user_input": prompt, "intent": "file_op"})
    plan = result["plan"]
    tools = [step["tool"] for step in plan]
    create_step = next(step for step in plan if step["tool"] == "presentation_create")
    save_step = next(step for step in plan if step["tool"] == "presentation_save")

    assert tools == ["presentation_create", "presentation_save", "presentation_verify"]
    assert create_step["args"]["topic"] == "AI agents"
    assert create_step["args"]["include_images"] is False
    assert save_step["args"]["path"].startswith("Desktop/")
    assert save_step["args"]["reveal"] is False


@pytest.mark.parametrize("prompt", [
    "make a word file on AI agents about 3 pages",
    "create an excel file about AI agents",
    "make a ppt file about AI agents",
])
@pytest.mark.asyncio
async def test_office_file_creation_overrides_active_browser_and_learned_skills(prompt, monkeypatch):
    intent = await intent_node({
        "user_input": prompt,
        "active_target": {"target_type": "browser", "application": "Chrome"},
    })
    assert intent["intent"] == "file_op"
    assert intent["selected_model"] == "artifact-creation-fastpath"

    skills_lookup = AsyncMock()
    monkeypatch.setattr(SkillRepository, "get_active_skills_for_matching", skills_lookup)
    match = await SkillMatcher().match_skill(prompt, uuid.uuid4(), None)
    assert match is None
    skills_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_unscoped_status_events_stay_with_their_workflow(monkeypatch):
    from backend.api import nexus as nexus_api

    class CaptureQueue:
        def __init__(self):
            self.events = []

        async def put(self, event):
            self.events.append(event)

    file_queue = CaptureQueue()
    browser_queue = CaptureQueue()
    monkeypatch.setattr(nexus_api, "_task_queues", {"file-task": file_queue, "browser-task": browser_queue})
    monkeypatch.setattr(nexus_api, "_task_states", {
        "file-task": {"execution_status": "executing"},
        "browser-task": {"execution_status": "executing"},
    })

    token = nexus_api._current_workflow_task_id.set("file-task")
    try:
        await nexus_api.push_event(None, "status", {"status": "executing", "message": "Generating document"})
    finally:
        nexus_api._current_workflow_task_id.reset(token)

    assert len(file_queue.events) == 1
    assert browser_queue.events == []

    await nexus_api.push_event(None, "status", {"status": "executing", "message": "Unattributed event"})
    assert len(file_queue.events) == 1
    assert browser_queue.events == []


@pytest.mark.asyncio
async def test_gmail_read_request_cannot_become_an_outgoing_email(monkeypatch):
    from backend.agent.tools.registry import tool_registry
    from backend.connectors.credentials_store import credentials_store

    monkeypatch.setattr(
        credentials_store,
        "get_credential",
        lambda user_id, connector_id: {"account_identifier": "owner@example.com"} if connector_id == "gmail" else None,
    )
    available_tools = {"gmail_list_messages", "gmail_brief_messages", "gmail_send_email", "gmail_create_draft"}
    monkeypatch.setattr(tool_registry, "has", lambda name: name in available_tools)
    compose = AsyncMock(return_value=("Subject", "Body"))
    monkeypatch.setattr(planner, "_compose_smart_email", compose)

    read_plan = await planner._build_active_connector_priority_plan("check my latest emails")
    assert len(read_plan) == 1
    assert read_plan[0]["tool"] == "gmail_list_messages"
    assert read_plan[0]["args"] == {"query": "in:inbox", "max_results": 10}
    assert read_plan[0]["risk_level"] == "READ_ONLY"
    compose.assert_not_awaited()

    brief_plan = await planner._build_active_connector_priority_plan("make a brief of all emails I have received")
    assert brief_plan[0]["tool"] == "gmail_brief_messages"
    assert brief_plan[0]["args"] == {"query": "-from:me", "max_results": 50}
    assert brief_plan[0]["risk_level"] == "READ_ONLY"

    send_plan = await planner._build_active_connector_priority_plan("send an email to friend@example.com saying hello")
    assert send_plan[0]["tool"] == "gmail_send_email"
    assert send_plan[0]["risk_level"] == "PRIVILEGED"


def test_filesystem_outcome_validator():
    """Verify ground-truth verification of created files."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"NEXUS Ground Truth Outcome Verification")
        temp_path = f.name

    try:
        val = verify_filesystem_outcome(temp_path)
        assert val.passed is True
        assert "non-empty size" in val.reason

        # Test non-existent file
        val_fail = verify_filesystem_outcome("C:\\non_existent_nexus_file_xyz123.bin")
        assert val_fail.passed is False
        assert "does not exist" in val_fail.reason
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_command_outcome_validator():
    """Verify command exit code outcome checking."""
    val = verify_command_outcome(command="echo 'hi'", exit_code=0, stdout="Success")
    assert val.passed is True

    val_fail = verify_command_outcome(command="rm /etc", exit_code=1, stderr="Permission Denied")
    assert val_fail.passed is False
    assert "exit code 1" in val_fail.reason


@pytest.mark.asyncio
async def test_full_state_outcome_validation():
    """Verify end-to-end outcome validator on task state."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"Report completed")
        temp_file = f.name

    try:
        state = {
            "fast_path_used": True,
            "llm_calls_count": 0,
            "plan": [
                {
                    "id": "step_1",
                    "description": "Write file",
                    "tool": "write_file",
                    "args": {"file_path": temp_file},
                    "result": f"Saved file to {temp_file}",
                    "status": "completed"
                }
            ],
            "issues": []
        }
        res = await validate_task_outcome(state)
        assert res.passed is True
        assert res.tier == "ground_truth"
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
