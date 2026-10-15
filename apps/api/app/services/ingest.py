"""Idempotent ingestion of SDK batches.

Guarantees (each covered by tests/test_ingest.py):
  * re-sending a batch creates no new rows (events dedupe on event_id, spans on span_id);
  * batches may arrive in any order: a span's parent may arrive later, an end-of-span
    update may arrive after the span start, and a terminal execution status is never
    overwritten by a late non-terminal one;
  * every payload and attribute map is redacted, then size-limited, before it is stored;
  * the whole batch commits or nothing does.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.contracts import EventBatch, IngestResult
from app.models import (
    Agent,
    AgentVersion,
    Artifact,
    Event,
    Execution,
    ExecutionStatus,
    Project,
    Span,
)
from app.redaction import Redactor

TERMINAL = {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.ABORTED}


class IngestConflict(Exception):
    """The batch contradicts what is already stored (e.g. execution moved project)."""


def _get_or_create(session: Session, model: Any, lookup: dict[str, Any], **extra: Any) -> Any:
    stmt = pg_insert(model).values(**lookup, **extra).on_conflict_do_nothing()
    session.execute(stmt)
    return session.scalars(select(model).filter_by(**lookup)).one()


class _Limiter:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.truncated = 0

    def __call__(self, obj: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(obj, sort_keys=True, default=str).encode()
        if len(raw) <= self.max_bytes:
            return obj
        self.truncated += 1
        return {
            "_truncated": True,
            "original_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def ingest_batch(session: Session, batch: EventBatch, *, max_payload_bytes: int) -> IngestResult:
    redact = Redactor()
    limit = _Limiter(max_payload_bytes)
    res, ex = batch.resource, batch.execution

    project = _get_or_create(session, Project, {"name": res.project}, owner_id="local-dev")
    agent = _get_or_create(session, Agent, {"project_id": project.id, "name": res.agent})
    version = _get_or_create(
        session,
        AgentVersion,
        {
            "agent_id": agent.id,
            "git_sha": res.agent_version.git_sha,
            "config_hash": res.agent_version.config_hash,
        },
        model_name=res.agent_version.model_name,
    )

    # ---------------------------------------------------------------- execution
    execution = session.get(Execution, ex.execution_id, with_for_update=True)
    attrs = limit(redact({**ex.attributes, "sdk": res.sdk.model_dump()}))
    if execution is None:
        execution = Execution(
            id=ex.execution_id,
            project_id=project.id,
            agent_version_id=version.id,
            parent_execution_id=ex.parent_execution_id,
            task_id=ex.task_id,
            status=ex.status or ExecutionStatus.RUNNING,
            started_at=ex.started_at,
            ended_at=ex.ended_at,
            attributes_json=attrs,
        )
        session.add(execution)
        session.flush()
    else:
        if execution.project_id != project.id or execution.agent_version_id != version.id:
            raise IngestConflict(
                f"execution {ex.execution_id} already belongs to a different project/agent version"
            )
        if ex.status is not None and not (
            execution.status in TERMINAL and ex.status not in TERMINAL
        ):
            execution.status = ex.status
        if ex.started_at and (execution.started_at is None or ex.started_at < execution.started_at):
            execution.started_at = ex.started_at
        if ex.ended_at:
            execution.ended_at = ex.ended_at
        execution.attributes_json = {**execution.attributes_json, **attrs}

    # ---------------------------------------------------------------- spans
    existing = {
        s.span_id: s for s in session.scalars(select(Span).where(Span.execution_id == execution.id))
    }
    spans_new = 0
    for sp in batch.spans:
        span_attrs = limit(redact(sp.attributes))
        current = existing.get(sp.span_id)
        if current is None:
            current = Span(
                execution_id=execution.id,
                trace_id=sp.trace_id,
                span_id=sp.span_id,
                parent_span_id=sp.parent_span_id,
                kind=sp.kind,
                name=sp.name,
                status=sp.status,
                start_ms=sp.start_ms,
                end_ms=sp.end_ms,
                attributes_json=span_attrs,
            )
            session.add(current)
            existing[sp.span_id] = current
            spans_new += 1
            continue
        # Merge a later/earlier view of the same span without losing information.
        current.start_ms = min(current.start_ms, sp.start_ms)
        if sp.end_ms is not None:
            current.end_ms = sp.end_ms
        if sp.status != "unset":
            current.status = sp.status
        if sp.parent_span_id and not current.parent_span_id:
            current.parent_span_id = sp.parent_span_id
        current.attributes_json = {**current.attributes_json, **span_attrs}

    # ---------------------------------------------------------------- events
    rows = []
    for ev in batch.events:
        if ev.execution_id is not None and ev.execution_id != execution.id:
            raise IngestConflict(f"event {ev.event_id} belongs to execution {ev.execution_id}")
        rows.append(
            {
                "id": ev.event_id,
                "execution_id": execution.id,
                "span_id": ev.span_id,
                "sequence_no": ev.sequence_no,
                "event_type": ev.event_type,
                "timestamp": ev.timestamp,
                "operation": ev.operation,
                "tool_name": ev.tool_name,
                "status": ev.status,
                "attributes_json": limit(redact(ev.attributes)),
                "payload_json": limit(redact(ev.payload)),
                "dedupe_key": str(ev.event_id),
            }
        )
    events_new = 0
    if rows:
        inserted = session.execute(
            pg_insert(Event).values(rows).on_conflict_do_nothing().returning(Event.id)
        )
        events_new = len(inserted.all())

    # ---------------------------------------------------------------- artifacts
    artifacts_new = 0
    for art in batch.artifacts:
        result = session.execute(
            pg_insert(Artifact)
            .values(
                id=uuid.uuid4(),
                project_id=project.id,
                execution_id=execution.id,
                **art.model_dump(),
            )
            .on_conflict_do_nothing()
            .returning(Artifact.id)
        )
        artifacts_new += len(result.all())

    session.flush()
    _refresh_derived(session, execution)
    session.commit()
    return IngestResult(
        execution_id=execution.id,
        spans_received=len(batch.spans),
        spans_new=spans_new,
        events_received=len(batch.events),
        events_new=events_new,
        events_duplicate=len(batch.events) - events_new,
        artifacts_new=artifacts_new,
        redactions=redact.count,
        payloads_truncated=limit.truncated,
    )


def _refresh_derived(session: Session, execution: Execution) -> None:
    """Recompute summary numbers from the STORED events, so list views never depend on
    what a client claims about itself."""
    tool_ends = session.execute(
        select(Event.payload_json, Event.status)
        .where(Event.execution_id == execution.id, Event.event_type == "tool_call_end")
        .order_by(Event.sequence_no)
    ).all()
    error_codes: list[str] = []
    for payload, status in tool_ends:
        code = payload.get("error_code") if status == "error" else None
        if code and code not in error_codes:
            error_codes.append(code)
    llm_calls = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.execution_id == execution.id, Event.event_type == "llm_call_end")
    )
    execution.attributes_json = {
        **execution.attributes_json,
        "derived": {
            "tool_calls": len(tool_ends),
            "tool_errors": sum(1 for _, s in tool_ends if s == "error"),
            "error_codes": error_codes,
            "llm_calls": llm_calls or 0,
        },
    }
