"""
NEXUS API - Pill Routing Enhancement
Routes web-only skills to extension pill for UI consistency.
"""
from __future__ import annotations
import asyncio
import datetime
import time
import json
import uuid
import logging
from contextvars import ContextVar
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.agent.graph import nexus_graph
from backend.agent.state import NexusState
from backend.core.permissions import permission_engine
from backend.core.firebase_auth import get_current_user_optional
from backend.database.models import User
from backend.agent.nodes.skill_executor import get_skill_execution_context

logger = logging.getLogger("nexus.api")
router = APIRouter()

# Active tasks store
_task_queues: dict[str, asyncio.Queue] = {}
_task_states: dict[str, NexusState] = {}
_task_background_jobs: dict[str, asyncio.Task] = {}
_task_pause_events: dict[str, asyncio.Event] = {}
_token_callbacks: dict[str, Any] = {}
_pending_user_inputs: dict[str, asyncio.Future[str]] = {}
_current_workflow_task_id: ContextVar[str | None] = ContextVar("nexus_workflow_task_id", default=None)


class RunRequest(BaseModel):
    input: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None


class PermissionDecision(BaseModel):
    step_id: str
    approved: bool


class UserInputSubmission(BaseModel):
    value: str
    task_id: Optional[str] = None


async def push_event(task_id: str | None, event_type: str, data: dict):
    if not task_id:
        task_id = _current_workflow_task_id.get()
    if not task_id:
        active_ids = [tid for tid, st in _task_states.items() if st.get("execution_status") in ("executing", "running", "paused", "observing")]
        task_id = active_ids[0] if len(active_ids) == 1 else None
    if task_id:
        queue = _task_queues.get(task_id)
        if queue:
            await queue.put({"event": event_type, "data": json.dumps(data)})


async def run_agent_workflow(task_id: str, initial_state: NexusState, resume: bool = False):
    token = _current_workflow_task_id.set(task_id)
    try:
        return await _run_agent_workflow(task_id, initial_state, resume)
    finally:
        _current_workflow_task_id.reset(token)


