"""
NEXUS In-Depth Real-World Test Matrix
====================================
Tests the full agent graph across:
1. Fast-Path Deterministic Operations (Apps, Folders, Math, System utilities)
2. Plan Cache Parameterized Workflows (Word, Excel creation)
3. General Knowledge & Informational Q&A (Messi, Quantum computing, Capitals)
4. Complex Automation & Multi-Step Tasks (File writing, Code, Search)
5. Conversational Greetings & Edge Cases ("hello", queries containing tricky keywords like 'about', 'hi')
"""
from __future__ import annotations

import asyncio
import time
import json
from typing import Any
import sys
import os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.agent.graph import build_nexus_graph
from backend.agent.state import NexusState


TEST_CASES = [
    # Category 1: Deterministic Fast-Path (0 LLM calls expected)
    {
        "category": "Deterministic Fast-Path",
        "query": "open chrome",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_not_contain": ["Groq API Key Not Configured", "Capabilities:"],
    },
    {
        "category": "Deterministic Fast-Path",
        "query": "open downloads folder",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_not_contain": ["Groq API Key Not Configured", "Capabilities:"],
    },
    {
        "category": "Deterministic Fast-Path",
        "query": "calculate (450 * 12) + 85",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_contain": ["5485"],
        "must_not_contain": ["Groq API Key Not Configured", "Capabilities:"],
    },
    {
        "category": "Deterministic Fast-Path",
        "query": "what time is it",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_not_contain": ["Groq API Key Not Configured", "Capabilities:"],
    },

    # Category 2: Plan Cache (0 LLM calls expected, structured templates)
    {
        "category": "Plan Cache (Parameterized)",
        "query": "create a word report on Autonomous AI Agents",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_not_contain": ["Groq API Key Not Configured"],
    },
    {
        "category": "Plan Cache (Parameterized)",
        "query": "create an excel spreadsheet for Monthly Expenses 2026",
        "expected_deterministic": True,
        "expected_llm_calls": 0,
        "must_not_contain": ["Groq API Key Not Configured"],
    },

    # Category 3: Knowledge & Informational Q&A (LLM expected, NEVER fallback pitch)
    {
        "category": "Informational Q&A",
        "query": "who is lionel messi",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_contain": ["Messi"],
        "must_not_contain": ["Groq API Key Not Configured", "Hello! I am NEXUS", "Capabilities:"],
    },
    {
        "category": "Informational Q&A",
        "query": "explain quantum computing in simple terms",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_contain": ["quantum", "qubit"],
        "must_not_contain": ["Groq API Key Not Configured", "Hello! I am NEXUS", "Capabilities:"],
    },
    {
        "category": "Informational Q&A",
        "query": "what is the capital of Japan and its population?",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_contain": ["Tokyo"],
        "must_not_contain": ["Groq API Key Not Configured", "Capabilities:"],
    },

    # Category 4: Conversational & Edge Cases (Keywords 'about', 'hi', 'hello')
    {
        "category": "Conversational Greeting",
        "query": "hello",
        "expected_deterministic": False,
        "must_contain": ["NEXUS"],
    },
    {
        "category": "Tricky Keyword: 'about'",
        "query": "tell me a fact about the solar system",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_not_contain": ["Hello! I am NEXUS", "Capabilities:", "Groq API Key Not Configured"],
    },
    {
        "category": "Tricky Keyword: 'hi' in word",
        "query": "give me a brief history of python programming",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_not_contain": ["Hello! I am NEXUS", "Capabilities:", "Groq API Key Not Configured"],
    },

    # Category 5: Multi-Step & Complex Automation Planning
    {
        "category": "Complex Multi-Step Task",
        "query": "search google for latest spacex starship launch and summarize the news",
        "expected_deterministic": False,
        "must_not_contain": ["Groq API Key Not Configured"],
    },
    {
        "category": "Complex Multi-Step Task",
        "query": "write a python script to calculate fibonacci numbers and save it to Desktop/fib.py",
        "expected_deterministic": False,
        "expected_min_llm_calls": 1,
        "must_not_contain": ["Groq API Key Not Configured", "Hello! I am NEXUS"],
    },
]


