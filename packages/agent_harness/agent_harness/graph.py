"""LangGraph state machine for the support agent.

    START -> model --(tool call, budget left)--> tool -> model -> ... -> END
                  \\-(finish / budget exhausted)-------------------------> END

State is plain JSON-serialisable data. Before every tool call the tool node emits a
PRE-STEP "checkpoint" event carrying a deep copy of the graph state and the sandbox, which
is everything needed to resume (M6). A resumed run starts with `pending` already set, so
the entry router goes straight to the tool node and re-executes the suffix for real.
The sandbox and the model are the environment, never stored in state.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_harness.interventions import Intervention, ReplaceToolArguments, ReplaceToolResult
from agent_harness.model import Finish, Model, ToolCall
from agent_harness.sandbox import Sandbox
from agent_harness.tools import ToolError, execute_tool

# Called for every lifecycle event; the M3 SDK plugs in here. Signature: (type, data).
EventSink = Callable[[str, dict[str, Any]], None]


class AgentState(TypedDict):
    task: dict[str, Any]
    observations: dict[str, Any]
    history: list[dict[str, Any]]
    pending: dict[str, Any] | None
    tool_calls: int
    model_turns: int
    max_tool_calls: int
    termination: str | None


def initial_state(task: dict[str, Any], max_tool_calls: int) -> AgentState:
    return AgentState(
        task=task,
        observations={},
        history=[],
        pending=None,
        tool_calls=0,
        model_turns=0,
        max_tool_calls=max_tool_calls,
        termination=None,
    )


def _observe(obs: dict[str, Any], tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    if tool == "lookup_order":
        obs["order"] = result
    elif tool == "lookup_inventory":
        obs["inventory"] = result
    elif tool == "get_policy":
        obs.setdefault("policies", {})[args["policy_key"]] = result
    elif tool == "draft_response":
        obs["draft_id"] = result["draft_id"]
    elif tool == "submit_resolution":
        obs["resolution_id"] = result["resolution_id"]


def build_graph(
    model: Model,
    sandbox: Sandbox,
    emit: EventSink,
    interventions: dict[int, Intervention] | None = None,
) -> CompiledStateGraph[Any]:
    interventions = interventions or {}

    def model_node(state: AgentState) -> dict[str, Any]:
        action = model.next_action(dict(state))
        turns = state["model_turns"] + 1
        # Real-model adapters expose details of the last decision (note, token usage,
        # latency); the scripted stub has none.
        info: dict[str, Any] = dict(getattr(model, "last_call", None) or {})
        note = str(info.get("note") or "")
        if isinstance(action, Finish):
            emit(
                "model_decision",
                {"model": model.name, "action": "finish", "reason": action.reason, **info},
            )
            return {"pending": None, "termination": action.reason, "model_turns": turns}
        assert isinstance(action, ToolCall)
        emit(
            "model_decision",
            {
                "model": model.name,
                "action": "tool_call",
                "tool": action.tool,
                "args": action.args,
                **info,
            },
        )
        if state["tool_calls"] >= state["max_tool_calls"]:
            emit("budget_exhausted", {"max_tool_calls": state["max_tool_calls"]})
            return {"pending": None, "termination": "budget_exhausted", "model_turns": turns}
        pending: dict[str, Any] = {"tool": action.tool, "args": action.args}
        if note:
            pending["note"] = note
        return {"pending": pending, "model_turns": turns}

    def tool_node(state: AgentState) -> dict[str, Any]:
        call = state["pending"]
        assert call is not None
        index = state["tool_calls"]
        # PRE-STEP checkpoint: the exact state before this call ran.
        emit(
            "checkpoint",
            {
                "call_index": index,
                "node_id": "tool",
                "graph_state": copy.deepcopy(dict(state)),
                "sandbox": sandbox.snapshot(),
            },
        )
        intervention = interventions.get(index)
        args = call["args"]
        if isinstance(intervention, ReplaceToolArguments):
            args = copy.deepcopy(intervention.arguments)
            emit(
                "intervention_applied",
                {
                    "call_index": index,
                    "type": intervention.type,
                    "tool": call["tool"],
                    "before": call["args"],
                    "after": args,
                },
            )
        emit("tool_call_start", {"call_index": index, "tool": call["tool"], "args": args})
        start = time.perf_counter()
        step: dict[str, Any] = {"call_index": index, "tool": call["tool"], "args": args}
        if call.get("note"):
            step["note"] = call["note"]
        if intervention is not None:
            step["intervention"] = intervention.type
        observations = {**state["observations"]}
        if "policies" in observations:
            observations["policies"] = dict(observations["policies"])
        try:
            if isinstance(intervention, ReplaceToolResult):
                result = copy.deepcopy(intervention.result)
                emit(
                    "intervention_applied",
                    {
                        "call_index": index,
                        "type": intervention.type,
                        "tool": call["tool"],
                        "after": result,
                    },
                )
            else:
                result = execute_tool(sandbox, call["tool"], args)
            step.update(ok=True, result=result, error_code=None)
            _observe(observations, call["tool"], args, result)
        except ToolError as err:
            step.update(ok=False, result=None, error_code=err.code.value, error=err.message)
        emit("tool_call_end", {**step, "elapsed_ms": round((time.perf_counter() - start) * 1e3, 3)})
        return {
            "history": [*state["history"], step],
            "observations": observations,
            "pending": None,
            "tool_calls": index + 1,
        }

    def route(state: AgentState) -> str:
        return "tool" if state["pending"] is not None else END

    def entry(state: AgentState) -> str:
        # Fresh runs start at the model; resumed runs (pending already set) at the tool.
        return "tool" if state["pending"] is not None else "model"

    builder = StateGraph(AgentState)
    builder.add_node("model", model_node)
    builder.add_node("tool", tool_node)
    builder.add_conditional_edges(START, entry, ["model", "tool"])
    builder.add_conditional_edges("model", route, ["tool", END])
    builder.add_edge("tool", "model")
    return builder.compile()
