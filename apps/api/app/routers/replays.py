"""Findings (M5), checkpoints and replays (M6), comparison (M7)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts import ReplayJobOut, ReplayRequest
from app.db import get_session
from app.jobs import enqueue_replay
from app.models import (
    AnalysisFinding,
    Checkpoint,
    Event,
    Execution,
    Project,
    ReplayJob,
    ReplayStatus,
    Span,
)
from app.services.checkpoints import load_and_check
from app.services.comparison import build_comparison
from app.services.replay import ReplayRejected, create_replay, job_out

router = APIRouter(prefix="/api/v1", tags=["analysis & replay"])
SessionDep = Annotated[Session, Depends(get_session)]


def _execution(session: Session, execution_id: uuid.UUID) -> Execution:
    ex = session.get(Execution, execution_id)
    if ex is None:
        raise HTTPException(404, f"execution {execution_id} not found")
    return ex


# ------------------------------------------------------------------ findings (M5)
class FindingOut(BaseModel):
    id: uuid.UUID
    category: str
    severity: str
    title: str
    explanation: str
    evidence_event_ids: list[str]
    evidence_span_ids: list[str]
    caveats: list[str]
    detector: str
    detector_version: str
    kind: str


class FindingsOut(BaseModel):
    execution_id: uuid.UUID
    findings: list[FindingOut]
    note: str


@router.get("/executions/{execution_id}/findings", response_model=FindingsOut)
def get_findings(execution_id: uuid.UUID, session: SessionDep) -> FindingsOut:
    ex = _execution(session, execution_id)
    allowed = get_settings().findings_allowed_projects
    project = session.get(Project, ex.project_id)
    if "*" not in allowed and (project is None or project.name not in allowed):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "findings for this project are not allowed")
    rows = session.scalars(
        select(AnalysisFinding).where(AnalysisFinding.execution_id == execution_id)
    ).all()
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return FindingsOut(
        execution_id=execution_id,
        findings=sorted(
            (
                FindingOut(
                    id=f.id,
                    category=f.category,
                    severity=f.severity,
                    title=f.title,
                    explanation=f.explanation,
                    evidence_event_ids=f.evidence_event_ids,
                    evidence_span_ids=f.evidence_span_ids,
                    caveats=f.caveats or [],
                    detector=f.detector,
                    detector_version=f.detector_version,
                    kind=f.kind,
                )
                for f in rows
            ),
            key=lambda f: order.get(f.severity, 9),
        ),
        note=(
            "Verified findings come from deterministic detectors and cite the events they "
            "are based on. They describe what happened, not a proven root cause."
        ),
    )


# ------------------------------------------------------------------ checkpoints (M6)
class CheckpointOut(BaseModel):
    checkpoint_id: uuid.UUID
    step_index: int
    node_id: str
    target_span_id: str | None
    tool_name: str | None
    recorded_arguments: Any
    replay_capability: str
    eligible: bool
    reasons: list[str]


@router.get("/executions/{execution_id}/checkpoints", response_model=list[CheckpointOut])
def get_checkpoints(execution_id: uuid.UUID, session: SessionDep) -> list[CheckpointOut]:
    _execution(session, execution_id)
    spans = {
        s.span_id: s for s in session.scalars(select(Span).where(Span.execution_id == execution_id))
    }
    starts = {
        e.span_id: e
        for e in session.scalars(
            select(Event).where(
                Event.execution_id == execution_id, Event.event_type == "tool_call_start"
            )
        )
    }
    out = []
    for cp in session.scalars(
        select(Checkpoint)
        .where(Checkpoint.execution_id == execution_id)
        .order_by(Checkpoint.step_index)
    ):
        span = spans.get(cp.target_span_id or "")
        start = starts.get(cp.target_span_id)
        payload = start.payload_json if start else {}
        check = load_and_check(cp)
        out.append(
            CheckpointOut(
                checkpoint_id=cp.id,
                step_index=cp.step_index,
                node_id=cp.node_id,
                target_span_id=cp.target_span_id,
                tool_name=(span.attributes_json or {}).get("gen_ai.tool.name") if span else None,
                recorded_arguments=payload.get("arguments")
                if payload.get("capture") == "content"
                else None,
                replay_capability=cp.replay_capability,
                eligible=check.eligible,
                reasons=check.reasons,
            )
        )
    return out


# ------------------------------------------------------------------ replays (M6/M7)
@router.post(
    "/replays",
    response_model=ReplayJobOut,
    status_code=202,
    responses={200: {"model": ReplayJobOut}, 422: {}},
)
def post_replay(req: ReplayRequest, response: Response, session: SessionDep) -> ReplayJobOut:
    try:
        job, created = create_replay(session, req)
    except ReplayRejected as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"reasons": exc.reasons}
        ) from None
    if created:
        enqueue_replay(str(job.id))
    else:
        response.status_code = status.HTTP_200_OK  # same idempotency key: existing job
    return job_out(session, job)


@router.get("/replays/{job_id}", response_model=ReplayJobOut)
def get_replay(job_id: uuid.UUID, session: SessionDep) -> ReplayJobOut:
    job = session.get(ReplayJob, job_id)
    if job is None:
        raise HTTPException(404, f"replay {job_id} not found")
    return job_out(session, job)


@router.get("/executions/{execution_id}/replays", response_model=list[ReplayJobOut])
def list_replays(execution_id: uuid.UUID, session: SessionDep) -> list[ReplayJobOut]:
    _execution(session, execution_id)
    jobs = session.scalars(
        select(ReplayJob)
        .where(ReplayJob.source_execution_id == execution_id)
        .order_by(ReplayJob.requested_at.desc())
    ).all()
    return [job_out(session, j) for j in jobs]


@router.get("/replays/{job_id}/comparison")
def get_comparison(job_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    job = session.get(ReplayJob, job_id)
    if job is None:
        raise HTTPException(404, f"replay {job_id} not found")
    if job.status != ReplayStatus.SUCCEEDED:
        raise HTTPException(409, f"replay is {job.status.value}; comparison needs a finished fork")
    return build_comparison(session, job)