async def _run_agent_workflow(task_id: str, initial_state: NexusState, resume: bool = False):
    config = {"configurable": {"thread_id": task_id}}
    max_retries = 3
    retry_count = 0
    
    # Determine pill routing for web-only skills
    plan = initial_state.get("plan", [])
    exec_context = get_skill_execution_context(plan)
    use_extension_pill = exec_context["use_extension_pill"]
    
    # Store in state for downstream nodes
    initial_state["_use_extension_pill"] = use_extension_pill
    initial_state["_pill_type"] = exec_context["pill_type"]
    
    logger.info(
        "[SkillExecutor] Skill composition: %s | Using %s pill",
        exec_context["composition"],
        "extension" if use_extension_pill else "desktop"
    )

    while retry_count <= max_retries:
        try:
            if not resume:
                await push_event(task_id, "status", {"status": "thinking", "message": "Analyzing intent..."})

            input_state = None
            if not resume:
                input_state = initial_state
            else:
                try:
                    cp = await nexus_graph.aget_state(config)
                    if not cp or not cp.values:
                        input_state = _task_states.get(task_id) or initial_state
                except Exception:
                    input_state = _task_states.get(task_id) or initial_state

            async for output in nexus_graph.astream(
                input_state,
                config=config,
                stream_mode="updates"
            ):
                p_event = _task_pause_events.get(task_id)
                if p_event:
                    await p_event.wait()
                for node_name, node_update in output.items():
                    if not isinstance(node_update, dict):
                        continue

                    current = _task_states.get(task_id, initial_state)
                    current.update(node_update)
                    _task_states[task_id] = current

                    if node_name == "intent":
                        await push_event(task_id, "intent", {
                            "intent": node_update.get("intent"),
                            "goal": node_update.get("goal"),
                            "model": node_update.get("selected_model"),
                        })
                    elif node_name == "reasoner":
                        obs = node_update.get("observations", [])
                        if obs:
                            await push_event(task_id, "reasoning", {"thought": obs[-1]})
                    elif node_name == "planner":
                        await push_event(task_id, "plan", {
                            "steps": node_update.get("plan", []),
                        })
                    elif node_name == "permission_gate":
                        if node_update.get("permission_required"):
                            current_plan = current.get("plan", [])
                            current_idx = current.get("current_step", 0)
                            step_id = current_plan[current_idx].get("id") if current_idx < len(current_plan) else "step"
                            await push_event(task_id, "permission_required", {
                                "step_id": step_id,
                                "items": node_update.get("permission_items", []),
                                "plan": current_plan,
                                "current_step": current_idx,
                            })
                            return
                    elif node_name == "executor":
                        await push_event(task_id, "step_progress", {
                            "plan": node_update.get("plan", []),
                            "tool_calls": node_update.get("tool_calls", []),
                        })
                        if node_update.get("execution_status") == "failed":
                            err_msg = node_update.get("error") or "Action failed during execution."
                            is_web = (
                                current.get("intent") == "web_automation" or
                                any(s.get("tool", "").startswith("browser_") for s in current.get("plan", []))
                            )
                            if is_web:
                                try:
                                    from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                                    if extension_bridge.is_connected():
                                        await extension_bridge.send_command("automation_disable_shield", {}, timeout=2.0)
                                        await extension_bridge.send_command("automation_update_step", {
                                            "step": "Task stopped due to issue",
                                            "error": err_msg,
                                            "issues": [{"type": "failure", "message": err_msg}],
                                        }, timeout=2.0)
                                except Exception:
                                    pass
                            await push_event(task_id, "issue", {
                                "type": "failure",
                                "message": err_msg,
                                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                            })
                    elif node_name == "observer":
                        obs = node_update.get("observations", [])
                        if obs:
                            last_obs = obs[-1]
                            await push_event(task_id, "observation", {"observation": last_obs})
                            if any(w in last_obs.lower() for w in ("rate limit", "429", "warning", "failed", "low confidence", "retry")):
                                await push_event(task_id, "issue", {
                                    "type": "rate_limit" if "rate limit" in last_obs.lower() else "warning",
                                    "message": last_obs,
                                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                                })
                    elif node_name == "evaluator":
                        if node_update.get("execution_status") == "completed":
                            perf_metrics = {
                                "llm_calls": node_update.get("llm_calls_count", 0),
                                "deterministic_steps": node_update.get("deterministic_actions_count", 0),
                                "tokens_saved": node_update.get("tokens_saved_estimate", 0),
                                "latency_ms": node_update.get("latency_ms", 0),
                                "fast_path": node_update.get("fast_path_used"),
                                "cache_hit": node_update.get("cache_hit", False),
                                "validation_tier": node_update.get("validation_tier"),
                                "validation_passed": node_update.get("validation_passed"),
                                "validation_reason": node_update.get("validation_reason"),
                            }
                            await push_event(task_id, "performance_metrics", perf_metrics)
                            await push_event(task_id, "completed", {
                                "final_response": node_update.get("final_response"),
                                "spoken_response": node_update.get("spoken_response"),
                                "plan": current.get("plan", []),
                                "performance_metrics": perf_metrics,
                            })
                            await push_event(task_id, "done", {})
                            try:
                                from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                                if extension_bridge.is_connected():
                                    await extension_bridge.send_command("automation_stop", {}, timeout=2.0)
                            except Exception:
                                pass
                            return
                        elif node_update.get("execution_status") == "failed":
                            err_msg = node_update.get("error") or "Execution failed: goal could not be achieved."
                            is_web = (
                                current.get("intent") == "web_automation" or
                                any(s.get("tool", "").startswith("browser_") for s in current.get("plan", []))
                            )
                            if is_web:
                                try:
                                    from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                                    if extension_bridge.is_connected():
                                        await extension_bridge.send_command("automation_disable_shield", {}, timeout=2.0)
                                        await extension_bridge.send_command("automation_update_step", {
                                            "step": "Task stopped due to issue",
                                            "error": err_msg,
                                            "issues": [{"type": "failure", "message": err_msg}]
                                        }, timeout=2.0)
                                except Exception:
                                    pass
                            await push_event(task_id, "issue", {
                                "type": "failure",
                                "message": err_msg,
                                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                            })
                            await push_event(task_id, "error", {
                                "error": err_msg,
                                "final_response": node_update.get("final_response"),
                                "spoken_response": node_update.get("spoken_response"),
                                "plan": current.get("plan", []),
                            })
                            await push_event(task_id, "done", {})
                            return

            final_st = _task_states.get(task_id, {})
            if final_st.get("execution_status") == "failed":
                await push_event(task_id, "error", {
                    "error": final_st.get("error", "Task execution failed."),
                    "final_response": final_st.get("final_response"),
                    "spoken_response": final_st.get("spoken_response"),
                    "plan": final_st.get("plan", []),
                })
            elif final_st.get("execution_status") == "completed":
                await push_event(task_id, "completed", {
                    "final_response": final_st.get("final_response", "Task completed."),
                    "spoken_response": final_st.get("spoken_response"),
                    "plan": final_st.get("plan", []),
                })
            try:
                from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                if extension_bridge.is_connected():
                    await extension_bridge.send_command("automation_stop", {}, timeout=2.0)
            except Exception:
                pass
            await push_event(task_id, "done", {})
            return

        except asyncio.CancelledError:
            try:
                from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                if extension_bridge.is_connected():
                    await extension_bridge.send_command("automation_stop", {}, timeout=2.0)
            except Exception:
                pass
            await push_event(task_id, "error", {"error": "Task cancelled by user."})
            await push_event(task_id, "done", {})
            return
        except Exception as e:
            logger.exception(f"[Task Execution] Task {task_id} encountered exception: {e}")
            retry_count += 1
            if retry_count > max_retries:
                try:
                    from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                    if extension_bridge.is_connected():
                        await extension_bridge.send_command("automation_stop", {}, timeout=2.0)
                except Exception:
                    pass
                await push_event(task_id, "error", {"error": f"Task failed after {max_retries} retries: {str(e)}"})
                await push_event(task_id, "done", {})
                return
            else:
                wait_time = 2 ** retry_count
                await push_event(task_id, "status", {
                    "status": "retrying",
                    "message": f"Retrying after error (attempt {retry_count}/{max_retries})...",
                    "retry_count": retry_count,
                    "wait_seconds": wait_time
                })
                await asyncio.sleep(wait_time)
                resume = True


