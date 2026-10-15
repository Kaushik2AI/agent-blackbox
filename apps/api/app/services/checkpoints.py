"""Checkpoint storage, integrity and replay eligibility (M6).

A checkpoint's state is written to the artifact store only if (1) its SHA-256 matches the
hash the client declared, and (2) it contains nothing secret-shaped. Replay eligibility is
re-checked from disk every time: the file must still exist and still hash to the value in
the database, and the code/fixture it was taken with must still be installed.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_harness import __version__ as harness_version
from agent_harness.fixtures import load_fixture
from agent_harness.runner import CHECKPOINT_SCHEMA, checkpoint_sha256
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts import CheckpointIn
from app.models import Artifact, Checkpoint
from app.redaction import Redactor

AVAILABLE = "available"


def _root() -> Path:
    return Path(get_settings().artifact_dir)


def store_checkpoint(
    session: Session, execution_id: uuid.UUID, project_id: uuid.UUID, cp: CheckpointIn
) -> Checkpoint:
    uri: str | None = None
    if cp.state is None:
        capability = "metadata_only"
    elif checkpoint_sha256(cp.state) != cp.state_sha256:
        capability = "rejected_hash_mismatch"
    else:
        scan = Redactor()
        scan(cp.state)
        if scan.count:
            capability = "rejected_secrets"
        else:
            capability = AVAILABLE
            uri = f"checkpoints/{execution_id}/{cp.checkpoint_id}.json"
            _atomic_write(_root() / uri, json.dumps(cp.state, sort_keys=True))
            session.add(
                Artifact(
                    project_id=project_id,
                    execution_id=execution_id,
                    uri=f"artifact://{uri}",
                    sha256=cp.state_sha256,
                    type="checkpoint_state",
                    byte_size=(_root() / uri).stat().st_size,
                    capture_policy="content",
                )
            )
    row = Checkpoint(
        id=cp.checkpoint_id,
        execution_id=execution_id,
        step_index=cp.step_index,
        node_id=cp.node_id,
        target_span_id=cp.target_span_id,
        state_artifact_uri=uri,
        state_hash=cp.state_sha256,
        replay_capability=capability,
    )
    session.add(row)
    return row


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class Eligibility:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    document: dict[str, Any] | None = None


def load_and_check(checkpoint: Checkpoint) -> Eligibility:
    """Integrity + compatibility check, from scratch, every time."""
    if checkpoint.replay_capability != AVAILABLE:
        explain = {
            "metadata_only": "run was recorded metadata-only, so its state was not captured",
            "rejected_hash_mismatch": "state did not match its declared SHA-256 at ingest",
            "rejected_secrets": "state contained secret-shaped data and was not stored",
        }
        return Eligibility(
            False, [explain.get(checkpoint.replay_capability, checkpoint.replay_capability)]
        )
    path = _root() / str(checkpoint.state_artifact_uri)
    if not path.is_file():
        return Eligibility(False, ["checkpoint state file is missing from the artifact store"])
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint_sha256(document) != checkpoint.state_hash:
        return Eligibility(False, ["checkpoint state hash mismatch: the stored file changed"])
    reasons = []
    if document.get("schema") != CHECKPOINT_SCHEMA:
        reasons.append(f"unsupported checkpoint schema {document.get('schema')!r}")
    if document.get("harness_version") != harness_version:
        reasons.append(
            f"taken with agent harness {document.get('harness_version')}, "
            f"installed {harness_version}"
        )
    try:
        fixture = load_fixture(str(document.get("fixture_id")))
        if fixture.content_hash != document.get("fixture_sha256"):
            reasons.append("fixture content changed since the checkpoint was taken")
    except KeyError:
        reasons.append(f"fixture {document.get('fixture_id')!r} is not installed")
    return Eligibility(not reasons, reasons, document if not reasons else None)
