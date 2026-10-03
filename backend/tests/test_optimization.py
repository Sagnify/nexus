import pytest
import os
import tempfile
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
