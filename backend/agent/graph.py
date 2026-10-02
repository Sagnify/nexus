"""LangGraph orchestration graph for NEXUS agent execution."""
from __future__ import annotations
from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from backend.agent.state import NexusState
from backend.agent.nodes.intent import intent_node
from backend.agent.nodes.reasoner import reasoner_node
from backend.agent.nodes.planner import planner_node
from backend.agent.nodes.permission_gate import permission_gate_node
from backend.agent.nodes.executor import executor_node
from backend.agent.nodes.observer import observer_node
from backend.agent.nodes.evaluator import evaluator_node


def route_permission_gate(state: NexusState) -> Literal["executor", "end"]:
    """If permission is required and not approved, pause execution."""
    if state.get("permission_required") and state.get("permission_status") != "approved":
        return "end"
    return "executor"


def route_evaluator(state: NexusState) -> Literal["permission_gate", "end"]:
    """If plan has more steps, loop back through permission gate, else end."""
    if state.get("execution_status") == "executing":
        return "permission_gate"
    return "end"


def build_nexus_graph():
    builder = StateGraph(NexusState)

    # Register nodes
    builder.add_node("intent", intent_node)
    builder.add_node("reasoner", reasoner_node)
    builder.add_node("planner", planner_node)
    builder.add_node("permission_gate", permission_gate_node)
    builder.add_node("executor", executor_node)
    builder.add_node("observer", observer_node)
    builder.add_node("evaluator", evaluator_node)

    # Define linear and conditional flow
    builder.add_edge(START, "intent")
    builder.add_edge("intent", "reasoner")
    builder.add_edge("reasoner", "planner")
    builder.add_edge("planner", "permission_gate")

    builder.add_conditional_edges(
        "permission_gate",
        route_permission_gate,
        {
            "executor": "executor",
            "end": END,
        }
    )

    builder.add_edge("executor", "observer")
    builder.add_edge("observer", "evaluator")

    builder.add_conditional_edges(
        "evaluator",
        route_evaluator,
        {
            "permission_gate": "permission_gate",
            "end": END,
        }
    )

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


nexus_graph = build_nexus_graph()
