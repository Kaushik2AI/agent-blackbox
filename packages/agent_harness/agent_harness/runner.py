"""Run one fixture end to end: fresh sandbox -> agent graph -> ground-truth verifier."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel

from agent_harness import __version__
from agent_harness.fixtures import Termination, load_fixture
from agent_harness.graph import EventSink, build_graph, initial_state
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


def run_fixture(
    fixture_id: str,
    model: Model | None = None,
    on_event: EventSink | None = None,
) -> RunResult:
    """on_event receives every lifecycle event as it happens (the BlackBox SDK hooks in
    here); it must not raise."""
    fixture = load_fixture(fixture_id)
    model = model or StubModel(fixture.model)
    sandbox = Sandbox.from_fixture(fixture.world, fixture.faults)
    events: list[LocalEvent] = []

    def emit(event_type: str, data: dict[str, Any]) -> None:
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

    execution_id = str(uuid.uuid4())
    emit("agent_start", {"execution_id": execution_id, "fixture_id": fixture.fixture_id})
    started = time.perf_counter()
    graph = build_graph(model, sandbox, emit)
    final = graph.invoke(
        initial_state(fixture.task.model_dump(), fixture.budget.max_tool_calls),
        {"recursion_limit": 4 * fixture.budget.max_tool_calls + 10},
    )
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
    )
