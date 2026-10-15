"""Detector behaviour on real recorded runs and on crafted edge cases; metric math."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from blackbox_sdk.exporters import MemoryExporter
from blackbox_sdk.integrations.agent_harness import run_traced

from analysis_engine.detectors import RETRY_LOOP_THRESHOLD, analyze
from analysis_engine.evaluation import evaluate, f1, score


def recorded(fixture: str) -> list[dict[str, Any]]:
    mem = MemoryExporter()
    run_traced(fixture, mem)  # metadata-only, the privacy default
    return [e for b in mem.batches for e in b["events"]]


def cats(events: list[dict[str, Any]]) -> set[str]:
    return {f.category for f in analyze(events)}


def tool_end(seq: int, tool: str, status: str, **payload: Any) -> dict[str, Any]:
    attrs = {"error_type": "timeout"} if payload.get("error_code") == "TIMEOUT" else {}
    return {
        "event_id": str(uuid.uuid4()),
        "span_id": f"{seq:016x}",
        "sequence_no": seq,
        "event_type": "tool_call_end",
        "tool_name": tool,
        "status": status,
        "attributes": attrs,
        "payload": payload,
    }


def test_flagship_failure_findings_cite_real_events() -> None:
    events = recorded("invalid_inventory_argument")
    findings = analyze(events)
    assert {f.category for f in findings} == {
        "tool_schema_mismatch",
        "retry_loop",
        "budget_exhausted",
    }
    by_id = {e["event_id"]: e for e in events}
    for f in findings:
        assert f.evidence_event_ids and all(i in by_id for i in f.evidence_event_ids)
        assert f.detector_version == "1.0" and f.kind == "verified"
    schema = next(f for f in findings if f.category == "tool_schema_mismatch")
    assert len(schema.evidence_event_ids) == 7
    assert all(
        by_id[i]["payload"]["error_code"] == "SKU_REQUIRED" for i in schema.evidence_event_ids
    )
    assert "product_name" in schema.explanation


@pytest.mark.parametrize(
    "fixture", ["exchange_success", "refund_out_of_stock", "transient_inventory_timeout"]
)
def test_healthy_and_recovered_runs_produce_no_findings(fixture: str) -> None:
    assert cats(recorded(fixture)) == set()


def test_identity_mismatch_cites_both_sides() -> None:
    events = recorded("wrong_order_identity")
    (finding,) = analyze(events)
    assert finding.category == "state_identity_mismatch" and finding.severity == "critical"
    tools = [
        next(e for e in events if e["event_id"] == i)["tool_name"]
        for i in finding.evidence_event_ids
    ]
    assert tools == ["lookup_order", "submit_resolution"]


def test_unrecovered_timeout_only() -> None:
    assert cats(recorded("persistent_inventory_timeout")) == {"tool_timeout"}
    recovered = [tool_end(1, "x", "error", error_code="TIMEOUT"), tool_end(2, "x", "ok")]
    assert cats(recovered) == set()


def test_retry_loop_threshold() -> None:
    def failing(n: int) -> list[dict[str, Any]]:
        return [
            tool_end(i, "x", "error", error_code="E", input_redacted={"a": "<str len=1>"})
            for i in range(n)
        ]

    assert "retry_loop" not in cats(failing(RETRY_LOOP_THRESHOLD - 1))
    assert "retry_loop" in cats(failing(RETRY_LOOP_THRESHOLD))
    varied = failing(RETRY_LOOP_THRESHOLD)
    varied[2]["payload"]["input_redacted"] = {"b": "<str len=1>"}  # agent changed something
    assert "retry_loop" not in cats(varied)


def test_metric_math() -> None:
    labels = {"a": {"retry_loop"}, "b": set(), "c": {"retry_loop"}, "d": set()}
    preds = {"a": {"retry_loop"}, "b": {"retry_loop"}, "c": set(), "d": set()}
    rl = next(s for s in score(preds, labels) if s.category == "retry_loop")
    assert (rl.tp, rl.fp, rl.fn, rl.tn) == (1, 1, 1, 1)
    assert rl.precision == 0.5 and rl.recall == 0.5 and rl.f1 == 0.5
    none = next(s for s in score(preds, labels) if s.category == "tool_timeout")
    assert none.precision is None and none.recall is None  # undefined, not 0 or 1
    assert f1(1.0, 0.0) == 0.0


def test_evaluation_is_reproducible_and_meets_regression_floor() -> None:
    a, b = evaluate(), evaluate()
    assert a.model_dump() == b.model_dump()
    assert a.fixtures == 6
    # Regression floor, not a claim about unseen data (see the evaluation caveat).
    assert all((c.recall or 0) >= 1.0 and (c.precision or 0) >= 1.0 for c in a.per_category)
