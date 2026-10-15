"""Original-vs-fork comparison (M7). Everything is derived from stored rows of the two
executions plus the replay job's intervention record."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalysisFinding, Event, Execution, ReplayJob

CAVEAT = (
    "Deterministic replay: the stub model and tool fixtures are fully controlled, so the "
    "fork differs from the original only by the declared intervention. A recovered fork "
    "shows that this change was followed by success in this run; it is not by itself proof "
    "of the root cause."
)


def _steps(session: Session, execution_id: uuid.UUID) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for e in session.scalars(
        select(Event)
        .where(Event.execution_id == execution_id, Event.event_type == "tool_call_end")
        .order_by(Event.sequence_no)
    ):
        attrs, payload = e.attributes_json or {}, e.payload_json or {}
        index = attrs.get("call_index")
        if not isinstance(index, int):
            continue
        out[index] = {
            "tool": e.tool_name,
            "status": e.status,
            "arguments": payload.get("input_redacted"),
            "error_code": payload.get("error_code"),
            "span_id": e.span_id,
            "intervention": attrs.get("intervention"),
        }
    return out


def diff(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    """Minimal structural JSON diff: one entry per changed leaf."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after), key=str):
            changes += diff(before.get(key, _MISSING), after.get(key, _MISSING), f"{path}.{key}")
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for i in range(max(len(before), len(after))):
            b = before[i] if i < len(before) else _MISSING
            a = after[i] if i < len(after) else _MISSING
            changes += diff(b, a, f"{path}[{i}]")
        return changes
    if before == after:
        return []
    return [
        {
            "path": path,
            "source": None if before is _MISSING else before,
            "fork": None if after is _MISSING else after,
            "change": "added"
            if before is _MISSING
            else "removed"
            if after is _MISSING
            else "changed",
        }
    ]


_MISSING: Any = object()


def _side(session: Session, execution: Execution) -> dict[str, Any]:
    attrs = execution.attributes_json or {}
    derived = attrs.get("derived", {})
    llm_calls = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.execution_id == execution.id, Event.event_type == "llm_call_end")
    )
    findings = session.scalars(
        select(AnalysisFinding).where(AnalysisFinding.execution_id == execution.id)
    ).all()
    duration = (
        (execution.ended_at - execution.started_at).total_seconds() * 1000
        if execution.started_at and execution.ended_at
        else None
    )
    return {
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "verifier": attrs.get("verifier"),
        "termination": attrs.get("termination"),
        "metrics": {
            "tool_calls_recorded": derived.get("tool_calls"),
            "tool_errors": derived.get("tool_errors"),
            "llm_calls_recorded": llm_calls,
            "duration_ms": round(duration, 3) if duration is not None else None,
            "tokens": None,
            "estimated_cost_usd": None,
        },
        "error_codes": derived.get("error_codes", []),
        "findings": [
            {"category": f.category, "severity": f.severity, "title": f.title} for f in findings
        ],
    }


def build_comparison(session: Session, job: ReplayJob) -> dict[str, Any]:
    source = session.get(Execution, job.source_execution_id)
    fork = session.get(Execution, job.fork_execution_id)
    if source is None or fork is None:
        raise LookupError("fork has not been recorded yet")
    replay = (fork.attributes_json or {}).get("replay", {})
    start = int(replay.get("checkpoint_step_index", 0))
    src_steps, fork_steps = _steps(session, source.id), _steps(session, fork.id)
    steps, first_divergence = [], None
    for index in sorted(set(src_steps) | set(fork_steps)):
        s = src_steps.get(index)
        f = fork_steps.get(index) if index >= start else s  # prefix is inherited, not re-run
        changed = (
            (s or {}).get("arguments") != (f or {}).get("arguments")
            or ((s or {}).get("status") != (f or {}).get("status"))
            or (s is None) != (f is None)
        )
        if changed and first_divergence is None:
            first_divergence = index
        steps.append(
            {
                "call_index": index,
                "inherited": index < start,
                "source": s,
                "fork": f,
                "changed": changed,
                "intervened": bool(f and f.get("intervention")),
            }
        )
    src_final = (source.attributes_json or {}).get("final_sandbox")
    fork_final = (fork.attributes_json or {}).get("final_sandbox")
    state_diff = (
        diff(src_final, fork_final) if src_final is not None and fork_final is not None else None
    )
    s_side, f_side = _side(session, source), _side(session, fork)
    # Within the fork only the suffix was executed; report that honestly.
    f_side["metrics"]["tool_calls_executed_in_fork"] = len([k for k in fork_steps if k >= start])
    return {
        "job_id": str(job.id),
        "replay_mode": job.replay_mode,
        "replay_level": "controlled_counterfactual"
        if job.intervention_json
        else "checkpoint_replay",
        "checkpoint": {"checkpoint_id": str(job.checkpoint_id), "step_index": start},
        "intervention": job.intervention_json,
        "sandbox": job.sandbox_config_json,
        "source": s_side,
        "fork": f_side,
        "steps": steps,
        "first_divergence_call_index": first_divergence,
        "state_diff": state_diff,
        "state_diff_note": None
        if state_diff is not None
        else "final sandbox state not captured for one side (metadata-only run)",
        "outcome_changed": s_side["status"] != f_side["status"],
        "caveat": CAVEAT,
    }
