"""Run the deterministic detectors over an execution's STORED events and persist the
findings (replacing any previous findings of the same kind for that execution)."""

from __future__ import annotations

from typing import Any

from analysis_engine import analyze
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalysisFinding, Event, Execution


def stored_events(session: Session, execution: Execution) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(Event).where(Event.execution_id == execution.id).order_by(Event.sequence_no)
    )
    return [
        {
            "event_id": str(e.id),
            "span_id": e.span_id,
            "sequence_no": e.sequence_no,
            "event_type": e.event_type,
            "tool_name": e.tool_name,
            "status": e.status,
            "attributes": e.attributes_json or {},
            "payload": e.payload_json or {},
        }
        for e in rows
    ]


def refresh_findings(session: Session, execution: Execution) -> int:
    findings = analyze(stored_events(session, execution))
    session.execute(
        delete(AnalysisFinding).where(
            AnalysisFinding.execution_id == execution.id, AnalysisFinding.kind == "verified"
        )
    )
    for f in findings:
        session.add(
            AnalysisFinding(
                execution_id=execution.id,
                category=f.category,
                severity=f.severity,
                title=f.title,
                explanation=f.explanation,
                evidence_event_ids=f.evidence_event_ids,
                evidence_span_ids=f.evidence_span_ids,
                caveats=f.caveats,
                detector=f.detector,
                detector_version=f.detector_version,
                kind=f.kind,
            )
        )
    return len(findings)
