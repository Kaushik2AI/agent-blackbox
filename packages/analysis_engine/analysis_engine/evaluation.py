"""Measure detector precision/recall against the labelled fixtures.

    python -m analysis_engine.evaluation               # print the table
    python -m analysis_engine.evaluation --out report.json

Every fixture is run by the real agent and recorded by the real SDK in METADATA-ONLY mode
(the privacy default), then analysed. Numbers are computed here, never typed in.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import cache
from importlib import resources
from typing import Any

from pydantic import BaseModel

from analysis_engine.detectors import CATEGORIES, DETECTOR_VERSION, analyze


class CategoryScore(BaseModel):
    category: str
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None
    f1: float | None


class EvaluationReport(BaseModel):
    detector_version: str
    label_set_version: str
    fixtures: int
    per_category: list[CategoryScore]
    micro_precision: float | None
    micro_recall: float | None
    predictions: dict[str, list[str]]
    labels: dict[str, list[str]]


@cache
def load_labels() -> dict[str, Any]:
    raw = (resources.files("analysis_engine") / "labels" / "v1.json").read_text()
    data: dict[str, Any] = json.loads(raw)
    return data


def ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or (p + r) == 0:
        return None if p is None or r is None else 0.0
    return round(2 * p * r / (p + r), 4)


def score(predictions: dict[str, set[str]], labels: dict[str, set[str]]) -> list[CategoryScore]:
    out = []
    for cat in CATEGORIES:
        tp = sum(1 for f in labels if cat in labels[f] and cat in predictions.get(f, set()))
        fp = sum(1 for f in labels if cat not in labels[f] and cat in predictions.get(f, set()))
        fn = sum(1 for f in labels if cat in labels[f] and cat not in predictions.get(f, set()))
        tn = len(labels) - tp - fp - fn
        p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
        out.append(
            CategoryScore(
                category=cat, tp=tp, fp=fp, fn=fn, tn=tn, precision=p, recall=r, f1=f1(p, r)
            )
        )
    return out


def predict(fixture_id: str) -> set[str]:
    from blackbox_sdk.exporters import MemoryExporter
    from blackbox_sdk.integrations.agent_harness import run_traced

    mem = MemoryExporter()
    run_traced(fixture_id, mem, capture_content=False)
    events = [e for b in mem.batches for e in b["events"]]
    return {f.category for f in analyze(events)}


def evaluate() -> EvaluationReport:
    data = load_labels()
    labels = {k: set(v) for k, v in data["labels"].items()}
    predictions = {fixture: predict(fixture) for fixture in labels}
    per = score(predictions, labels)
    tp, fp, fn = sum(c.tp for c in per), sum(c.fp for c in per), sum(c.fn for c in per)
    return EvaluationReport(
        detector_version=DETECTOR_VERSION,
        label_set_version=data["label_set_version"],
        fixtures=len(labels),
        per_category=per,
        micro_precision=ratio(tp, tp + fp),
        micro_recall=ratio(tp, tp + fn),
        predictions={k: sorted(v) for k, v in sorted(predictions.items())},
        labels={k: sorted(v) for k, v in sorted(labels.items())},
    )


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m analysis_engine.evaluation")
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)
    report = evaluate()
    print(
        f"detectors v{report.detector_version}, labels v{report.label_set_version}, "
        f"{report.fixtures} fixtures (metadata-only traces)\n"
    )
    print(f"{'category':<26}{'TP':>4}{'FP':>4}{'FN':>4}{'TN':>4}  precision  recall    F1")
    for c in report.per_category:
        print(
            f"{c.category:<26}{c.tp:>4}{c.fp:>4}{c.fn:>4}{c.tn:>4}  {_fmt(c.precision):>9}"
            f"  {_fmt(c.recall):>6}  {_fmt(c.f1):>4}"
        )
    print(
        f"\nmicro precision {_fmt(report.micro_precision)}, "
        f"micro recall {_fmt(report.micro_recall)}"
    )
    print(
        "Caveat: 6 hand-labelled fixtures written by the same team as the detectors; no "
        "held-out set yet (M8). Treat as a regression check, not a generalisation claim."
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report.model_dump_json(indent=2))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
