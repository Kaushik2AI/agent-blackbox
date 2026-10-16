"""Write benchmark artifacts: runs.jsonl, runs.csv, summary.json, summary.md, charts/*.svg.

Every number in summary.md and the charts is computed from runs.jsonl by metrics.py.
"""

from __future__ import annotations

import csv
import io
import json
from html import escape
from pathlib import Path
from typing import Any

from evaluation.metrics import summarize
from evaluation.stats import Rate

CSV_FIELDS = [
    "run_key", "benchmark_version", "case_id", "family", "split", "arm", "repeat", "draw",
    "seed", "model_spec", "model_id", "model_revision", "agent_version", "fixture_version",
    "passed", "skipped", "termination", "tool_calls", "error_codes", "findings",
    "expected_findings", "restart_call_index", "intervention_type", "intervention_tool",
    "replay_valid", "elapsed_ms", "tokens_in", "tokens_out", "cost_usd", "execution_id",
    "parent_execution_id",
]  # fmt: skip

LABELS = {
    "repair": "FlightPath's suggested change",
    "random": "Random valid change",
    "no_change": "Restart, nothing changed",
}


def load_runs(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def to_csv(records: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in records:
        row = dict(r)
        iv = r.get("intervention") or {}
        row["intervention_type"] = iv.get("type")
        row["intervention_tool"] = iv.get("tool")
        for k in ("error_codes", "findings", "expected_findings"):
            if isinstance(row.get(k), list):
                row[k] = ";".join(row[k])
        w.writerow(row)
    return buf.getvalue()


def pct(r: Rate) -> str:
    if r["rate"] is None:
        return "n/a (0 runs)"
    return f"{r['rate'] * 100:.0f}% ({r['k']}/{r['n']}; 95% CI {r['ci_low'] * 100:.0f}-{r['ci_high'] * 100:.0f}%)"  # type: ignore[operator]


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# FlightPath benchmark results: {summary['benchmark_version']}",
        "",
        f"Agent: `{summary['model_id']}` ({summary['model_spec']})"
        + (f", revision `{summary['model_revision']}`" if summary.get("model_revision") else "")
        + f". Agent harness {summary['agent_version']}. Seed {summary['seed']}.",
        f"{summary['cases']} cases, {summary['runs']} runs. Generated from `runs.jsonl` by "
        "`python -m evaluation.benchmark`.",
        "",
        "| Metric | All cases | Dev | Held-out |",
        "|---|---|---|---|",
    ]
    rows = [
        ("Baseline success", "success"),
        ("Recovery with FlightPath's change", "repair_recovery"),
        ("Recovery with a random valid change", "random_recovery"),
        ("Recovery when restarting with no change", "no_change_recovery"),
        ("Repair coverage (a change was proposed)", "repair_coverage"),
        ("Replay validity (no-change replay reproduces)", "replay_validity"),
        ("False benefit (recovered without the change)", "false_benefit"),
    ]
    splits = summary["splits"]
    for label, key in rows:
        cells = [pct(splits[s][key]) if s in splits else "n/a" for s in ("all", "dev", "heldout")]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## By family",
        "",
        "| Family | Cases | Baseline success | Recovery (FlightPath) | Recovery (random) |",
        "|---|---|---|---|---|",
    ]
    for f in summary["families"]:
        lines.append(
            f"| {f['family']} | {f['cases']} | {pct(f['success'])} | {pct(f['repair_recovery'])} "
            f"| {pct(f['random_recovery'])} |"
        )
    det = splits["all"]["detectors"]
    lines += [
        "",
        "## Detectors (baseline runs, against case labels)",
        "",
        "| Category | TP | FP | FN | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for cat, d in det["per_category"].items():
        lines.append(
            f"| {cat} | {d['tp']} | {d['fp']} | {d['fn']} | {pct(d['precision'])} | {pct(d['recall'])} |"
        )
    lines += [
        "",
        f"Failed runs where at least one detector fired: {pct(det['coverage_on_failed'])}.",
        f"Passed runs where a detector fired anyway: {pct(det['false_alarm_on_passed'])}.",
        "",
        "## Latency per run",
        "",
        "| Arm | Median | p95 | Mean tokens |",
        "|---|---|---|---|",
    ]
    for arm, lat in splits["all"]["latency"].items():
        tok = splits["all"]["tokens"][arm]
        lines.append(
            f"| {arm} | {lat['median_ms'] if lat['median_ms'] is not None else 'n/a'} ms "
            f"| {lat['p95_ms'] if lat['p95_ms'] is not None else 'n/a'} ms "
            f"| {tok['mean_tokens'] if tok['mean_tokens'] is not None else 'n/a'} |"
        )
    lines += [
        "",
        "## How to read this",
        "",
        "- Intervals are 95% Wilson score intervals. Random-change runs are several draws per",
        "  case, so their interval is narrower than the number of cases justifies.",
        "- With the scripted agent every run is deterministic: one run per case and arm is the",
        "  whole distribution. Real-model runs (GPU) repeat each case with different seeds.",
        "- The repair rules and detectors were written against the hand-made demo fixtures,",
        "  not these cases; the held-out split is reported separately anyway.",
        "- Recovery shows that a change was followed by success, compared against the two",
        "  controls (no change, random change). It is not by itself proof of the root cause.",
        "",
        "## Definitions",
        "",
        "```",
        str(summary["definitions"]).strip(),
        "```",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ charts (static SVG)
INK, INK2, MUTED, LINE, SURFACE, BAR = (
    "#151a24",
    "#485063",
    "#737b8e",
    "#e0e3ea",
    "#ffffff",
    "#2160c4",
)


def bar_chart_svg(title: str, subtitle: str, rows: list[tuple[str, Rate]]) -> str:
    """Horizontal bars (one series, one hue) with 95% CI whiskers and direct labels."""
    w, left, right, top, row_h = 760, 250, 150, 70, 44
    h = top + row_h * len(rows) + 46
    plot_w = w - left - right

    def x(v: float) -> float:
        return left + v * plot_w

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-labelledby="t d" font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<title id="t">{escape(title)}</title><desc id="d">{escape(subtitle)}</desc>',
        f'<rect width="{w}" height="{h}" rx="12" fill="{SURFACE}"/>',
        f'<text x="24" y="32" font-size="17" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="24" y="52" font-size="13" fill="{INK2}">{escape(subtitle)}</text>',
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        tx = x(tick)
        parts.append(
            f'<line x1="{tx:.1f}" y1="{top - 6}" x2="{tx:.1f}" y2="{h - 34}" stroke="{LINE}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{tx:.1f}" y="{h - 16}" font-size="12" fill="{MUTED}" text-anchor="middle">{int(tick * 100)}%</text>'
        )
    for i, (label, r) in enumerate(rows):
        cy = top + i * row_h + row_h / 2
        parts.append(
            f'<text x="{left - 14}" y="{cy + 4:.1f}" font-size="13.5" fill="{INK}" text-anchor="end">{escape(label)}</text>'
        )
        if r["rate"] is None:
            parts.append(
                f'<text x="{left + 6}" y="{cy + 4:.1f}" font-size="13" fill="{MUTED}">no runs</text>'
            )
            continue
        bw = max(r["rate"] * plot_w, 2.0)
        parts.append(
            f'<rect x="{left}" y="{cy - 9:.1f}" width="{bw:.1f}" height="18" rx="4" fill="{BAR}"/>'
        )
        lo, hi = x(r["ci_low"] or 0), x(r["ci_high"] or 0)
        parts.append(
            f'<line x1="{lo:.1f}" y1="{cy:.1f}" x2="{hi:.1f}" y2="{cy:.1f}" stroke="{INK}" stroke-width="1.5"/>'
        )
        for cx in (lo, hi):
            parts.append(
                f'<line x1="{cx:.1f}" y1="{cy - 6:.1f}" x2="{cx:.1f}" y2="{cy + 6:.1f}" stroke="{INK}" stroke-width="1.5"/>'
            )
        parts.append(
            f'<text x="{max(hi, x(r["rate"])) + 10:.1f}" y="{cy + 4:.1f}" font-size="13.5" fill="{INK}">'
            f'<tspan font-weight="600">{r["rate"] * 100:.0f}%</tspan>'
            f'<tspan fill="{INK2}"> {r["k"]}/{r["n"]}</tspan></text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def charts(summary: dict[str, Any]) -> dict[str, str]:
    s = summary["splits"]["all"]
    recovery = bar_chart_svg(
        "Recovery of failed runs, by change",
        f"Share of {s['failed_runs']} failed runs that pass after restarting with one change. "
        "Whiskers: 95% CI.",
        [(LABELS[k], s[f"{k}_recovery"]) for k in ("repair", "random", "no_change")],
    )
    families = bar_chart_svg(
        "Recovery with FlightPath's change, by failure family",
        "Failed runs per family that pass after the suggested change. Whiskers: 95% CI.",
        [
            (f["family"].replace("_", " "), f["repair_recovery"])
            for f in summary["families"]
            if f["repair_recovery"]["n"]
        ],
    )
    return {"recovery.svg": recovery, "families.svg": families}


def write_all(
    records: list[dict[str, Any]], out: Path, *, runs_written: bool = False
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    records = sorted(
        records,
        key=lambda r: (
            r["case_id"],
            r["arm"],
            r["repeat"],
            r["draw"] if r["draw"] is not None else -1,
        ),
    )
    if not runs_written:
        (out / "runs.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
        )
    (out / "runs.csv").write_text(to_csv(records))
    summary = summarize(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (out / "summary.md").write_text(markdown(summary))
    (out / "charts").mkdir(exist_ok=True)
    for name, svg in charts(summary).items():
        (out / "charts" / name).write_text(svg)
    return summary
