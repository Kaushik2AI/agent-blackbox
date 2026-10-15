"""Recorder: builds OpenTelemetry-compatible spans and events for one execution and turns
them into contract-v1.0 batches for POST /api/v1/events:batch.

Data model follows OTel: 32-hex trace_id, 16-hex span_id, parent links, start/end in
epoch milliseconds, attributes using GenAI semantic-convention names where one exists
(gen_ai.operation.name, gen_ai.request.model, gen_ai.tool.name, gen_ai.agent.name).
OTLP export is not implemented; the platform's own JSON contract is the wire format.

Content capture is OFF by default: payloads record only the *shape* of arguments and
results (field names and types/lengths). With capture_content=True values are kept after
redaction. Either way secrets are redacted before anything leaves the process.
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from blackbox_sdk.redaction import Redactor

SpanKind = Literal["agent", "llm", "tool", "retrieval", "chain"]
SpanStatus = Literal["unset", "ok", "error"]


@dataclass(frozen=True)
class Resource:
    project: str
    agent: str
    git_sha: str
    config_hash: str
    model_name: str
    sdk_name: str = "blackbox-sdk"
    sdk_version: str = "0.3.0"


@dataclass
class SpanHandle:
    span_id: str
    name: str
    kind: SpanKind
    parent_span_id: str | None
    start_ms: int
    end_ms: int | None = None
    status: SpanStatus = "unset"
    attributes: dict[str, Any] = field(default_factory=dict)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def shape_of(value: Any) -> Any:
    """Metadata-only view of a value: keeps structure and field names, drops content."""
    if isinstance(value, dict):
        return {str(k): shape_of(v) for k, v in value.items()}
    if isinstance(value, list):
        return f"<list len={len(value)}>"
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, int | float):
        return f"<{type(value).__name__}>"
    if isinstance(value, str):
        return f"<str len={len(value)}>"
    if value is None:
        return None
    return f"<{type(value).__name__}>"


class Recorder:
    def __init__(
        self,
        *,
        resource: Resource,
        execution_id: str,
        task_id: str,
        capture_content: bool = False,
        parent_execution_id: str | None = None,
    ) -> None:
        self.resource = resource
        self.execution_id = execution_id
        self.task_id = task_id
        self.capture_content = capture_content
        self.parent_execution_id = parent_execution_id
        self.trace_id = secrets.token_hex(16)
        self.spans: dict[str, SpanHandle] = {}
        self.events: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self.started_at = datetime.now(UTC)
        self.ended_at: datetime | None = None
        self.status: str | None = "running"
        self.execution_attributes: dict[str, Any] = {}
        self._seq = 0
        self._redactor = Redactor()

    # ------------------------------------------------------------- content policy
    @property
    def capture_policy(self) -> str:
        return "content" if self.capture_content else "metadata_only"

    def capture(self, value: Any) -> Any:
        """Value for an event payload. Payloads are redacted in add_event either way."""
        return value if self.capture_content else shape_of(value)

    def redact(self, value: Any) -> Any:
        return self._redactor(value)

    @property
    def redactions(self) -> int:
        return self._redactor.count

    # ------------------------------------------------------------- spans & events
    def start_span(
        self,
        name: str,
        kind: SpanKind,
        *,
        parent: SpanHandle | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanHandle:
        span = SpanHandle(
            span_id=secrets.token_hex(8),
            name=name,
            kind=kind,
            parent_span_id=parent.span_id if parent else None,
            start_ms=_now_ms(),
            attributes=self.redact(attributes or {}),
        )
        self.spans[span.span_id] = span
        return span

    def end_span(self, span: SpanHandle, status: SpanStatus = "ok") -> None:
        span.end_ms = _now_ms()
        span.status = status

    def add_event(
        self,
        span: SpanHandle | None,
        event_type: str,
        *,
        status: Literal["ok", "error"] | None = None,
        operation: str | None = None,
        tool_name: str | None = None,
        attributes: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "span_id": span.span_id if span else None,
            "parent_span_id": span.parent_span_id if span else None,
            "sequence_no": self._seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "operation": operation,
            "tool_name": tool_name,
            "status": status,
            "attributes": self.redact(attributes or {}),
            "payload": {"capture": self.capture_policy, **self.redact(payload or {})},
        }
        self._seq += 1
        self.events.append(event)
        return event

    def add_artifact(self, uri: str, sha256: str, type_: str, byte_size: int | None = None) -> None:
        self.artifacts.append(
            {
                "uri": uri,
                "sha256": sha256,
                "type": type_,
                "byte_size": byte_size,
                "capture_policy": "metadata_only",
            }
        )

    def finish(
        self,
        status: Literal["succeeded", "failed", "aborted"],
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.ended_at = datetime.now(UTC)
        self.execution_attributes.update(self.redact(attributes or {}))

    # ------------------------------------------------------------- batches
    def to_batches(self, max_events: int = 1000) -> list[dict[str, Any]]:
        """Contract-v1.0 batches. Spans and artifacts ride in the first batch; events are
        chunked. Every batch is independently idempotent, so retries are always safe."""
        res = self.resource
        header = {
            "schema_version": "1.0",
            "resource": {
                "project": res.project,
                "agent": res.agent,
                "agent_version": {
                    "git_sha": res.git_sha,
                    "config_hash": res.config_hash,
                    "model_name": res.model_name,
                },
                "sdk": {"name": res.sdk_name, "version": res.sdk_version},
            },
            "execution": {
                "execution_id": self.execution_id,
                "task_id": self.task_id,
                "parent_execution_id": self.parent_execution_id,
                "status": self.status,
                "started_at": self.started_at.isoformat(),
                "ended_at": self.ended_at.isoformat() if self.ended_at else None,
                "attributes": self.execution_attributes,
            },
        }
        spans = [
            {
                "trace_id": self.trace_id,
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "kind": s.kind,
                "name": s.name,
                "status": s.status,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "attributes": s.attributes,
            }
            for s in self.spans.values()
        ]
        chunks = [self.events[i : i + max_events] for i in range(0, len(self.events), max_events)]
        chunks = chunks or [[]]
        return [
            {
                **header,
                "spans": spans if i == 0 else [],
                "events": chunk,
                "artifacts": self.artifacts if i == 0 else [],
            }
            for i, chunk in enumerate(chunks)
        ]
