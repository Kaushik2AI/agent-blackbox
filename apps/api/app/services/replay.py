"""Replay orchestration (M6): validate -> enqueue -> worker resumes the checkpoint in an
isolated sandbox -> fork recorded as a NEW execution -> ground-truth verifier.

Never a "replay" in name only: the worker re-executes the remaining agent steps through
the real LangGraph harness. The source execution is only ever read.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_harness.interventions import (
    Intervention,
    InterventionError,
    ReplaceToolArguments,
    ReplaceToolResult,
    validate_intervention,
)
from agent_harness.llm import ModelUnavailable
from blackbox_sdk.exporters import MemoryExporter
from blackbox_sdk.integrations.agent_harness import replay_traced
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts import EventBatch, ReplayJobOut, ReplayRequest
from app.models import Checkpoint, Event, Execution, ReplayJob, ReplayStatus, Span
from app.services.checkpoints import load_and_check
from app.services.ingest import ingest_batch
from app.services.llm import build_llm, llm_hosts, llm_model_name, llm_status
from app.services.sandbox_guard import SandboxViolation, no_network

SANDBOX = {"type": "fixture_only", "network": "blocked", "tools": "allowlisted simulated tools"}


class ReplayRejected(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _recorded_arguments(session: Session, execution_id: uuid.UUID, span_id: str) -> Any:
    start = session.scalars(
        select(Event).where(
            Event.execution_id == execution_id,
            Event.span_id == span_id,
            Event.event_type == "tool_call_start",
        )
    ).first()
    if start is None:
        return None
    payload = start.payload_json or {}
    return payload.get("arguments") if payload.get("capture") == "content" else None


def resolve_intervention(
    session: Session, req: ReplayRequest, checkpoint: Checkpoint
) -> dict[str, Any] | None:
    """Turn the request into a fully explicit, contract-validated intervention record."""
    iv = req.intervention
    if iv is None:
        return None
    span = session.scalars(
        select(Span).where(
            Span.execution_id == req.source_execution_id, Span.span_id == iv.target_span_id
        )
    ).first()
    if span is None or span.kind != "tool":
        raise ReplayRejected([f"target span {iv.target_span_id} is not a tool call in this run"])
    attrs = span.attributes_json or {}
    call_index = attrs.get("blackbox.call_index")
    tool = attrs.get("gen_ai.tool.name")
    if not isinstance(call_index, int) or not isinstance(tool, str):
        raise ReplayRejected(["target span has no recorded call index / tool name"])
    if call_index < checkpoint.step_index:
        raise ReplayRejected(
            [
                f"target is tool call #{call_index}, which ran before the selected checkpoint "
                f"(#{checkpoint.step_index}); pick a checkpoint at or before the target call"
            ]
        )

    intervention: Intervention
    if iv.type == "replace_tool_argument":
        if iv.arguments is not None:
            arguments = copy.deepcopy(iv.arguments)
        else:
            if iv.field is None:
                raise ReplayRejected(["replace_tool_argument needs `arguments` or `field`"])
            recorded = _recorded_arguments(session, req.source_execution_id, iv.target_span_id)
            if not isinstance(recorded, dict):
                raise ReplayRejected(
                    [
                        "the original arguments were not captured (metadata-only run); "
                        "send the full `arguments` object instead of a field edit"
                    ]
                )
            arguments = {k: v for k, v in recorded.items() if k not in iv.remove_fields}
            arguments[iv.field] = iv.value
        intervention = ReplaceToolArguments(call_index=call_index, arguments=arguments)
    else:
        if iv.result is None:
            raise ReplayRejected(["replace_tool_result needs a `result` object"])
        intervention = ReplaceToolResult(call_index=call_index, result=copy.deepcopy(iv.result))
    try:
        validate_intervention(intervention, tool)
    except InterventionError as exc:
        raise ReplayRejected([str(exc)]) from None
    record: dict[str, Any] = {
        "type": intervention.type,
        "target_span_id": iv.target_span_id,
        "call_index": call_index,
        "tool": tool,
    }
    if isinstance(intervention, ReplaceToolArguments):
        record["arguments"] = intervention.arguments
        record["original_arguments"] = _recorded_arguments(
            session, req.source_execution_id, iv.target_span_id
        )
    else:
        record["result"] = intervention.result
    return record


def create_replay(session: Session, req: ReplayRequest) -> tuple[ReplayJob, bool]:
    """Validate and persist a replay job. Returns (job, created). Same idempotency key ->
    the same job, never a second fork."""
    key = (
        req.idempotency_key
        or hashlib.sha256(req.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()
    )
    existing = session.scalars(select(ReplayJob).where(ReplayJob.idempotency_key == key)).first()
    if existing is not None:
        return existing, False

    source = session.get(Execution, req.source_execution_id)
    if source is None:
        raise ReplayRejected([f"execution {req.source_execution_id} not found"])
    checkpoint = session.get(Checkpoint, req.checkpoint_id)
    if checkpoint is None or checkpoint.execution_id != source.id:
        raise ReplayRejected(["checkpoint does not belong to the source execution"])
    eligibility = load_and_check(checkpoint)
    if not eligibility.eligible or eligibility.document is None:
        raise ReplayRejected(["checkpoint is not replayable: " + "; ".join(eligibility.reasons)])
    model = str(eligibility.document.get("model_name", ""))
    if model.startswith("llm:"):
        # Real model: the suffix gets fresh inference, so the replay is
        # controlled_stochastic whatever the client asked for.
        if llm_status()[0] != "ready":
            raise ReplayRejected(
                ["this run used a live AI model, which is not available on this server right now"]
            )
        if model != llm_model_name():
            raise ReplayRejected(
                [f"this run used {model}; this server now runs {llm_model_name()}"]
            )
        mode = "controlled_stochastic"
    elif model.startswith("stub"):
        if req.mode == "controlled_stochastic":
            raise ReplayRejected(
                [
                    f"this run used the scripted agent ({model}), whose replays are "
                    "deterministic; request mode 'deterministic'"
                ]
            )
        mode = "deterministic"
    else:
        raise ReplayRejected([f"no replay support for model {model!r}"])
    record = resolve_intervention(session, req, checkpoint)

    job = ReplayJob(
        source_execution_id=source.id,
        checkpoint_id=checkpoint.id,
        fork_execution_id=uuid.uuid4(),
        intervention_json=record,
        sandbox_config_json={**SANDBOX, "freeze": req.freeze},
        replay_mode=mode,
        status=ReplayStatus.QUEUED,
        idempotency_key=key,
        attempts=0,
        result_json={},
    )
    session.add(job)
    session.commit()
    return job, True


def job_out(session: Session, job: ReplayJob) -> ReplayJobOut:
    checkpoint = session.get(Checkpoint, job.checkpoint_id)
    return ReplayJobOut(
        job_id=job.id,
        source_execution_id=job.source_execution_id,
        fork_execution_id=job.fork_execution_id,
        checkpoint_id=job.checkpoint_id,
        checkpoint_step_index=checkpoint.step_index if checkpoint else -1,
        status=job.status.value,
        replay_mode=job.replay_mode,
        replay_level="controlled_counterfactual" if job.intervention_json else "checkpoint_replay",
        intervention=job.intervention_json,
        sandbox=job.sandbox_config_json,
        attempts=job.attempts,
        error=job.error,
        result=job.result_json or {},
        requested_at=job.requested_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


# ------------------------------------------------------------------ worker side
def _to_intervention(record: dict[str, Any] | None) -> list[Intervention]:
    if not record:
        return []
    if record["type"] == "replace_tool_argument":
        return [
            ReplaceToolArguments(call_index=record["call_index"], arguments=record["arguments"])
        ]
    return [ReplaceToolResult(call_index=record["call_index"], result=record["result"])]


def execute_job(session: Session, job_id: uuid.UUID) -> ReplayJob:
    """Run one replay job. Safe to call again for the same job (worker retry/crash):
    a finished job is a no-op, and a half-written fork from a crashed attempt is removed
    and rebuilt under the same pre-assigned fork id."""
    job = session.get(ReplayJob, job_id, with_for_update=True)
    if job is None:
        raise LookupError(f"replay job {job_id} not found")
    if job.status in (ReplayStatus.SUCCEEDED, ReplayStatus.FAILED):
        session.rollback()
        return job
    job.status = ReplayStatus.RUNNING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    session.commit()

    incidents: list[str] = []
    try:
        checkpoint = session.get(Checkpoint, job.checkpoint_id)
        assert checkpoint is not None
        eligibility = load_and_check(checkpoint)
        if not eligibility.eligible or eligibility.document is None:
            raise ReplayRejected(
                ["checkpoint no longer replayable: " + "; ".join(eligibility.reasons)]
            )
        # Remove a partial fork left by a crashed earlier attempt. Only ever the job's own
        # pre-assigned fork, and only if it really is a child of this job's source.
        partial = session.get(Execution, job.fork_execution_id)
        if partial is not None:
            if partial.parent_execution_id != job.source_execution_id:
                raise ReplayRejected(["fork id collides with an unrelated execution"])
            session.execute(delete(Execution).where(Execution.id == partial.id))
            session.commit()

        exporter = MemoryExporter()
        live_model = job.replay_mode == "controlled_stochastic"
        model = build_llm() if live_model else None
        # Only the model API stays reachable for real-model replays; nothing for scripted.
        with no_network(incidents, allow=llm_hosts() if live_model else None):
            run, _ = replay_traced(
                eligibility.document,
                _to_intervention(job.intervention_json),
                exporter,
                fork_execution_id=str(job.fork_execution_id),
                parent_execution_id=str(job.source_execution_id),
                extra_attributes={
                    "replay": {
                        "job_id": str(job.id),
                        "checkpoint_id": str(job.checkpoint_id),
                        "checkpoint_step_index": checkpoint.step_index,
                        "intervention": job.intervention_json,
                        "replay_mode": job.replay_mode,
                        "sandbox": job.sandbox_config_json,
                    }
                },
                model=model,
            )
        settings = get_settings()
        for batch in exporter.batches:
            ingest_batch(
                session,
                EventBatch.model_validate(batch),
                max_payload_bytes=settings.max_event_payload_bytes,
            )
        job = session.get(ReplayJob, job_id, with_for_update=True) or job
        job.status = ReplayStatus.SUCCEEDED
        job.result_json = {
            "fork_verifier_passed": run.verifier.passed,
            "fork_verifier_reasons": run.verifier.reasons,
            "fork_termination": run.termination,
            "fork_tool_calls": run.tool_calls,
            "isolation_incidents": 0,
            "determinism": run.determinism,
        }
    except (SandboxViolation, ReplayRejected, Exception) as exc:  # noqa: BLE001
        session.rollback()
        job = session.get(ReplayJob, job_id, with_for_update=True) or job
        job.status = ReplayStatus.FAILED
        if incidents:
            job.error = f"isolation incident: {incidents[0]}"
        elif isinstance(exc, ModelUnavailable):
            job.error = f"The AI model is unavailable: {exc}"
        else:
            job.error = f"{type(exc).__name__}: {exc}"
        job.error = job.error[:2000]
        job.result_json = {"isolation_incidents": len(incidents)}
    job.finished_at = datetime.now(UTC)
    session.commit()
    return job


def fingerprint_rows(session: Session, execution_id: uuid.UUID) -> str:
    """SHA-256 over every domain row of an execution (used to prove immutability)."""
    ex = session.get(Execution, execution_id)
    assert ex is not None
    spans = session.scalars(
        select(Span).where(Span.execution_id == execution_id).order_by(Span.span_id)
    ).all()
    events = session.scalars(
        select(Event).where(Event.execution_id == execution_id).order_by(Event.sequence_no)
    ).all()
    checkpoints = session.scalars(
        select(Checkpoint)
        .where(Checkpoint.execution_id == execution_id)
        .order_by(Checkpoint.step_index)
    ).all()
    doc = {
        "execution": [
            ex.status.value,
            ex.task_id,
            str(ex.parent_execution_id),
            ex.attributes_json,
            str(ex.started_at),
            str(ex.ended_at),
        ],
        "spans": [
            [s.span_id, s.parent_span_id, s.status, s.start_ms, s.end_ms, s.attributes_json]
            for s in spans
        ],
        "events": [
            [str(e.id), e.sequence_no, e.event_type, e.status, e.payload_json, e.attributes_json]
            for e in events
        ],
        "checkpoints": [
            [str(c.id), c.step_index, c.state_hash, c.replay_capability] for c in checkpoints
        ],
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()