class SelectTargetRequest(BaseModel):
    target_id: str


@router.get("/targets")
async def get_targets():
    from backend.core.targets import target_manager
    targets = target_manager.discover_targets()
    active_target = target_manager.get_active_target()
    return {
        "active_target_id": active_target.id,
        "active_target": active_target.model_dump(),
        "targets": [t.model_dump() for t in targets],
    }


@router.post("/target/select")
async def select_target(req: SelectTargetRequest):
    from backend.core.targets import target_manager, TargetUnavailableException
    try:
        target, context = target_manager.select_target(req.target_id)
        return {
            "success": True,
            "target": target.model_dump(),
            "context": context.model_dump(),
        }
    except TargetUnavailableException as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.get("/target/current")
async def get_current_target():
    from backend.core.targets import target_manager
    target = target_manager.get_active_target()
    context = target_manager.acquire_context()
    return {
        "target": target.model_dump(),
        "context": context.model_dump(),
    }


@router.post("/run")
async def run_task(
    req: RunRequest,
    user: Optional[User] = Depends(get_current_user_optional),
):
    task_id = f"task_{uuid.uuid4().hex[:10]}"
    queue = asyncio.Queue()
    _task_queues[task_id] = queue

    p_event = asyncio.Event()
    p_event.set()
    _task_pause_events[task_id] = p_event

    async def on_token(chunk: str):
        await push_event(task_id, "token", {"chunk": chunk})

    _token_callbacks[task_id] = on_token

    from backend.core.targets import target_manager
    try:
        cur_target = target_manager.get_active_target().model_dump()
        cur_context = target_manager.refresh_current_context().model_dump()
    except Exception:
        cur_target = {"id": "antigravity", "application": "Antigravity", "target_type": "antigravity"}
        cur_context = {}

    # Registered users and local desktop users receive a user_id to match saved skills.
    is_valid_user = bool(
        user
        and (
            (user.firebase_uid and not user.firebase_uid.startswith("guest_"))
            or (user.firebase_uid and user.firebase_uid.startswith("local_device_"))
            or (user.email and (user.email.lower().endswith("@nexus.desktop") or user.email.lower().endswith(".nexus.desktop")))
        )
    )
    user_id = str(user.id) if is_valid_user else None

    # Resolve user display name for email sign-offs and personalization
    import re
    resolved_name = req.user_name
    if not resolved_name and user and user.display_name:
        resolved_name = user.display_name
    if not resolved_name and user and user.email:
        prefix = user.email.split("@")[0]
        clean = re.sub(r"\d+", "", prefix).strip("._- ")
        resolved_name = clean.capitalize() if len(clean) >= 2 else prefix.capitalize()
    if not resolved_name:
        try:
            from backend.connectors.credentials_store import credentials_store
            creds = credentials_store.get_credential(user_id or "default", "gmail") or credentials_store.get_credential("default", "gmail")
            if creds:
                sender_acc = creds.get("account_identifier") or ""
                if sender_acc:
                    prefix = sender_acc.split("@")[0]
                    clean = re.sub(r"\d+", "", prefix).strip("._- ")
                    resolved_name = clean.capitalize() if len(clean) >= 2 else prefix.capitalize()
        except Exception:
            pass
    if not resolved_name:
        import os
        os_user = os.environ.get("USERNAME") or os.environ.get("USER")
        if os_user:
            resolved_name = os_user.capitalize()

    initial_state: NexusState = {
        "task_id": task_id,
        "user_id": user_id,
        "user_name": resolved_name,
        "user_input": req.input,
        "messages": [{"role": "user", "content": req.input}],
        "intent": "general",
        "goal": req.input,
        "plan": [],
        "current_step": 0,
        "selected_model": "qwen/qwen3.8-27b",
        "model_history": [],
        "memory_context": [],
        "tool_calls": [],
        "tool_results": [],
        "observations": [],
        "screen_context": None,
        "permission_required": False,
        "permission_status": "none",
        "permission_items": [],
        "execution_status": "thinking",
        "retry_count": 0,
        "max_retries": 3,
        "notification_events": [],
        "final_response": None,
        "spoken_response": None,
        "error": None,
        "execution_history": [],
        "goal_achieved": False,
        "max_iterations": 20,
        "verification_retries": 0,
        "verification_details": None,
        "active_target": cur_target,
        "active_context": cur_context,
        "start_time": time.time(),
        "llm_calls_count": 0,
        "deterministic_actions_count": 0,
        "tokens_saved_estimate": 0,
        "fast_path_used": None,
        "cache_hit": False,
        "latency_ms": 0.0,
        "validation_tier": None,
        "validation_passed": None,
        "validation_reason": None,
    }
    _task_states[task_id] = initial_state

    job = asyncio.create_task(run_agent_workflow(task_id, initial_state))
    _task_background_jobs[task_id] = job

    return {
        "task_id": task_id,
        "status": "started",
    }


