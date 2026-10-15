"""Read APIs for the dashboard (M4). Everything is computed from stored rows."""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
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

router = APIRouter(prefix="/api/v1", tags=["executions"])
SessionDep = Annotated[Session, Depends(get_session)]


# ------------------------------------------------------------------ response models
class AgentVersionOut(BaseModel):
    id: uuid.UUID
    agent: str
    git_sha: str
    config_hash: str
    model_name: str


class ExecutionSummary(BaseModel):
    id: uuid.UUID
    project: str
    task_id: str
    status: ExecutionStatus
    agent_version: AgentVersionOut
    parent_execution_id: uuid.UUID | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: float | None
    tool_calls: int
    error_codes: list[str]
    termination: str | None
    verifier_passed: bool | None


class ExecutionPage(BaseModel):
    items: list[ExecutionSummary]
    total: int
    limit: int
    offset: int


class ArtifactOut(BaseModel):
    uri: str
    sha256: str
    type: str
    byte_size: int | None
    capture_policy: str


class ExecutionDetail(ExecutionSummary):
    attributes: dict[str, Any]
    artifacts: list[ArtifactOut]
    span_count: int
    event_count: int


class SpanOut(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None
    kind: str
    name: str
    status: str
    start_ms: int
    end_ms: int | None
    duration_ms: int | None
    attributes: dict[str, Any]


class EventOut(BaseModel):
    event_id: uuid.UUID
    span_id: str | None
    sequence_no: int
    event_type: str
    timestamp: datetime
    operation: str | None
    tool_name: str | None
    status: str | None
    attributes: dict[str, Any]
    payload: dict[str, Any]


class Timeline(BaseModel):
    execution_id: uuid.UUID
    spans: list[SpanOut]
    events: list[EventOut]


class GraphNode(BaseModel):
    id: str
    kind: str
    name: str
    status: str
    order: int
    parent_span_id: str | None
    orphan: bool
    duration_ms: int | None
    tool_name: str | None
    error_code: str | None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["parent", "next"]


class Graph(BaseModel):
    execution_id: uuid.UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Overview(BaseModel):
    total: int
    succeeded: int
    failed: int
    other: int
    success_rate: float | None
    median_duration_ms: float | None
    failure_tags: dict[str, int]
    by_task: dict[str, dict[str, int]]
    total_tokens: int | None


# ------------------------------------------------------------------ helpers
def _summary(e: Execution, v: AgentVersion, agent: str, project: str) -> ExecutionSummary:
    attrs = e.attributes_json or {}
    derived = attrs.get("derived", {})
    verifier = attrs.get("verifier") or {}
    duration = (
        (e.ended_at - e.started_at).total_seconds() * 1000 if e.started_at and e.ended_at else None
    )
    return ExecutionSummary(
        id=e.id,
        project=project,
        task_id=e.task_id,
        status=e.status,
        agent_version=AgentVersionOut(
            id=v.id,
            agent=agent,
            git_sha=v.git_sha,
            config_hash=v.config_hash,
            model_name=v.model_name,
        ),
        parent_execution_id=e.parent_execution_id,
        started_at=e.started_at,
        ended_at=e.ended_at,
        duration_ms=round(duration, 3) if duration is not None else None,
        tool_calls=int(derived.get("tool_calls", 0)),
        error_codes=list(derived.get("error_codes", [])),
        termination=attrs.get("termination"),
        verifier_passed=verifier.get("passed") if isinstance(verifier, dict) else None,
    )


def _base_query() -> Any:
    return (
        select(Execution, AgentVersion, Agent.name, Project.name)
        .join(AgentVersion, Execution.agent_version_id == AgentVersion.id)
        .join(Agent, AgentVersion.agent_id == Agent.id)
        .join(Project, Execution.project_id == Project.id)
    )


def _get_execution(session: Session, execution_id: uuid.UUID) -> Any:
    row = session.execute(_base_query().where(Execution.id == execution_id)).first()
    if row is None:
        raise HTTPException(404, f"execution {execution_id} not found")
    return row


# ------------------------------------------------------------------ endpoints
@router.get("/agent-versions", response_model=list[AgentVersionOut])
def list_agent_versions(session: SessionDep) -> list[AgentVersionOut]:
    rows = session.execute(
        select(AgentVersion, Agent.name)
        .join(Agent, AgentVersion.agent_id == Agent.id)
        .order_by(AgentVersion.created_at.desc())
    ).all()
    return [
        AgentVersionOut(
            id=v.id, agent=a, git_sha=v.git_sha, config_hash=v.config_hash, model_name=v.model_name
        )
        for v, a in rows
    ]


@router.get("/executions", response_model=ExecutionPage)
def list_executions(
    session: SessionDep,
    status: ExecutionStatus | None = None,
    agent_version_id: uuid.UUID | None = None,
    task_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExecutionPage:
    query = _base_query()
    if status is not None:
        query = query.where(Execution.status == status)
    if agent_version_id is not None:
        query = query.where(Execution.agent_version_id == agent_version_id)
    if task_id:
        query = query.where(Execution.task_id == task_id)
    if since is not None:
        query = query.where(Execution.started_at >= since)
    if until is not None:
        query = query.where(Execution.started_at < until)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(Execution.started_at.desc().nulls_last(), Execution.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return ExecutionPage(
        items=[_summary(e, v, a, p) for e, v, a, p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetail)
def get_execution(execution_id: uuid.UUID, session: SessionDep) -> ExecutionDetail:
    e, v, a, p = _get_execution(session, execution_id)
    artifacts = session.scalars(select(Artifact).where(Artifact.execution_id == e.id)).all()
    span_count = session.scalar(select(func.count()).where(Span.execution_id == e.id)) or 0
    event_count = session.scalar(select(func.count()).where(Event.execution_id == e.id)) or 0
    return ExecutionDetail(
        **_summary(e, v, a, p).model_dump(),
        attributes=e.attributes_json or {},
        artifacts=[
            ArtifactOut(
                uri=x.uri,
                sha256=x.sha256,
                type=x.type,
                byte_size=x.byte_size,
                capture_policy=x.capture_policy,
            )
            for x in artifacts
        ],
        span_count=span_count,
        event_count=event_count,
    )


def _spans(session: Session, execution_id: uuid.UUID) -> list[Span]:
    """Spans in the order the agent executed them. Many spans start within the same
    millisecond, so the first event sequence number (monotonic per run) is the primary
    key; start time only orders spans that have no events."""
    rows = session.execute(
        select(Event.span_id, func.min(Event.sequence_no))
        .where(Event.execution_id == execution_id, Event.span_id.is_not(None))
        .group_by(Event.span_id)
    ).all()
    first_seq: dict[str, int] = {str(span_id): int(seq) for span_id, seq in rows}
    spans = session.scalars(select(Span).where(Span.execution_id == execution_id)).all()
    return sorted(
        spans,
        key=lambda s: (first_seq.get(s.span_id, float("inf")), s.start_ms, s.span_id),
    )


@router.get("/executions/{execution_id}/timeline", response_model=Timeline)
def get_timeline(execution_id: uuid.UUID, session: SessionDep) -> Timeline:
    _get_execution(session, execution_id)
    events = session.scalars(
        select(Event).where(Event.execution_id == execution_id).order_by(Event.sequence_no)
    ).all()
    return Timeline(
        execution_id=execution_id,
        spans=[
            SpanOut(
                span_id=s.span_id,
                trace_id=s.trace_id,
                parent_span_id=s.parent_span_id,
                kind=s.kind,
                name=s.name,
                status=s.status,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                duration_ms=(s.end_ms - s.start_ms) if s.end_ms is not None else None,
                attributes=s.attributes_json or {},
            )
            for s in _spans(session, execution_id)
        ],
        events=[
            EventOut(
                event_id=ev.id,
                span_id=ev.span_id,
                sequence_no=ev.sequence_no,
                event_type=ev.event_type,
                timestamp=ev.timestamp,
                operation=ev.operation,
                tool_name=ev.tool_name,
                status=ev.status,
                attributes=ev.attributes_json or {},
                payload=ev.payload_json or {},
            )
            for ev in events
        ],
    )


@router.get("/executions/{execution_id}/graph", response_model=Graph)
def get_graph(execution_id: uuid.UUID, session: SessionDep) -> Graph:
    """Nodes are spans. 'parent' edges follow the span tree; 'next' edges connect sibling
    steps in the order they started (the agent's control flow)."""
    _get_execution(session, execution_id)
    spans = _spans(session, execution_id)
    ids = {s.span_id for s in spans}
    error_by_span: dict[str, str] = {}
    for span_id, payload in session.execute(
        select(Event.span_id, Event.payload_json).where(
            Event.execution_id == execution_id, Event.status == "error"
        )
    ):
        if span_id and isinstance(payload, dict) and payload.get("error_code"):
            error_by_span.setdefault(span_id, payload["error_code"])

    nodes, edges = [], []
    children: dict[str | None, list[Span]] = {}
    for order, s in enumerate(spans):
        orphan = s.parent_span_id is not None and s.parent_span_id not in ids
        nodes.append(
            GraphNode(
                id=s.span_id,
                kind=s.kind,
                name=s.name,
                status=s.status,
                order=order,
                parent_span_id=s.parent_span_id,
                orphan=orphan,
                duration_ms=(s.end_ms - s.start_ms) if s.end_ms is not None else None,
                tool_name=(s.attributes_json or {}).get("gen_ai.tool.name"),
                error_code=error_by_span.get(s.span_id),
            )
        )
        if s.parent_span_id in ids:
            edges.append(
                GraphEdge(
                    id=f"p-{s.span_id}",
                    source=s.parent_span_id or "",
                    target=s.span_id,
                    kind="parent",
                )
            )
        children.setdefault(s.parent_span_id if s.parent_span_id in ids else None, []).append(s)
    for siblings in children.values():
        for a, b in zip(siblings, siblings[1:], strict=False):
            edges.append(
                GraphEdge(
                    id=f"n-{a.span_id}-{b.span_id}", source=a.span_id, target=b.span_id, kind="next"
                )
            )
    return Graph(execution_id=execution_id, nodes=nodes, edges=edges)


@router.get("/overview", response_model=Overview)
def overview(session: SessionDep, since: datetime | None = None) -> Overview:
    query = select(Execution)
    if since is not None:
        query = query.where(Execution.started_at >= since)
    executions = session.scalars(query).all()
    statuses = Counter(e.status for e in executions)
    tags: Counter[str] = Counter()
    by_task: dict[str, Counter[str]] = {}
    durations, tokens, saw_tokens = [], 0, False
    for e in executions:
        attrs = e.attributes_json or {}
        tags.update(attrs.get("derived", {}).get("error_codes", []))
        by_task.setdefault(e.task_id, Counter())[e.status.value] += 1
        if e.started_at and e.ended_at:
            durations.append((e.ended_at - e.started_at).total_seconds() * 1000)
        usage = attrs.get("usage") or {}
        if isinstance(usage, dict) and "total_tokens" in usage:
            saw_tokens = True
            tokens += int(usage["total_tokens"])
    done = statuses[ExecutionStatus.SUCCEEDED] + statuses[ExecutionStatus.FAILED]
    return Overview(
        total=len(executions),
        succeeded=statuses[ExecutionStatus.SUCCEEDED],
        failed=statuses[ExecutionStatus.FAILED],
        other=len(executions) - done,
        success_rate=round(statuses[ExecutionStatus.SUCCEEDED] / done, 4) if done else None,
        median_duration_ms=round(statistics.median(durations), 3) if durations else None,
        failure_tags=dict(tags.most_common()),
        by_task={k: dict(v) for k, v in sorted(by_task.items())},
        total_tokens=tokens if saw_tokens else None,
    )
