"""Reasoner node for deep reasoning and context analysis."""
from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage
from backend.agent.state import NexusState
from backend.agent.router.model_router import ainvoke_with_dynamic_switch
from backend.core.config import get_groq_api_key, get_gemma_api_key

REASONER_PROMPT = """You are NEXUS's Reasoning Engine.
Analyze the user's intent and goal to produce a concise technical execution strategy.
CRITICAL RULES:
- Do NOT answer the user's question, and do NOT perform or execute the task here.
- Do NOT output tables, markdown documents, code blocks, or full answers.
- Output ONLY 1 to 2 brief sentences (max 30 words) explaining how the agent will plan or resolve the request.
- Never use emojis."""


async def reasoner_node(state: NexusState) -> dict:
    goal = state.get("goal") or state.get("user_input", "")
    intent = state.get("intent", "general")
    task_id = state.get("task_id")

    # Fast-Path & Cache Bypass: Skip LLM call if plan is already formulated
    fast_path_used = state.get("fast_path_used")
    cache_hit = state.get("cache_hit")
    if fast_path_used or cache_hit or (state.get("plan") and len(state["plan"]) > 0):
        obs = state.get("observations", []).copy()
        tag = f"[{fast_path_used.upper()}]" if fast_path_used else "[CACHED]" if cache_hit else "[OPTIMIZED]"
        rationale = f"{tag} Direct execution strategy compiled for '{goal}'."
        obs.append(f"Rationale: {rationale}")
        return {
            "reasoning": rationale,
            "observations": obs,
            "execution_status": "planning",
        }

    # Fast Knowledge Bypass: Skip 6s Gemma streaming for direct Q&A
    if intent == "question":
        obs = state.get("observations", []).copy()
        rationale = f"Synthesizing direct knowledge response for '{goal}'."
        obs.append(f"Rationale: {rationale}")
        return {
            "reasoning": rationale,
            "observations": obs,
            "execution_status": "planning",
            "llm_calls_count": state.get("llm_calls_count", 0),
        }

    rationale = ""
    llm_used = False
    # Stream live thoughts using Gemma if key is available
    if get_gemma_api_key():
        try:
            from backend.agent.router.model_router import stream_gemma_with_thoughts
            user_msg = f"User Goal: {goal}\nIntent: {intent}\nProvide a concise 1-2 sentence execution plan."
            messages = [
                SystemMessage(content=REASONER_PROMPT),
                HumanMessage(content=user_msg),
            ]
            content, thought = await stream_gemma_with_thoughts(
                messages,
                task_id=task_id,
                timeout=6.0,
            )
            rationale = thought or content
            if rationale:
                llm_used = True
        except Exception:
            pass

    if not rationale:
        # High quality fallback rationale
        if intent == "web_automation":
            rationale = f"Navigating browser and preparing interactive workflow for '{goal}'..."
        elif intent == "shell":
            rationale = f"Analyzing system environment and preparing command for '{goal}'..."
        elif intent == "file_op":
            rationale = f"Inspecting filesystem workspace for '{goal}'..."
        else:
            rationale = f"Formulating optimal execution strategy for '{goal}'..."

    obs = state.get("observations", []).copy()
    obs.append(f"Rationale: {rationale}")
    cur_llm_calls = state.get("llm_calls_count", 0) + (1 if llm_used else 0)
    return {
        "reasoning": rationale,
        "observations": obs,
        "execution_status": "planning",
        "llm_calls_count": cur_llm_calls,
    }
