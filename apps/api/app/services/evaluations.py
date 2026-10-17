"""Benchmark results in the app (M8/M9): import a results folder, summarise it.

A results folder is what `python -m evaluation.benchmark run` writes (on a laptop or a
GPU batch job): runs.jsonl (one validated record per run) and, optionally, traces.jsonl
(the recorded runs). Import is idempotent: records dedupe on run_key, traces on event id.
Records containing anything secret-shaped are rejected, never stored.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from evaluation.metrics import summarize
from evaluation.report import to_csv
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import EventBatch
from app.models import EvaluationRun, Execution
from app.redaction import Redactor
from app.services.ingest import IngestConflict, ingest_batch


class RunRecordIn(BaseModel):
    """The fields every record must have; the rest is kept as-is."""

    model_config = ConfigDict(extra="allow")

    schema_: Literal["flightpath-eval-run/1"]
    run_key: str
    benchmark_version: str
    case_id: str
    family: str
    split: Literal["dev", "heldout"]
    arm: Literal["baseline", "no_change", "repair", "random"]
    repeat: int
    draw: int | None = None
    seed: int
    model_spec: str
    model_id: str
    model_revision: str | None = None
    agent_version: str
    passed: bool
    expected_findings: list[str]
    execution_id: str | None = None


def source_id(record: dict[str, Any]) -> str:
    key = "|".join(
        str(record.get(k)) for k in ("benchmark_version", "model_spec", "model_revision", "seed")
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class ImportReport:
    read: int = 0
    imported: int = 0
    duplicates: int = 0
    rejected: list[str] = field(default_factory=list)
    traces_ingested: int = 0
    traces_rejected: int = 0
    sources: set[str] = field(default_factory=set)


def _validate(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    data["schema_"] = data.pop("schema", None)
    RunRecordIn.model_validate(data)
    redactor = Redactor()
    redactor(raw)
    if redactor.count:
        raise ValueError("contains secret-shaped values")
    return raw


def import_folder(session: Session, folder: Path, *, max_payload_bytes: int) -> ImportReport:
    runs_path = folder / "runs.jsonl" if folder.is_dir() else folder
    if not runs_path.is_file():
        raise FileNotFoundError(f"{runs_path} not found")
    report = ImportReport()
    valid_keys: set[str] = set()
    for n, line in enumerate(runs_path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        report.read += 1
        try:
            record = _validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            report.rejected.append(f"line {n}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        src = source_id(record)
        report.sources.add(src)
        valid_keys.add(record["run_key"])
        stmt = (
            insert(EvaluationRun)
            .values(
                run_key=record["run_key"],
                source=src,
                benchmark_version=record["benchmark_version"],
                case_id=record["case_id"],
                family=record["family"],
                split=record["split"],
                arm=record["arm"],
                model_spec=record["model_spec"],
                model_id=record["model_id"],
                passed=bool(record["passed"]),
                execution_id=record.get("execution_id"),
                record_json=record,
            )
            .on_conflict_do_nothing(index_elements=["run_key"])
            .returning(EvaluationRun.id)
        )
        if session.execute(stmt).scalar_one_or_none() is not None:
            report.imported += 1
        else:
            report.duplicates += 1
    session.commit()

    traces = runs_path.parent / "traces.jsonl"
    if traces.is_file():
        for line in traces.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("run_key") not in valid_keys:
                report.traces_rejected += 1
                continue
            try:
                batch = EventBatch.model_validate(item["batch"])
                ingest_batch(session, batch, max_payload_bytes=max_payload_bytes)
                report.traces_ingested += 1
            except (ValidationError, IngestConflict, KeyError):
                session.rollback()
                report.traces_rejected += 1
    return report


# ------------------------------------------------------------------ read side
def _records(session: Session, source: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(EvaluationRun.record_json).where(EvaluationRun.source == source)
    ).all()
    return [dict(r) for r in rows]


def list_sources(session: Session) -> list[dict[str, Any]]:
    stats = session.execute(
        select(
            EvaluationRun.source,
            func.count(),
            func.max(EvaluationRun.imported_at),
        ).group_by(EvaluationRun.source)
    ).all()
    out = []
    for src, runs, imported_at in stats:
        records = _records(session, src)
        s = summarize(records)
        out.append(
            {
                "source": src,
                "benchmark_version": s["benchmark_version"],
                "model_spec": s["model_spec"],
                "model_id": s["model_id"],
                "model_revision": s["model_revision"],
                "seed": s["seed"],
                "cases": s["cases"],
                "runs": runs,
                "imported_at": imported_at.isoformat() if imported_at else None,
                "success": s["splits"]["all"]["success"],
                "repair_recovery": s["splits"]["all"]["repair_recovery"],
            }
        )
    out.sort(key=lambda x: x["imported_at"] or "", reverse=True)
    return out


def _norm_id(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def _recorded_ids(session: Session, records: list[dict[str, Any]]) -> set[str]:
    """The records' execution ids whose run is actually stored. Results folders often come
    without traces.jsonl (it is large and not committed), and a link to a run that was never
    imported would only lead to "not found"."""
    wanted = {uuid.UUID(x) for r in records if (x := _norm_id(r.get("execution_id")))}
    found: set[str] = set()
    ids = sorted(wanted)
    for i in range(0, len(ids), 1000):
        rows = session.execute(select(Execution.id).where(Execution.id.in_(ids[i : i + 1000])))
        found.update(str(x) for x in rows.scalars())
    return found


def source_summary(session: Session, source: str) -> dict[str, Any] | None:
    records = _records(session, source)
    if not records:
        return None
    summary = summarize(records)
    summary.pop("definitions", None)
    recorded = _recorded_ids(session, records)
    # Per case: what each arm did, with links to the recorded runs when traces were imported.
    cases: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in records:
        c = cases[r["case_id"]]
        c.setdefault("case_id", r["case_id"])
        c.setdefault("family", r["family"])
        c.setdefault("split", r["split"])
        if r["repeat"] != 0:
            continue
        if r["arm"] == "random":
            c.setdefault("random", []).append(bool(r["passed"]))
        else:
            run_id = _norm_id(r.get("execution_id"))
            c[r["arm"]] = {
                "passed": bool(r["passed"]),
                "skipped": r.get("skipped"),
                "execution_id": run_id if run_id in recorded else None,
                "findings": r.get("findings"),
                "intervention": (r.get("intervention") or {}).get("label"),
            }
    summary["source"] = source
    summary["case_rows"] = sorted(cases.values(), key=lambda c: c["case_id"])
    return summary


def source_csv(session: Session, source: str) -> str | None:
    records = _records(session, source)
    return to_csv(records) if records else None
