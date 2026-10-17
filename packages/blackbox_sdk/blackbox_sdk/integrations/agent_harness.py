"""Instrumentation for the demo agent harness (packages/agent_harness).

    from blackbox_sdk.exporters import HttpExporter
    from blackbox_sdk.integrations.agent_harness import run_traced
    run_traced("invalid_inventory_argument", HttpExporter("http://127.0.0.1:8000"))

Span tree for one run:
    invoke_agent support-agent            (kind=agent)
      ├─ chat stub-planner-v1             (kind=llm)   one per model decision
      ├─ execute_tool lookup_order        (kind=tool)  one per tool call
      ├─ chat stub-planner-v1
      ├─ execute_tool lookup_inventory    status=error, event payload error_code=SKU_REQUIRED
      └─ ...
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Protocol

from agent_harness import __version__ as harness_version
from agent_harness.fixtures import load_fixture
from agent_harness.freshness import REFERENCE_NOW
from agent_harness.graph import EventSink
from agent_harness.interventions import Intervention
from agent_harness.model import Model, StubModel
from agent_harness.runner import RunResult, run_fixture, run_from_checkpoint
from agent_harness.tools import TOOL_CONTRACT_VERSION

from blackbox_sdk.recorder import Recorder, Resource, SpanHandle

AGENT_NAME = "support-agent"
ERROR_TYPES = {
    "SKU_REQUIRED": "validation_error",
    "INVALID_ARGUMENT": "validation_error",
    "TIMEOUT": "timeout",
    "ORDER_NOT_FOUND": "not_found",
    "SKU_NOT_FOUND": "not_found",
    "POLICY_NOT_FOUND": "not_found",
    "UNKNOWN_TOOL": "forbidden_tool",
}


class Exporter(Protocol):
    def export(self, batch: dict[str, Any]) -> dict[str, Any]: ...


def git_sha() -> str:
    if sha := os.environ.get("BLACKBOX_GIT_SHA"):
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def harness_resource(model_name: str, project: str = "demo") -> Resource:
    config = {"harness": harness_version, "tools": TOOL_CONTRACT_VERSION, "model": model_name}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    from blackbox_sdk import __version__ as sdk_version

    return Resource(
        project=project,
        agent=AGENT_NAME,
        git_sha=git_sha(),
        config_hash=config_hash,
        model_name=model_name,
        sdk_version=sdk_version,
    )


class HarnessTracer:
    """EventSink for agent_harness.run_fixture that records spans and events."""

    def __init__(
        self,
        task_id: str,
        model_name: str,
        *,
        capture_content: bool = False,
        project: str = "demo",
        execution_id: str | None = None,
        parent_execution_id: str | None = None,
        extra_attributes: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = task_id
        self.model_name = model_name
        self.capture_content = capture_content
        self.project = project
        self.forced_execution_id = execution_id
        self.parent_execution_id = parent_execution_id
        self.extra_attributes = extra_attributes or {}
        self.recorder: Recorder | None = None
        self.root: SpanHandle | None = None
        self.open_tool: SpanHandle | None = None
        self.pending_checkpoint: dict[str, Any] | None = None
        self.tokens_in = 0
        self.tokens_out = 0

    def __call__(self, event_type: str, data: dict[str, Any]) -> None:
        handler = getattr(self, f"_on_{event_type}", None)
        if handler is not None:
            handler(data)

    # ------------------------------------------------------------- handlers
    def _on_agent_start(self, data: dict[str, Any]) -> None:
        self.recorder = Recorder(
            resource=harness_resource(self.model_name, self.project),
            # A replay worker pre-assigns the fork id so retries stay idempotent.
            execution_id=self.forced_execution_id or data["execution_id"],
            task_id=self.task_id,
            capture_content=self.capture_content,
            parent_execution_id=self.parent_execution_id,
        )
        self.root = self.recorder.start_span(
            f"invoke_agent {AGENT_NAME}",
            "agent",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": AGENT_NAME,
                "blackbox.fixture_id": data["fixture_id"],
            },
        )
        self.recorder.add_event(
            self.root,
            "agent_start",
            operation="invoke_agent",
            payload={"fixture_id": data["fixture_id"]},
        )
        resumed = data.get("resumed_from_call_index")
        if resumed is not None:
            self.root.attributes["blackbox.resumed_from_call_index"] = resumed
            self.recorder.add_event(
                self.root,
                "replay_start",
                operation="invoke_agent",
                payload={
                    "resumed_from_call_index": resumed,
                    "parent_execution_id": self.parent_execution_id,
                },
            )

    def _on_checkpoint(self, data: dict[str, Any]) -> None:
        rec, _ = self._require()
        # The tool span this checkpoint precedes does not exist yet; link it on start.
        self.pending_checkpoint = rec.add_checkpoint(
            step_index=data["call_index"],
            node_id=data["node_id"],
            state_sha256=data["sha256"],
            state=data["document"],
        )

    def _on_intervention_applied(self, data: dict[str, Any]) -> None:
        rec, root = self._require()
        payload = {
            "type": data["type"],
            "call_index": data["call_index"],
            "tool": data["tool"],
            "after": rec.capture(data.get("after")),
        }
        if "before" in data:
            payload["before"] = rec.capture(data["before"])
        rec.add_event(
            root,
            "intervention_applied",
            operation="replay",
            tool_name=data["tool"],
            payload=payload,
        )

    def _on_model_decision(self, data: dict[str, Any]) -> None:
        rec, root = self._require()
        span = rec.start_span(
            f"chat {data['model']}",
            "llm",
            parent=root,
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": data["model"],
                "blackbox.decision": data["action"],
            },
        )
        payload: dict[str, Any] = {"action": data["action"]}
        if data["action"] == "tool_call":
            payload.update(tool=data["tool"], arguments=rec.capture(data["args"]))
        else:
            payload["reason"] = data["reason"]
        if data.get("note"):
            # The model's own one-line explanation: content, so captured like arguments.
            payload["note"] = rec.capture(data["note"])
        if data.get("unparsed"):
            payload["unparsed"] = True
            if data.get("raw_preview"):
                payload["raw_preview"] = rec.capture(data["raw_preview"])
        usage = data.get("usage") or {}
        attributes: dict[str, Any] = {}
        if usage:
            attributes["gen_ai.usage.input_tokens"] = usage.get("input_tokens", 0)
            attributes["gen_ai.usage.output_tokens"] = usage.get("output_tokens", 0)
            span.attributes.update(attributes)
            self.tokens_in += int(usage.get("input_tokens", 0))
            self.tokens_out += int(usage.get("output_tokens", 0))
        if data.get("latency_ms") is not None:
            attributes["elapsed_ms"] = data["latency_ms"]
        rec.add_event(
            span,
            "llm_call_end",
            status="error" if data.get("unparsed") else "ok",
            operation="chat",
            attributes=attributes,
            payload=payload,
        )
        rec.end_span(span, "error" if data.get("unparsed") else "ok")

    def _on_budget_exhausted(self, data: dict[str, Any]) -> None:
        rec, root = self._require()
        rec.add_event(
            root,
            "budget_exhausted",
            status="error",
            attributes={"error_type": "budget_exhausted"},
            payload=dict(data),
        )

    def _on_tool_call_start(self, data: dict[str, Any]) -> None:
        rec, root = self._require()
        self.open_tool = rec.start_span(
            f"execute_tool {data['tool']}",
            "tool",
            parent=root,
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": data["tool"],
                "blackbox.call_index": data["call_index"],
            },
        )
        if self.pending_checkpoint is not None:
            self.pending_checkpoint["target_span_id"] = self.open_tool.span_id
            self.pending_checkpoint = None
        rec.add_event(
            self.open_tool,
            "tool_call_start",
            operation="execute_tool",
            tool_name=data["tool"],
            payload={
                "arguments": rec.capture(data["args"]),
                "identity": rec.identity(data["args"]),
            },
        )

    def _on_tool_call_end(self, data: dict[str, Any]) -> None:
        rec, _ = self._require()
        span = self.open_tool
        assert span is not None, "tool_call_end without tool_call_start"
        ok = bool(data["ok"])
        payload: dict[str, Any] = {
            "input_redacted": rec.capture(data["args"]),
            "identity": rec.identity(data["args"]),
        }
        attributes: dict[str, Any] = {
            "elapsed_ms": data.get("elapsed_ms"),
            "call_index": data["call_index"],
        }
        if data.get("intervention"):
            attributes["intervention"] = data["intervention"]
        if ok:
            payload["output"] = rec.capture(data["result"])
            payload["output_identity"] = rec.identity(data["result"])
            # Freshness of a retrieved snapshot is metadata, not a captured value: the
            # snapshot date and the logical "now" it was read at, so a detector can tell
            # the agent acted on stale data without the data itself being stored.
            result = data["result"]
            if isinstance(result, dict) and result.get("as_of"):
                attributes["data_as_of"] = result["as_of"]
                attributes["data_checked_at"] = REFERENCE_NOW
        else:
            payload["error_code"] = data["error_code"]
            payload["error_message"] = data.get("error")
            attributes["error_type"] = ERROR_TYPES.get(data["error_code"], "tool_error")
        rec.add_event(
            span,
            "tool_call_end",
            status="ok" if ok else "error",
            operation="execute_tool",
            tool_name=data["tool"],
            attributes=attributes,
            payload=payload,
        )
        rec.end_span(span, "ok" if ok else "error")
        self.open_tool = None

    def _on_agent_end(self, data: dict[str, Any]) -> None:
        rec, root = self._require()
        completed = data["termination"] == "completed"
        rec.add_event(
            root,
            "agent_end",
            status="ok" if completed else "error",
            operation="invoke_agent",
            payload=dict(data),
        )
        rec.end_span(root, "ok" if completed else "error")

    def _require(self) -> tuple[Recorder, SpanHandle]:
        if self.recorder is None or self.root is None:
            raise RuntimeError("event received before agent_start")
        return self.recorder, self.root

    # ------------------------------------------------------------- completion
    def finish(self, result: RunResult) -> Recorder:
        rec, _ = self._require()
        fixture = load_fixture(result.fixture_id)
        rec.add_artifact(
            f"fixture://{fixture.fixture_id}@{fixture.fixture_version}",
            fixture.content_hash,
            "fixture",
        )
        sandbox_state = json.dumps(result.sandbox_effects, sort_keys=True).encode()
        rec.add_artifact(
            f"sandbox-state://{result.execution_id}/final",
            hashlib.sha256(sandbox_state).hexdigest(),
            "sandbox_state",
            byte_size=len(sandbox_state),
        )
        rec.finish(
            "succeeded" if result.verifier.passed else "failed",
            {
                "termination": result.termination,
                "verifier": result.verifier.model_dump(),
                "fixture": {
                    "id": fixture.fixture_id,
                    "version": fixture.fixture_version,
                    "sha256": fixture.content_hash,
                },
                "determinism": result.determinism,
                "model_name": result.model_name,
                "agent_version": result.agent_version,
                "tool_contract_version": result.tool_contract_version,
                "capture_policy": rec.capture_policy,
                "resumed_from_call_index": result.resumed_from_call_index,
                **(
                    {
                        "usage": {
                            "input_tokens": self.tokens_in,
                            "output_tokens": self.tokens_out,
                            "total_tokens": self.tokens_in + self.tokens_out,
                        }
                    }
                    if self.tokens_in or self.tokens_out
                    else {}
                ),
                # Final sandbox content (for original-vs-fork state diffs) only when the
                # run was recorded with content capture.
                **({"final_sandbox": result.sandbox_effects} if self.capture_content else {}),
                **self.extra_attributes,
            },
        )
        return rec


def _tee(tracer: HarnessTracer, sink: EventSink | None) -> EventSink:
    if sink is None:
        return tracer

    def both(event_type: str, data: dict[str, Any]) -> None:
        tracer(event_type, data)
        try:
            sink(event_type, data)
        except Exception:  # noqa: BLE001, S110 - an observer must never break the run
            pass

    return both


def run_traced(
    fixture_id: str,
    exporter: Exporter,
    *,
    capture_content: bool = False,
    project: str = "demo",
    model: Model | None = None,
    message: str | None = None,
    sink: EventSink | None = None,
    extra_attributes: dict[str, Any] | None = None,
) -> tuple[RunResult, list[dict[str, Any]]]:
    """Run one fixture with tracing; export its batches. Returns (run, ingest responses).
    `model` defaults to the fixture's scripted stub; `sink` also receives every harness
    event as it happens (used for live progress)."""
    fixture = load_fixture(fixture_id)
    model = model or StubModel(fixture.model)
    tracer = HarnessTracer(
        fixture_id,
        model.name,
        capture_content=capture_content,
        project=project,
        extra_attributes=extra_attributes,
    )
    result = run_fixture(fixture_id, model=model, on_event=_tee(tracer, sink), message=message)
    recorder = tracer.finish(result)
    responses = [exporter.export(batch) for batch in recorder.to_batches()]
    return result, responses


def replay_traced(
    document: dict[str, Any],
    interventions: list[Intervention],
    exporter: Exporter,
    *,
    fork_execution_id: str,
    parent_execution_id: str,
    extra_attributes: dict[str, Any],
    project: str = "demo",
    model: Model | None = None,
    sink: EventSink | None = None,
) -> tuple[RunResult, list[dict[str, Any]]]:
    """Resume a checkpoint as a NEW traced execution (a fork) and export its batches.
    The fork is always recorded with content capture so it can itself be replayed.
    `model` defaults to the scripted stub; pass the real-model adapter for LLM runs."""
    fixture = load_fixture(document["fixture_id"])
    model = model or StubModel(fixture.model)
    tracer = HarnessTracer(
        fixture.fixture_id,
        model.name,
        capture_content=True,
        project=project,
        execution_id=fork_execution_id,
        parent_execution_id=parent_execution_id,
        extra_attributes=extra_attributes,
    )
    result = run_from_checkpoint(document, interventions, on_event=_tee(tracer, sink), model=model)
    recorder = tracer.finish(result)
    responses = [exporter.export(batch) for batch in recorder.to_batches()]
    return result, responses
