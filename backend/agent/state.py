"""NEXUS Agent State — the single source of truth through the LangGraph."""
from __future__ import annotations
from typing import Any, Optional
from typing_extensions import TypedDict


class PlanStep(TypedDict):
    id: str
    title: str
    description: str
    tool: str          # "read_file" | "write_file" | "run_command" | "search_files" | "ai_response"
    args: dict
    risk_level: str    # RiskLevel value
    status: str        # "pending" | "running" | "completed" | "failed" | "skipped"
    result: Optional[str]
    error: Optional[str]


class NexusState(TypedDict):
    # Input
    task_id: str
    user_id: Optional[str]
    user_name: Optional[str]
    user_input: str
    messages: list[dict]

    # Intent & Goal
    intent: str        # "coding" | "file_op" | "shell" | "research" | "general" | "question"
    goal: str

    # Plan
    plan: list[PlanStep]
    current_step: int

    # Model routing
    selected_model: str
    model_history: list[dict]

    # Memory
    memory_context: list[str]

    # Tool execution
    tool_calls: list[dict]
    tool_results: list[dict]

    # Observations
    observations: list[str]
    screen_context: Optional[str]

    # Permission
    permission_required: bool
    permission_status: str   # "none" | "pending" | "approved" | "rejected"
    permission_items: list[str]  # Human-readable list of what needs approval

    # Execution
    execution_status: str    # "thinking" | "planning" | "executing" | "observing" | "completed" | "failed" | "paused"
    retry_count: int
    max_retries: int

    # Adaptive ReAct execution tracking
    execution_history: list[dict]   # [{action, args, result, url, success}, ...]
    goal_achieved: bool             # Set to True by executor when goal is done
    initial_dom: Optional[dict]     # Baseline DOM snapshot captured before automation starts
    max_iterations: int             # Hard cap to prevent infinite loops (default 20)
    verification_retries: int       # Number of post-execution DOM verification attempts in evaluator
    verification_details: Optional[dict]
    goal_check_count: int           # Number of goal_achieved claims validated by VLM in executor

    # Notifications
    notification_events: list[dict]

    # Target Context
    active_target: Optional[dict]
    active_context: Optional[dict]

    # Skill Learning & Replay
    skill_id: Optional[str]
    skill_version: Optional[int]
    is_replay_mode: Optional[bool]
    resolved_params: Optional[dict]
    reframing_count: Optional[int]

    # Output
    final_response: Optional[str]
    spoken_response: Optional[str]
    error: Optional[str]

    # Performance & Optimization Telemetry
    llm_calls_count: Optional[int]
    deterministic_actions_count: Optional[int]
    tokens_saved_estimate: Optional[int]
    fast_path_used: Optional[str]
    cache_hit: Optional[bool]
    start_time: Optional[float]
    latency_ms: Optional[float]
    validation_tier: Optional[str]
    validation_passed: Optional[bool]
    validation_reason: Optional[str]

