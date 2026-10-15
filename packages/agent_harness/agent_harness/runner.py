"""Run one fixture end to end: fresh sandbox -> agent graph -> ground-truth verifier."""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel

from agent_harness import __version__
from agent_harness.fixtures import Fixture, Termination, load_fixture
from agent_harness.graph import AgentState, EventSink, build_graph, initial_state
from agent_harness.interventions import Intervention, InterventionError
from agent_harness.model import Model, StubModel
from agent_harness.sandbox import Sandbox
from agent_harness.tools import TOOL_CONTRACT_VERSION
from agent_harness.verifier import VerifierResult, verify


class LocalEvent(BaseModel):
    sequence_no: int
    type: str
    timestamp: str
    data: dict[str, Any]


class RunResult(BaseModel):
    execution_id: str
    fixture_id: str
    fixture_version: str
    fixture_sha256: str
    agent_version: str
    tool_contract_version: str
    model_name: str
    determinism: str
    termination: Termination
    tool_calls: int
    model_turns: int
    history: list[dict[str, Any]]
    sandbox_effects: list[dict[str, Any]]
    verifier: VerifierResult
    elapsed_ms: float
    events: list[LocalEvent]
    resumed_from_call_index: int | None = None
    interventions: list[dict[str, Any]] = []

    @property
    def error_codes(self) -> list[str]:
        """Distinct tool error codes in the order they first occurred."""
        seen: list[str] = []
        for step in self.history:
            code = step.get("error_code")
            if code and code not in seen:
                seen.append(code)
        return seen

    def outcome_signature(self) -> dict[str, Any]:
        """Everything that must be identical across repeated deterministic runs."""
        return {
            "termination": self.termination,
            "tool_calls": self.tool_calls,
            "history": [{k: v for k, v in s.items() if k != "elapsed_ms"} for s in self.history],
            "sandbox_effects": self.sandbox_effects,
            "verifier": self.verifier.model_dump(),
        }


CHECKPOINT_SCHEMA = "agent-harness-checkpoint/1"


class CheckpointMismatch(ValueError):
    """The checkpoint cannot be resumed with the code/fixture installed here."""


def checkpoint_sha256(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def run_fixture(
    fixture_id: str,
    model: Model | None = None,
    on_event: EventSink | None = None,
) -> RunResult:
    """Run a fixture from scratch. on_event receives every lifecycle event as it happens
    (the BlackBox SDK hooks in here); it must not raise. "checkpoint" events carry a full,
    self-describing checkpoint document (see run_from_checkpoint)."""
    fixture = load_fixture(fixture_id)
    model = model or StubModel(fixture.model)
    sandbox = Sandbox.from_fixture(fixture.world, fixture.faults)
    state = initial_state(fixture.task.model_dump(), fixture.budget.max_tool_calls)
    return _execute(fixture, model, sandbox, state, on_event, {}, None)


def run_from_checkpoint(
    document: dict[str, Any],
    interventions: list[Intervention] | None = None,
    on_event: EventSink | None = None,
    model: Model | None = None,
) -> RunResult:
    """Resume a run from a PRE-STEP checkpoint in a brand-new execution: restore the graph
    state and an independent copy of the sandbox, apply the (validated) interventions,
    and re-execute every remaining step for real. The source run is not touched."""
    if document.get("schema") != CHECKPOINT_SCHEMA:
        raise CheckpointMismatch(f"unsupported checkpoint schema {document.get('schema')!r}")
    fixture = load_fixture(document["fixture_id"])
    problems = []
    if document["fixture_version"] != fixture.fixture_version:
        problems.append(
            f"fixture version {document['fixture_version']} != {fixture.fixture_version}"
        )
    if document["fixture_sha256"] != fixture.content_hash:
        problems.append("fixture content changed since the checkpoint was taken")
    if document["harness_version"] != __version__:
        problems.append(f"agent harness {document['harness_version']} != installed {__version__}")
    if problems:
        raise CheckpointMismatch("; ".join(problems))

    state = copy.deepcopy(document["graph_state"])
    start_index = int(document["call_index"])
    if state.get("pending") is None or state.get("tool_calls") != start_index:
        raise CheckpointMismatch("checkpoint is not a pre-step state")
    by_index: dict[int, Intervention] = {}
    for item in interventions or []:
        if item.call_index < start_index:
            raise InterventionError(
                f"intervention targets call {item.call_index}, which ran before the "
                f"checkpoint (call {start_index}); it would have no effect"
            )
        if item.call_index in by_index:
            raise InterventionError(f"more than one intervention for call {item.call_index}")
        by_index[item.call_index] = item
    model = model or StubModel(fixture.model)
    sandbox = Sandbox.restore(document["sandbox"])
    return _execute(
        fixture, model, sandbox, cast(AgentState, state), on_event, by_index, start_index
    )


def _execute(
    fixture: Fixture,
    model: Model,
    sandbox: Sandbox,
    state: AgentState,
    on_event: EventSink | None,
    interventions: dict[int, Intervention],
    resumed_from: int | None,
) -> RunResult:
    events: list[LocalEvent] = []
    execution_id = str(uuid.uuid4())

    def emit(event_type: str, data: dict[str, Any]) -> None:
        if event_type == "checkpoint":
            document = {
                "schema": CHECKPOINT_SCHEMA,
                "harness_version": __version__,
                "tool_contract_version": TOOL_CONTRACT_VERSION,
                "fixture_id": fixture.fixture_id,
                "fixture_version": fixture.fixture_version,
                "fixture_sha256": fixture.content_hash,
                "model_name": model.name,
                **data,
            }
            data = {
                "document": document,
                "sha256": checkpoint_sha256(document),
                "call_index": data["call_index"],
                "node_id": data["node_id"],
            }
        events.append(
            LocalEvent(
                sequence_no=len(events),
                type=event_type,
                timestamp=datetime.now(UTC).isoformat(),
                data=data,
            )
        )
        if on_event is not None:
            on_event(event_type, data)

    emit(
        "agent_start",
        {
            "execution_id": execution_id,
            "fixture_id": fixture.fixture_id,
            "resumed_from_call_index": resumed_from,
        },
    )
    started = time.perf_counter()
    graph = build_graph(model, sandbox, emit, interventions)
    final = graph.invoke(state, {"recursion_limit": 4 * fixture.budget.max_tool_calls + 10})
    elapsed = (time.perf_counter() - started) * 1000
    termination = cast(Termination, final["termination"] or "error")
    result = verify(fixture, sandbox, final["tool_calls"])
    emit("agent_end", {"termination": termination, "verifier_passed": result.passed})

    return RunResult(
        execution_id=execution_id,
        fixture_id=fixture.fixture_id,
        fixture_version=fixture.fixture_version,
        fixture_sha256=fixture.content_hash,
        agent_version=__version__,
        tool_contract_version=TOOL_CONTRACT_VERSION,
        model_name=model.name,
        determinism="deterministic" if isinstance(model, StubModel) else "controlled_stochastic",
        termination=termination,
        tool_calls=final["tool_calls"],
        model_turns=final["model_turns"],
        history=final["history"],
        sandbox_effects=[
            {"kind": e.kind, "effect_id": e.effect_id, "payload": e.payload}
            for e in sandbox.effects
        ],
        verifier=result,
        elapsed_ms=round(elapsed, 3),
        events=events,
        resumed_from_call_index=resumed_from,
        interventions=[
            {"type": i.type, "call_index": i.call_index} for i in interventions.values()
        ],
    )