@router.get("/stream/{task_id}")
async def stream_task(task_id: str, request: Request):
    queue = _task_queues.get(task_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Task not found or already completed.")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                event = await queue.get()
                yield event
                if event.get("event") == "done":
                    break
        finally:
            pass

    return EventSourceResponse(event_generator())


@router.post("/permission/{task_id}")
async def submit_permission(task_id: str, decision: PermissionDecision):
    state = _task_states.get(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found.")

    permission_engine.resolve_permission(task_id, decision.step_id, decision.approved)

    if decision.approved:
        config = {"configurable": {"thread_id": task_id}}
        state_update = {
            "permission_status": "approved",
            "permission_required": False,
            "execution_status": "executing",
        }
        await nexus_graph.aupdate_state(config, state_update, as_node="permission_gate")
        state.update(state_update)
        job = asyncio.create_task(run_agent_workflow(task_id, state, resume=True))
        _task_background_jobs[task_id] = job
        return {"status": "resumed"}
    else:
        state["permission_status"] = "rejected"
        state["execution_status"] = "failed"
        await push_event(task_id, "error", {"error": "Action rejected by user."})
        await push_event(task_id, "done", {})
        return {"status": "rejected"}


@router.post("/pause")
@router.post("/pause/{task_id}")
async def pause_task(task_id: str | None = None):
    if not task_id:
        active_ids = [tid for tid, st in _task_states.items() if st.get("execution_status") in ("executing", "running")]
        task_id = active_ids[-1] if active_ids else (list(_task_pause_events.keys())[-1] if _task_pause_events else None)
    if not task_id:
        return {"status": "no_active_task"}
    pause_event = _task_pause_events.get(task_id)
    if pause_event:
        pause_event.clear()
        st = _task_states.get(task_id)
        if st:
            st["execution_status"] = "paused"
        await push_event(task_id, "pause_state", {"is_paused": True})
        await push_event(task_id, "status", {"status": "paused", "message": "Automation paused"})
        is_web = (
            st.get("intent") == "web_automation" or
            any(s.get("tool", "").startswith("browser_") for s in st.get("plan", []))
        ) if st else False
        if is_web:
            try:
                from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                if extension_bridge.is_connected():
                    await extension_bridge.send_command("automation_pause", {}, timeout=2.0)
            except Exception:
                pass
        return {"status": "paused", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task not found.")


@router.post("/resume")
@router.post("/resume/{task_id}")
async def resume_task(task_id: str | None = None):
    if not task_id:
        paused_ids = [tid for tid, st in _task_states.items() if st.get("execution_status") == "paused"]
        task_id = paused_ids[-1] if paused_ids else (list(_task_pause_events.keys())[-1] if _task_pause_events else None)
    if not task_id:
        return {"status": "no_active_task"}
    pause_event = _task_pause_events.get(task_id)
    if pause_event:
        pause_event.set()
        st = _task_states.get(task_id)
        if st:
            st["execution_status"] = "executing"
        await push_event(task_id, "pause_state", {"is_paused": False})
        await push_event(task_id, "status", {"status": "executing", "message": "Resuming automation..."})
        is_web = (
            st.get("intent") == "web_automation" or
            any(s.get("tool", "").startswith("browser_") for s in st.get("plan", []))
        ) if st else False
        if is_web:
            try:
                from backend.agent.tools.web_automation.extension_bridge import extension_bridge
                if extension_bridge.is_connected():
                    await extension_bridge.send_command("automation_resume", {}, timeout=2.0)
            except Exception:
                pass
        return {"status": "resumed", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task not found.")


@router.post("/cancel")
@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str | None = None):
    if not task_id:
        active_ids = [tid for tid, st in _task_states.items() if st.get("execution_status") in ("executing", "running", "paused", "observing")]
        task_id = active_ids[-1] if active_ids else (list(_task_background_jobs.keys())[-1] if _task_background_jobs else None)

    try:
        from backend.agent.tools.web_automation.extension_bridge import extension_bridge
        if extension_bridge.is_connected():
            await extension_bridge.send_command("automation_stop", {}, timeout=2.0)
    except Exception:
        pass

    if not task_id:
        return {"status": "cancelled", "message": "No active task running."}

    job = _task_background_jobs.get(task_id)
    if job and not job.done():
        job.cancel()
    p_event = _task_pause_events.get(task_id)
    if p_event:
        p_event.set()
    st = _task_states.get(task_id)
    if st:
        st["execution_status"] = "cancelled"

    await push_event(task_id, "issue", {
        "type": "cancelled",
        "message": "Automation cancelled by user via dismiss cross button.",
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
    })
    await push_event(task_id, "error", {"error": "Task cancelled by user."})
    await push_event(task_id, "done", {})
    return {"status": "cancelled", "task_id": task_id}


async def request_user_input(
    task_id: str,
    prompt: str,
    options: list[str] | None = None,
    placeholder: str = "",
) -> str:
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending_user_inputs[task_id] = fut

    await push_event(task_id, "user_input_request", {
        "task_id": task_id,
        "prompt": prompt,
        "options": options or [],
        "placeholder": placeholder or "Type your response...",
    })

    try:
        from backend.agent.tools.web_automation.extension_bridge import extension_bridge
        if extension_bridge.is_connected():
            await extension_bridge.send_command("automation_request_input", {
                "task_id": task_id,
                "prompt": prompt,
                "options": options or [],
                "placeholder": placeholder or "Type your response...",
            }, timeout=2.0)
    except Exception:
        pass

    try:
        val = await asyncio.wait_for(fut, timeout=300.0)
    except asyncio.TimeoutError:
        val = options[0] if options else "No response (timeout)"
    finally:
        _pending_user_inputs.pop(task_id, None)
        await push_event(task_id, "user_input_resolved", {"task_id": task_id})
        try:
            from backend.agent.tools.web_automation.extension_bridge import extension_bridge
            if extension_bridge.is_connected():
                await extension_bridge.send_command("automation_clear_input", {}, timeout=2.0)
        except Exception:
            pass

    return str(val)


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Transcribes audio WAV file via Groq Whisper Turbo and checks for wake word.
    Returns:
        text: full transcript
        wake_detected: boolean whether wake word was detected ('hey nexus', 'nexus', etc.)
        command: the actionable command text after the wake word
        error: error detail if transcription failed
    """
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            return {"text": "", "wake_detected": False, "command": "", "error": "Empty audio file received"}

        import re
        from backend.core.config import get_groq_api_key
        api_key = get_groq_api_key()
        if not api_key:
            return {"text": "", "wake_detected": False, "command": "", "error": "Groq API key not configured"}

        from groq import Groq
        client = Groq(api_key=api_key)

        text = ""
        transcription_err = None
        for model in ("whisper-large-v3-turbo", "whisper-large-v3"):
            try:
                transcription = await asyncio.to_thread(
                    client.audio.transcriptions.create,
                    file=("audio.wav", audio_bytes, "audio/wav"),
                    model=model,
                    response_format="json",
                    language="en",
                    temperature=0.0,
                )
                text = (getattr(transcription, "text", "") or "").strip()
                if text:
                    break
            except Exception as e:
                transcription_err = str(e)
                logger.warning(f"[STT] Groq transcription with {model} failed: {e}")

        if not text and transcription_err:
            return {"text": "", "wake_detected": False, "command": "", "error": transcription_err}

        wake_detected = False
        command = text
        # Detect "hey nexus", "hi nexus", "hello nexus", "ok nexus", "okay nexus", or just "nexus"
        match = re.match(r"^\s*(?:hey|hi|hello|ok|okay)?\s*nexus\b[,\s:!-]*", text, re.IGNORECASE)
        if match:
            wake_detected = True
            command = text[match.end():].strip()
            command = re.sub(r"^[,:\s!-]+", "", command).strip()

        return {
            "text": text,
            "wake_detected": wake_detected,
            "command": command,
        }
    except Exception as exc:
        logger.error(f"[STT] Transcription endpoint error: {exc}", exc_info=True)
        return {"text": "", "wake_detected": False, "command": "", "error": str(exc)}


@router.post("/input")
@router.post("/input/{task_id}")
async def submit_user_input(submission: UserInputSubmission, task_id: Optional[str] = None):
    tid = task_id or submission.task_id
    if not tid:
        pending_keys = list(_pending_user_inputs.keys())
        if pending_keys:
            tid = pending_keys[-1]

    if not tid or tid not in _pending_user_inputs:
        if _pending_user_inputs:
            tid = list(_pending_user_inputs.keys())[-1]
        else:
            return {"status": "no_pending_input", "detail": "No task is currently awaiting user input."}

    fut = _pending_user_inputs.get(tid)
    if fut and not fut.done():
        fut.set_result(submission.value)
    return {"status": "accepted", "task_id": tid, "value": submission.value}


class ExplorerRequest(BaseModel):
    path: str


@router.post("/reveal-in-explorer")
async def reveal_in_explorer(req: ExplorerRequest):
    import subprocess
    import sys
    from backend.core.paths import resolve_system_path
    p = resolve_system_path(req.path)
    if p.exists() and sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", f"/select,{str(p)}"])
            return {"status": "ok", "path": str(p)}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    elif p.exists():
        return {"status": "ok", "path": str(p)}
    return {"status": "not_found", "path": str(p)}


@router.post("/pick-save-path")
async def pick_save_path(default_filename: str = "presentation.pptx"):
    from backend.core.file_dialog import open_native_save_dialog
    selected = open_native_save_dialog(default_filename=default_filename)
    return {"selected_path": selected}


class ExcelExecuteRequest(BaseModel):
    instruction: str
    hwnd: Optional[int] = None
    workbook_name: Optional[str] = None
    sheet_name: Optional[str] = None


@router.get("/excel/windows")
async def get_excel_windows(copilot_hwnds: Optional[str] = None):
    """Enumerate all open Excel windows and their bounding rects on the desktop."""
    from backend.agent.tools.excel_copilot.resolver import get_open_excel_windows
    hwnds_set = set()
    if copilot_hwnds:
        for p in copilot_hwnds.split(","):
            p_str = p.strip().lstrip("-")
            if p_str.isdigit():
                hwnds_set.add(int(p.strip()))
    windows = get_open_excel_windows(copilot_hwnds=hwnds_set)
    return {"windows": windows}


@router.get("/excel/context")
async def get_excel_context(hwnd: Optional[int] = None, workbook_name: Optional[str] = None):
    """Acquire real-time deep context for a specific Excel window or workbook."""
    from backend.agent.tools.excel_copilot.context import acquire_deep_excel_context
    ctx = acquire_deep_excel_context(workbook_name=workbook_name, hwnd=hwnd)
    return {"context": ctx}


@router.post("/excel/execute")
async def execute_excel_instruction(req: ExcelExecuteRequest):
    """Execute a natural-language spreadsheet operation directly in the target Excel workbook."""
    from backend.agent.tools.excel_copilot.resolver import resolve_excel_target
    from backend.agent.tools.excel_copilot.context import acquire_deep_excel_context
    from backend.agent.tools.excel_copilot.planner import build_excel_copilot_plan
    from backend.agent.tools.registry import tool_registry
    from backend.core.targets import target_manager

    # 1. Resolve exact target
    try:
        app, wb, ws, win = resolve_excel_target(
            workbook_name=req.workbook_name,
            hwnd=req.hwnd,
        )
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Cannot connect to Excel target: {err}")

    # 2. Acquire real-time context
    active_target = {
        "application": "Excel",
        "target_type": "excel",
        "window_id": str(getattr(win, "Hwnd", req.hwnd or "")),
        "target_name": str(getattr(wb, "Name", req.workbook_name or "")),
        "file_path": str(getattr(wb, "FullName", "")),
    }
    context = acquire_deep_excel_context(workbook_name=req.workbook_name, hwnd=req.hwnd)

    # 3. Compile plan
    plan = build_excel_copilot_plan(req.instruction, active_target, context)

    if not plan:
        # Dynamic AI fallback planning
        try:
            import json
            import re
            from langchain_core.messages import HumanMessage
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch

            headers_summary = [h.get("name") for h in context.get("headers", [])]
            fallback_prompt = (
                f"You are NEXUS Excel Copilot. Translate this spreadsheet command into a 1-step JSON plan array.\n"
                f"Active Worksheet Columns: {headers_summary}\n"
                f"User Instruction: \"{req.instruction}\"\n\n"
                f"Available tools and valid operations:\n"
                f"- 'excel_formula': operation in ['sum', 'sumif', 'average', 'averageif', 'count', 'counta', 'countif', 'if'], target_column (str), condition_column (str, optional), condition_value (str, optional)\n"
                f"- 'excel_sort_filter': operation in ['sort', 'filter'], key_column (str), order in ['ascending', 'descending'], filter_column (str), filter_criteria (str)\n"
                f"- 'excel_pivot': row_fields (list), value_fields (list), aggregation in ['sum', 'average', 'count']\n"
                f"- 'excel_conditional_format': column (str), operator in ['greater', 'less', 'equal', 'color_scale'], value1 (num)\n"
                f"- 'excel_lookup': lookup_type in ['xlookup', 'vlookup'], lookup_value_col (str), dest_col (str)\n"
                f"- 'excel_data_cleanup': operation in ['remove_duplicates', 'text_to_columns', 'flash_fill', 'delete_rows', 'delete_columns', 'autofit']\n\n"
                f"Output strictly a JSON list with one object: [{{\"title\": \"...\", \"description\": \"...\", \"tool\": \"...\", \"args\": {{...}}}}] without markdown fencing."
            )
            llm_res = await ainvoke_with_dynamic_switch([HumanMessage(content=fallback_prompt)], temperature=0.0)
            raw_text = getattr(llm_res, "content", str(llm_res)).strip()
            if "```" in raw_text:
                m_json = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
                if m_json:
                    raw_text = m_json.group(1).strip()
            parsed_plan = json.loads(raw_text)
            if isinstance(parsed_plan, list) and len(parsed_plan) > 0 and "tool" in parsed_plan[0]:
                plan = parsed_plan
        except Exception as llm_err:
            logger.warning(f"Excel AI fallback planning error: {llm_err}")

    if not plan:
        return {
            "success": False,
            "error": f"Could not determine structured Excel operation for: '{req.instruction}'. Try specifying the column or operation (e.g. 'sum goals where goals > 30', 'filter players with goals > 30', 'highlight goals > 30').",
            "plan": [],
            "results": [],
            "context": context,
        }

    # 4. Execute each planned tool step
    results = []
    overall_success = True
    for step in plan:
        tool_name = step.get("tool")
        params = dict(step.get("parameters") or step.get("args") or {})
        if "hwnd" not in params and req.hwnd:
            params["hwnd"] = req.hwnd
        if "workbook_name" not in params and req.workbook_name:
            params["workbook_name"] = req.workbook_name

        try:
            tool_res = tool_registry.execute(tool_name, params)
            results.append({
                "step_id": step.get("step_id"),
                "tool": tool_name,
                "success": tool_res.success,
                "data": tool_res.data,
                "error": tool_res.error,
            })
            if not tool_res.success:
                overall_success = False
                break
        except Exception as ex:
            overall_success = False
            results.append({
                "step_id": step.get("step_id"),
                "tool": tool_name,
                "success": False,
                "error": str(ex),
            })
            break

    # 5. Visual Language Model (VLM) validation and self-healing loop
    vlm_validation = None
    replan_applied = False
    if overall_success and plan and results:
        try:
            from backend.agent.tools.excel_copilot.validator import (
                validate_excel_execution_with_vlm,
                self_heal_excel_operation,
            )
            vlm_validation = await validate_excel_execution_with_vlm(
                goal=req.instruction,
                step=plan[0],
                tool_result=results[0],
                hwnd=req.hwnd,
                context=context,
            )

            # If VLM detects execution error or calculation defect, initiate self-healing
            if not vlm_validation.get("passed", True) and vlm_validation.get("needs_replan"):
                logger.info(f"[Excel VLM Validation] Defect detected: {vlm_validation.get('observation')}. Triggering self-healing...")
                heal_ok, replan_steps, final_vlm = await self_heal_excel_operation(
                    goal=req.instruction,
                    failed_step=plan[0],
                    vlm_diagnosis=vlm_validation,
                    hwnd=req.hwnd,
                    workbook_name=req.workbook_name,
                    context=context,
                )
                if heal_ok and replan_steps:
                    plan = replan_steps
                    replan_applied = True
                    vlm_validation = final_vlm
        except Exception as vlm_err:
            logger.warning(f"VLM post-execution validation error: {vlm_err}")

    # 6. Refresh context after mutation
    updated_context = acquire_deep_excel_context(workbook_name=req.workbook_name, hwnd=req.hwnd)
    try:
        target_manager.refresh_current_context()
    except Exception:
        pass

    last_res = results[-1] if results else {}
    base_msg = (
        last_res.get("data", {}).get("message", "Operation completed successfully.")
        if last_res.get("success")
        else (last_res.get("error", "Execution failed") if results else "No operations executed.")
    )

    if vlm_validation:
        obs = vlm_validation.get("observation", "")
        if replan_applied:
            msg = f"✓ Self-healed & verified by VLM: {obs}"
        elif vlm_validation.get("passed", True):
            msg = f"✓ Verified by VLM: {obs or base_msg}"
        else:
            msg = f"⚠️ VLM Notice: {obs or base_msg}"
    else:
        msg = base_msg

    return {
        "success": overall_success,
        "plan": plan,
        "results": results,
        "updated_context": updated_context,
        "message": msg,
        "vlm_validation": vlm_validation,
        "replan_applied": replan_applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WORD COPILOT FLOATING PILL ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

class WordExecuteRequest(BaseModel):
    instruction: str
    hwnd: Optional[int] = None
    document_name: Optional[str] = None


@router.get("/word/windows")
async def get_word_windows(copilot_hwnds: Optional[str] = None, electron_pid: Optional[int] = None):
    """Enumerate all open Word windows and their bounding rects on the desktop."""
    from backend.agent.tools.word_copilot.resolver import get_open_word_windows
    hwnds_set = set()
    if copilot_hwnds:
        for p in copilot_hwnds.split(","):
            p_str = p.strip().lstrip("-")
            if p_str.isdigit():
                hwnds_set.add(int(p.strip()))
    windows = get_open_word_windows(copilot_hwnds=hwnds_set, electron_pid=electron_pid)
    return {"windows": windows}


@router.get("/word/context")
async def get_word_context(hwnd: Optional[int] = None, document_name: Optional[str] = None):
    """Acquire real-time deep context for a specific Word window or document."""
    from backend.agent.tools.word_copilot.context import acquire_deep_word_context
    try:
        ctx = acquire_deep_word_context(document_name=document_name, hwnd=hwnd)
        return {"context": ctx}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Cannot acquire Word context: {e}")


@router.post("/word/execute")
async def execute_word_instruction(req: WordExecuteRequest):
    """Execute a natural-language document operation directly in the target Word document."""
    from backend.agent.tools.word_copilot.resolver import resolve_word_target
    from backend.agent.tools.word_copilot.context import acquire_deep_word_context
    from backend.agent.tools.word_copilot.planner import build_word_copilot_plan
    from backend.agent.tools.registry import tool_registry

    # 1. Resolve exact target
    try:
        word_app, doc, win = resolve_word_target(
            document_name=req.document_name,
            hwnd=req.hwnd,
        )
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Cannot connect to Word target: {err}")

    # 2. Acquire real-time context
    active_target = {
        "application": "Word",
        "target_type": "word",
        "window_id": str(getattr(win, "Hwnd", req.hwnd or "")),
        "target_name": str(getattr(doc, "Name", req.document_name or "")),
        "file_path": str(getattr(doc, "FullName", "")),
    }
    context = acquire_deep_word_context(document_name=req.document_name, hwnd=req.hwnd)

    # 3. Compile plan
    plan = build_word_copilot_plan(req.instruction, active_target, context)

    if not plan:
        # Dynamic AI fallback planning
        try:
            import json
            import re
            from langchain_core.messages import HumanMessage
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch

            fallback_prompt = (
                f"You are NEXUS Word Copilot. Translate this document command into a 1-step JSON plan array.\n"
                f"Document: {context.get('document_name')}, Selection: '{context.get('selection', {}).get('text')}'\n"
                f"User Instruction: \"{req.instruction}\"\n\n"
                f"Available tools and valid operations:\n"
                f"- 'word_format_text': bold (bool), italic (bool), underline (bool|str), font_size (num), font_name (str), font_color (str), highlight_color (str), strikethrough (bool), case ('uppercase'|'lowercase'|'titlecase'), target_text (str)\n"
                f"- 'word_clipboard_op': operation in ['copy', 'cut', 'paste', 'duplicate'], target_text (str), paste_text (str), position in ['selection', 'end', 'start']\n"
                f"- 'word_find_replace': find_text (str), replace_with (str), replace_all (bool), match_case (bool)\n"
                f"- 'word_format_paragraph': alignment in ['left', 'center', 'right', 'justify'], line_spacing (num: 1.0, 1.5, 2.0), indent ('increase'|'decrease'|num), bullets ('bullet'|'number'|'none')\n"
                f"- 'word_insert': item_type in ['table', 'image', 'shape', 'hyperlink', 'header', 'footer', 'page_break'], rows (num), cols (num), headers (list), url (str), text (str), shape_type (str), path_or_url (str)\n\n"
                f"Output strictly a JSON list with one object: [{{\"title\": \"...\", \"description\": \"...\", \"tool\": \"...\", \"args\": {{...}}}}] without markdown fencing."
            )
            llm_res = await ainvoke_with_dynamic_switch([HumanMessage(content=fallback_prompt)], temperature=0.0)
            raw_text = getattr(llm_res, "content", str(llm_res)).strip()
            if "```" in raw_text:
                m_json = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
                if m_json:
                    raw_text = m_json.group(1).strip()
            parsed_plan = json.loads(raw_text)
            if isinstance(parsed_plan, list) and len(parsed_plan) > 0 and "tool" in parsed_plan[0]:
                plan = parsed_plan
        except Exception as llm_err:
            logger.warning(f"Word AI fallback planning error: {llm_err}")

    if not plan:
        return {
            "success": False,
            "error": f"Could not determine structured Word operation for: '{req.instruction}'. Try specifying formatting or content (e.g. 'make bold', 'center align', 'replace X with Y', 'insert table 3x3').",
            "plan": [],
            "results": [],
            "context": context,
        }

    # 4. Execute each planned tool step
    results = []
    overall_success = True
    for step in plan:
        tool_name = step.get("tool")
        params = dict(step.get("parameters") or step.get("args") or {})
        if "hwnd" not in params and req.hwnd:
            params["hwnd"] = req.hwnd
        if "document_name" not in params and req.document_name:
            params["document_name"] = req.document_name

        try:
            tool_obj = tool_registry.get(tool_name)
            if not tool_obj:
                raise ValueError(f"Tool '{tool_name}' not found.")
            tool_res = await tool_obj.execute(**params)
            results.append({
                "step_id": step.get("step_id"),
                "tool": tool_name,
                "success": tool_res.success,
                "output": tool_res.output,
                "error": tool_res.error,
                "metadata": tool_res.metadata,
            })
            if not tool_res.success:
                overall_success = False
                break
        except Exception as ex:
            overall_success = False
            results.append({
                "step_id": step.get("step_id"),
                "tool": tool_name,
                "success": False,
                "error": str(ex),
            })
            break

    # 5. Refresh context after mutation
    updated_context = acquire_deep_word_context(document_name=req.document_name, hwnd=req.hwnd)
    last_res = results[-1] if results else {}
    base_msg = (
        last_res.get("output", "Operation completed successfully in Word.")
        if last_res.get("success")
        else (last_res.get("error", "Execution failed") if results else "No operations executed.")
    )

    return {
        "success": overall_success,
        "plan": plan,
        "results": results,
        "updated_context": updated_context,
        "message": base_msg,
    }


