"""Benchmark metrics from run records. Every number states its denominator.

Definitions (also printed in the report):
  success rate        baseline runs that passed the outcome check / baseline runs
  repair coverage     failed baseline runs for which a repair rule produced a change /
                      failed baseline runs
  recovery (repair)   failed baseline runs that passed after the repair /
                      failed baseline runs        (no change produced = not recovered)
  recovery (random)   random-change runs that passed / random-change runs on failed cases
  replay validity     no-change replays whose outcome, ending and saved effects match
                      the baseline / no-change replays
  false benefit       repair recoveries where the no-change replay from the same step
                      ALSO passed (so the change was not needed) / repair recoveries
  detector P/R        per category, over baseline runs, against the case labels
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from analysis_engine.detectors import CATEGORIES

from evaluation.stats import Rate, quantile, rate

Record = dict[str, Any]


def _by(records: list[Record], arm: str) -> list[Record]:
    return [r for r in records if r["arm"] == arm]


def _latency(rows: list[Record]) -> dict[str, float | None]:
    xs = [float(r["elapsed_ms"]) for r in rows if r.get("elapsed_ms") is not None]
    med, p95 = quantile(xs, 0.5), quantile(xs, 0.95)
    return {
        "median_ms": round(med, 2) if med is not None else None,
        "p95_ms": round(p95, 2) if p95 is not None else None,
    }


def _tokens(rows: list[Record]) -> dict[str, Any]:
    ran = [r for r in rows if "tokens_in" in r]
    tin = sum(int(r["tokens_in"]) for r in ran)
    tout = sum(int(r["tokens_out"]) for r in ran)
    costs = [r["cost_usd"] for r in ran if r.get("cost_usd") is not None]
    return {
        "runs": len(ran),
        "tokens_in": tin,
        "tokens_out": tout,
        "mean_tokens": round((tin + tout) / len(ran), 1) if ran else None,
        "cost_usd": round(sum(costs), 6) if costs else None,
    }


# Same order the app uses to pick the "most likely cause" among several findings.
CAUSE_PRIORITY = (
    "state_identity_mismatch",
    "stale_data",
    "tool_schema_mismatch",
    "tool_timeout",
    "repeated_action",
    "retry_loop",
    "budget_exhausted",
)


def main_cause(findings: list[str]) -> str:
    for cat in CAUSE_PRIORITY:
        if cat in findings:
            return cat
    return findings[0] if findings else "none"


def _detectors(baseline: list[Record]) -> dict[str, Any]:
    per: dict[str, dict[str, Any]] = {}
    for cat in CATEGORIES:
        tp = fp = fn = 0
        for r in baseline:
            pred = cat in (r.get("findings") or [])
            truth = cat in r["expected_findings"]
            tp += pred and truth
            fp += pred and not truth
            fn += truth and not pred
        per[cat] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": rate(tp, tp + fp),
            "recall": rate(tp, tp + fn),
        }
    failed = [r for r in baseline if not r["passed"]]
    covered = sum(1 for r in failed if r.get("findings"))
    causes: dict[str, int] = {}
    for r in failed:
        cause = main_cause(list(r.get("findings") or []))
        causes[cause] = causes.get(cause, 0) + 1
    return {
        # Failed runs by their most likely cause ("none": no detector fired). Unlike the
        # per-category table this needs no labels, so it is the one to read for real
        # models, whose mistakes are their own rather than the case's planted fault.
        "failure_causes": dict(sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "per_category": per,
        # Failed runs where at least one detector fired / failed runs.
        "coverage_on_failed": rate(covered, len(failed)),
        "false_alarm_on_passed": rate(
            sum(1 for r in baseline if r["passed"] and r.get("findings")),
            sum(1 for r in baseline if r["passed"]),
        ),
    }


def _block(records: list[Record]) -> dict[str, Any]:
    baseline = _by(records, "baseline")
    failed_keys = {(r["case_id"], r["repeat"]) for r in baseline if not r["passed"]}
    repair = [r for r in _by(records, "repair") if (r["case_id"], r["repeat"]) in failed_keys]
    attempted = [r for r in repair if not r.get("skipped")]
    random_rows = [r for r in _by(records, "random") if (r["case_id"], r["repeat"]) in failed_keys]
    no_change = _by(records, "no_change")
    nc_by = {(r["case_id"], r["repeat"]): r for r in no_change}
    recovered = [r for r in attempted if r["passed"]]
    false_benefit = sum(
        1
        for r in recovered
        if (nc := nc_by.get((r["case_id"], r["repeat"]))) is not None
        and nc.get("restart_call_index") == r.get("restart_call_index")
        and nc["passed"]
    )
    random_cases = defaultdict(list)
    for r in random_rows:
        random_cases[(r["case_id"], r["repeat"])].append(r["passed"])
    return {
        "baseline_runs": len(baseline),
        "success": rate(sum(r["passed"] for r in baseline), len(baseline)),
        "failed_runs": len(failed_keys),
        "repair_coverage": rate(len(attempted), len(failed_keys)),
        "repair_recovery": rate(len(recovered), len(failed_keys)),
        "repair_recovery_when_attempted": rate(len(recovered), len(attempted)),
        "random_recovery": rate(sum(r["passed"] for r in random_rows), len(random_rows)),
        "random_any_draw_recovers": rate(
            sum(1 for v in random_cases.values() if any(v)), len(random_cases)
        ),
        "replay_validity": rate(
            sum(bool(r.get("replay_valid")) for r in no_change), len(no_change)
        ),
        # The control for "did the change cause the recovery": restart, change nothing.
        "no_change_recovery": rate(
            sum(r["passed"] for r in no_change if (r["case_id"], r["repeat"]) in failed_keys),
            sum(1 for r in no_change if (r["case_id"], r["repeat"]) in failed_keys),
        ),
        "false_benefit": rate(false_benefit, len(recovered)),
        "detectors": _detectors(baseline),
        "latency": {
            arm: _latency(_by(records, arm))
            for arm in ("baseline", "no_change", "repair", "random")
        },
        "tokens": {
            arm: _tokens(_by(records, arm)) for arm in ("baseline", "no_change", "repair", "random")
        },
    }


def _family_rows(records: list[Record]) -> list[dict[str, Any]]:
    families: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        families[r["family"]].append(r)
    rows = []
    for family, rs in families.items():
        b = _block(rs)
        rows.append(
            {
                "family": family,
                "cases": len({r["case_id"] for r in rs}),
                "success": b["success"],
                "repair_recovery": b["repair_recovery"],
                "random_recovery": b["random_recovery"],
                "replay_validity": b["replay_validity"],
            }
        )
    return rows


def summarize(records: list[Record]) -> dict[str, Any]:
    if not records:
        raise ValueError("no records to summarize")
    first = records[0]
    splits = {
        "all": records,
        "dev": [r for r in records if r["split"] == "dev"],
        "heldout": [r for r in records if r["split"] == "heldout"],
    }
    return {
        "benchmark_version": first["benchmark_version"],
        "model_spec": first["model_spec"],
        "model_id": first["model_id"],
        "model_revision": first.get("model_revision"),
        "decoding": first.get("decoding"),
        "seed": first["seed"],
        "agent_version": first["agent_version"],
        "cases": len({r["case_id"] for r in records}),
        "runs": len(records),
        "splits": {name: _block(rs) for name, rs in splits.items() if rs},
        "families": _family_rows(records),
        "definitions": __doc__,
    }


def headline(summary: dict[str, Any]) -> dict[str, Rate]:
    """The four numbers shown at the top of the report and the dashboard."""
    s = summary["splits"]["all"]
    return {
        "success": s["success"],
        "repair_recovery": s["repair_recovery"],
        "random_recovery": s["random_recovery"],
        "replay_validity": s["replay_validity"],
    }
