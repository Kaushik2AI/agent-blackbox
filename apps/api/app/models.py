"""Domain schema.

M1: projects -> agents -> agent_versions, executions.
M3: spans, events, artifacts (written by the ingest API from SDK batches).
Checkpoints, replay_jobs, findings and evaluation tables arrive with the milestones that
write to them (M5, M6, M8) - see docs/data-model.md.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExecutionStatus(StrEnum):
    """Lifecycle states; transitions are documented in docs/architecture.md."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    owner_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_agents_project_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentVersion(Base):
    """Immutable build metadata. A changed config or git SHA is a new row."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "git_sha", "config_hash", name="uq_agent_versions_build"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    git_sha: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Execution(Base):
    """One agent run. Forks (M6) point at their source through parent_execution_id."""

    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_project_started", "project_id", "started_at"),
        CheckConstraint(
            "parent_execution_id IS NULL OR parent_execution_id <> id",
            name="ck_executions_not_own_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), index=True
    )
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        SAEnum(
            ExecutionStatus, name="execution_status", values_callable=lambda e: [m.value for m in e]
        ),
        default=ExecutionStatus.PENDING,
    )
    task_id: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Run summary reported by the SDK: termination, verifier result, fixture provenance...
    attributes_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Span(Base):
    """OpenTelemetry-style span. parent_span_id is deliberately NOT a foreign key: spans
    may arrive before their parent (out-of-order batches) and are linked when it lands."""

    __tablename__ = "spans"
    __table_args__ = (
        UniqueConstraint("execution_id", "span_id", name="uq_spans_execution_span"),
        Index("ix_spans_trace_span", "trace_id", "span_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str] = mapped_column(String(32))
    span_id: Mapped[str] = mapped_column(String(16))
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))  # agent | llm | tool
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))  # unset | ok | error
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Event(Base):
    """One recorded event. id == the client's event_id, which makes re-ingestion a no-op."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_execution_sequence", "execution_id", "sequence_no"),
        Index("ix_events_execution_timestamp", "execution_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    span_id: Mapped[str | None] = mapped_column(String(16))
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    operation: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(16))
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Artifact(Base):
    """Reference to content stored elsewhere, identified by SHA-256 (content not stored)."""

    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("execution_id", "uri", name="uq_artifacts_execution_uri"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    uri: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    capture_policy: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