async def run_single_test(app: Any, test: dict[str, Any]) -> dict[str, Any]:
    task_id = f"test_{int(time.time() * 1000)}"
    query = test["query"]

    initial_st: NexusState = {
        "task_id": task_id,
        "user_id": "test_qa_suite",
        "user_input": query,
        "messages": [{"role": "user", "content": query}],
        "intent": "general",
        "goal": query,
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

    config = {"configurable": {"thread_id": task_id}}
    final_state: dict[str, Any] = {}
    plan_steps: list[dict] = []

    try:
        async for state in app.astream(initial_st, config=config):
            for node, update in state.items():
                if "plan" in update and update["plan"]:
                    plan_steps = update["plan"]
                final_state.update(update)

        latency_ms = final_state.get("latency_ms", 0)
        llm_calls = final_state.get("llm_calls_count", 0)
        fast_path = final_state.get("fast_path_used")
        cache_hit = final_state.get("cache_hit", False)
        final_res = str(final_state.get("final_response") or "")
        exec_status = final_state.get("execution_status")

        # Verifications
        errors = []
        if test.get("expected_deterministic"):
            if not (fast_path or cache_hit):
                errors.append(f"Expected deterministic, but fast_path={fast_path} and cache_hit={cache_hit}")
            if llm_calls != 0:
                errors.append(f"Expected 0 LLM calls, but got {llm_calls}")

        if "expected_min_llm_calls" in test:
            min_calls = test["expected_min_llm_calls"]
            if llm_calls < min_calls:
                errors.append(f"Expected at least {min_calls} LLM call(s), got {llm_calls}")

        for term in test.get("must_contain", []):
            if term.lower() not in final_res.lower():
                errors.append(f"Response missing expected term: '{term}'")

        for term in test.get("must_not_contain", []):
            if term.lower() in final_res.lower():
                errors.append(f"Response incorrectly contains forbidden term: '{term}'")

        if not final_res and not plan_steps:
            errors.append("No response and no plan generated")

        return {
            "query": query,
            "category": test["category"],
            "success": len(errors) == 0,
            "errors": errors,
            "latency_ms": latency_ms,
            "llm_calls": llm_calls,
            "fast_path": fast_path,
            "cache_hit": cache_hit,
            "plan_length": len(plan_steps),
            "response_preview": final_res[:180].replace("\n", " "),
        }
    except Exception as e:
        return {
            "query": query,
            "category": test["category"],
            "success": False,
            "errors": [f"Exception during execution: {str(e)}"],
            "latency_ms": 0,
            "llm_calls": 0,
            "fast_path": None,
            "cache_hit": False,
            "plan_length": 0,
            "response_preview": "EXCEPTION",
        }


async def main():
    print("=" * 80)
    print("NEXUS COMPREHENSIVE EXECUTION MATRIX TEST SUITE")
    print("=" * 80)

    app = build_nexus_graph()
    results = []

    for idx, test in enumerate(TEST_CASES, 1):
        print(f"\n[{idx}/{len(TEST_CASES)}] Testing [{test['category']}]: '{test['query']}'")
        res = await run_single_test(app, test)
        results.append(res)
        status_symbol = "PASS" if res["success"] else "FAIL"
        print(f"  Result: {status_symbol} | Latency: {res['latency_ms']}ms | LLM Calls: {res['llm_calls']} | FastPath: {res['fast_path']} | Cache: {res['cache_hit']}")
        print(f"  Preview: {res['response_preview']}")
        if not res["success"]:
            for err in res["errors"]:
                print(f"   ERROR: {err}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"Total Passed: {passed}/{total} ({round((passed/total)*100, 1)}%)")

    if passed == total:
        print("ALL TESTS PASSED CLEANLY! ZERO DUMMY FALLBACKS, 100% ACCURATE TELEMETRY.")
    else:
        print(f"{total - passed} test(s) failed. See details above.")


if __name__ == "__main__":
    asyncio.run(main())
