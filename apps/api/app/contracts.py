"""Ingest contract v1.0 (see docs/data-model.md §2). Unknown schema versions are rejected."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ExecutionStatus

SUPPORTED_SCHEMA_VERSIONS = ("1.0",)
HEX16 = r"^[0-9a-f]{16}$"
HEX32 = r"^[0-9a-f]{32}$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentVersionIn(_In):
    git_sha: str = Field(min_length=1, max_length=64)
    config_hash: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=200)


class SdkIn(_In):
    name: str = Field(max_length=100)
    version: str = Field(max_length=50)


class ResourceIn(_In):
    project: str = Field(min_length=1, max_length=200)
    agent: str = Field(min_length=1, max_length=200)
    agent_version: AgentVersionIn
    sdk: SdkIn


class ExecutionIn(_In):
    execution_id: uuid.UUID
    task_id: str = Field(min_length=1, max_length=200)
    parent_execution_id: uuid.UUID | None = None
    status: ExecutionStatus | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class SpanIn(_In):
    trace_id: str = Field(pattern=HEX32)
    span_id: str = Field(pattern=HEX16)
    parent_span_id: str | None = Field(default=None, pattern=HEX16)
    kind: Literal["agent", "llm", "tool", "retrieval", "chain"]
    name: str = Field(min_length=1, max_length=200)
    status: Literal["unset", "ok", "error"] = "unset"
    start_ms: int = Field(ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EventIn(_In):
    schema_version: str | None = None  # tolerated per event; the batch version is authoritative
    event_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    trace_id: str | None = Field(default=None, pattern=HEX32)
    span_id: str | None = Field(default=None, pattern=HEX16)
    parent_span_id: str | None = Field(default=None, pattern=HEX16)
    sequence_no: int = Field(ge=0)
    timestamp: datetime
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    operation: str | None = Field(default=None, max_length=64)
    tool_name: str | None = Field(default=None, max_length=100)
    status: Literal["ok", "error"] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class ArtifactIn(_In):
    uri: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    type: str = Field(max_length=64)
    byte_size: int | None = Field(default=None, ge=0)
    capture_policy: Literal["metadata_only", "content"] = "metadata_only"


class CheckpointIn(_In):
    checkpoint_id: uuid.UUID
    step_index: int = Field(ge=0)
    node_id: str = Field(min_length=1, max_length=64)
    target_span_id: str | None = Field(default=None, pattern=HEX16)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Full pre-step state; present only when the run was recorded with content capture.
    state: dict[str, Any] | None = None


class EventBatch(_In):
    schema_version: str
    resource: ResourceIn
    execution: ExecutionIn
    spans: list[SpanIn] = Field(default_factory=list, max_length=5000)
    events: list[EventIn] = Field(default_factory=list, max_length=10000)
    artifacts: list[ArtifactIn] = Field(default_factory=list, max_length=100)
    checkpoints: list[CheckpointIn] = Field(default_factory=list, max_length=1000)

    @field_validator("schema_version")
    @classmethod
    def _known_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported schema_version {v!r}; this server accepts "
                f"{', '.join(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return v


class IngestResult(BaseModel):
    execution_id: uuid.UUID
    spans_received: int
    spans_new: int
    events_received: int
    events_new: int
    events_duplicate: int
    artifacts_new: int
    redactions: int
    payloads_truncated: int
    checkpoints_new: int = 0
    checkpoints_replayable: int = 0
    findings: int = 0


# ------------------------------------------------------------------ replay (M6)
class InterventionIn(_In):
    """One explicit change. replace_tool_argument: give the full `arguments` object, or a
    single `field`/`value` edit (optionally removing fields) applied to the recorded
    arguments. replace_tool_result: give the full `result` object."""

    type: Literal["replace_tool_argument", "replace_tool_result"]
    target_span_id: str = Field(pattern=HEX16)
    arguments: dict[str, Any] | None = None
    field: str | None = Field(default=None, max_length=100)
    value: Any = None
    remove_fields: list[str] = Field(default_factory=list, max_length=20)
    result: dict[str, Any] | None = None


FreezeItem = Literal["task_input", "tool_fixtures", "agent_version", "model_settings"]


def _default_freeze() -> list[FreezeItem]:
    return ["task_input", "tool_fixtures", "agent_version"]


class ReplayRequest(_In):
    source_execution_id: uuid.UUID
    checkpoint_id: uuid.UUID
    mode: Literal["deterministic", "controlled_stochastic"] = "deterministic"
    sandbox: Literal["fixture_only"] = "fixture_only"
    intervention: InterventionIn | None = None  # None = plain checkpoint replay (level 2)
    freeze: list[FreezeItem] = Field(default_factory=_default_freeze)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


class ReplayJobOut(BaseModel):
    job_id: uuid.UUID
    source_execution_id: uuid.UUID
    fork_execution_id: uuid.UUID
    checkpoint_id: uuid.UUID
    checkpoint_step_index: int
    status: str
    replay_mode: str
    replay_level: Literal["checkpoint_replay", "controlled_counterfactual"]
    intervention: dict[str, Any] | None
    sandbox: dict[str, Any]
    attempts: int
    error: str | None
    result: dict[str, Any]
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
