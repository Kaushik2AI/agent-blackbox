"""Deterministic failure detectors (M5).

Each detector reads the recorded events of ONE execution and returns findings that cite
the exact event IDs they are based on. Findings are observations ("this happened, here is
the evidence"); they do not claim to prove the root cause. Every detector works on
metadata-only traces: it uses error codes, error types, argument field names and salted
identity fingerprints, never captured values.

Input events use the ingest/timeline shape: event_id, span_id, sequence_no, event_type,
tool_name, status, attributes, payload.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

DETECTOR_VERSION = "1.1"
RETRY_LOOP_THRESHOLD = 4  # identical failing calls in a row (default retry budget is 3)

Category = Literal[
    "tool_schema_mismatch",
    "retry_loop",
    "tool_timeout",
    "budget_exhausted",
    "state_identity_mismatch",
    "repeated_action",
]
CATEGORIES: tuple[Category, ...] = (
    "tool_schema_mismatch",
    "retry_loop",
    "tool_timeout",
    "budget_exhausted",
    "state_identity_mismatch",
    "repeated_action",
)
# Tools whose successful call leaves a lasting effect; doing one twice is a bug.
SIDE_EFFECT_TOOLS = ("draft_response", "submit_resolution")
Severity = Literal["critical", "high", "medium", "low"]

Event = dict[str, Any]


class Finding(BaseModel):
    category: Category
    severity: Severity
    title: str
    explanation: str
    evidence_event_ids: list[str] = Field(min_length=1)
    evidence_span_ids: list[str]
    detector: str
    detector_version: str = DETECTOR_VERSION
    kind: Literal["verified"] = "verified"
    caveats: list[str] = Field(default_factory=list)


def _ordered(events: Sequence[Event]) -> list[Event]:
    return sorted(events, key=lambda e: int(e["sequence_no"]))


def _tool_ends(events: Sequence[Event]) -> list[Event]:
    return [e for e in _ordered(events) if e["event_type"] == "tool_call_end"]


def _ids(events: Sequence[Event]) -> tuple[list[str], list[str]]:
    spans = [str(e["span_id"]) for e in events if e.get("span_id")]
    return [str(e["event_id"]) for e in events], list(dict.fromkeys(spans))


def _arg_fields(event: Event) -> list[str]:
    args = event.get("payload", {}).get("input_redacted")
    return sorted(args) if isinstance(args, dict) else []


# ------------------------------------------------------------------ detectors
def detect_tool_schema_mismatch(events: Sequence[Event]) -> list[Finding]:
    groups: dict[tuple[str, str], list[Event]] = {}
    for e in _tool_ends(events):
        if e.get("status") == "error" and e.get("attributes", {}).get("error_type") == (
            "validation_error"
        ):
            key = (str(e.get("tool_name")), str(e["payload"].get("error_code")))
            groups.setdefault(key, []).append(e)
    findings = []
    for (tool, code), evs in groups.items():
        ids, spans = _ids(evs)
        sent = _arg_fields(evs[0])
        findings.append(
            Finding(
                category="tool_schema_mismatch",
                severity="high",
                title=f"{tool} rejected its arguments ({code})",
                explanation=(
                    f"{len(evs)} call(s) to {tool} failed argument validation with {code}. "
                    f"Fields sent: {', '.join(sent) or 'none'}. "
                    f"Tool message: {evs[0]['payload'].get('error_message', 'n/a')}."
                ),
                evidence_event_ids=ids,
                evidence_span_ids=spans,
                detector="tool_schema_mismatch",
            )
        )
    return findings


def _call_signature(e: Event) -> str:
    p = e.get("payload", {})
    return json.dumps(
        [e.get("tool_name"), p.get("input_redacted"), p.get("identity"), p.get("error_code")],
        sort_keys=True,
    )


def detect_retry_loop(events: Sequence[Event]) -> list[Finding]:
    findings: list[Finding] = []
    run: list[Event] = []

    def flush() -> None:
        if len(run) >= RETRY_LOOP_THRESHOLD:
            ids, spans = _ids(run)
            first = run[0]
            findings.append(
                Finding(
                    category="retry_loop",
                    severity="high",
                    title=f"{first.get('tool_name')} retried {len(run)}x with identical input",
                    explanation=(
                        f"The agent made {len(run)} consecutive calls to "
                        f"{first.get('tool_name')} with the same arguments and got the same "
                        f"error ({first['payload'].get('error_code')}) every time; nothing "
                        "changed between attempts."
                    ),
                    evidence_event_ids=ids,
                    evidence_span_ids=spans,
                    detector="retry_loop",
                    caveats=[f"threshold: {RETRY_LOOP_THRESHOLD} identical failing calls"],
                )
            )

    for e in _tool_ends(events):
        if e.get("status") != "error":
            flush()
            run = []
            continue
        if run and _call_signature(run[-1]) != _call_signature(e):
            flush()
            run = []
        run.append(e)
    flush()
    return findings


def detect_tool_timeout(events: Sequence[Event]) -> list[Finding]:
    ends = _tool_ends(events)
    findings = []
    for tool in dict.fromkeys(str(e.get("tool_name")) for e in ends):
        calls = [e for e in ends if e.get("tool_name") == tool]
        timeouts = [e for e in calls if e["payload"].get("error_code") == "TIMEOUT"]
        if not timeouts:
            continue
        last_timeout = int(timeouts[-1]["sequence_no"])
        recovered = any(
            e.get("status") == "ok" and int(e["sequence_no"]) > last_timeout for e in calls
        )
        if recovered:
            continue
        ids, spans = _ids(timeouts)
        findings.append(
            Finding(
                category="tool_timeout",
                severity="high",
                title=f"{tool} timed out and never recovered",
                explanation=(
                    f"{tool} timed out {len(timeouts)} time(s) and no later call to it "
                    "succeeded, so the agent continued without its result."
                ),
                evidence_event_ids=ids,
                evidence_span_ids=spans,
                detector="tool_timeout",
                caveats=["timeouts followed by a successful retry are not reported"],
            )
        )
    return findings


def detect_budget_exhausted(events: Sequence[Event]) -> list[Finding]:
    hits = [e for e in _ordered(events) if e["event_type"] == "budget_exhausted"]
    if not hits:
        return []
    ids, spans = _ids(hits)
    limit = hits[0].get("payload", {}).get("max_tool_calls")
    return [
        Finding(
            category="budget_exhausted",
            severity="high",
            title=f"Tool-call budget exhausted ({limit} calls)",
            explanation=(
                f"The agent wanted to make another tool call but had used all {limit} "
                "allowed calls, so the run was stopped before finishing the task."
            ),
            evidence_event_ids=ids,
            evidence_span_ids=spans,
            detector="budget_exhausted",
        )
    ]


def detect_state_identity_mismatch(events: Sequence[Event]) -> list[Finding]:
    established: dict[str, tuple[str, Event]] = {}
    findings = []
    for e in _tool_ends(events):
        p = e.get("payload", {})
        for key, fp in (p.get("identity") or {}).items():
            if key in established and established[key][0] != fp:
                source = established[key][1]
                ids, spans = _ids([source, e])
                findings.append(
                    Finding(
                        category="state_identity_mismatch",
                        severity="critical",
                        title=f"{e.get('tool_name')} used a different {key} than earlier steps",
                        explanation=(
                            f"{source.get('tool_name')} (event #{source['sequence_no']}) "
                            f"established one {key}, but {e.get('tool_name')} (event "
                            f"#{e['sequence_no']}) was called with a different one."
                        ),
                        evidence_event_ids=ids,
                        evidence_span_ids=spans,
                        detector="state_identity_mismatch",
                        caveats=["compared via per-run salted fingerprints; values not stored"],
                    )
                )
        if e.get("status") == "ok":
            for key, fp in (p.get("output_identity") or {}).items():
                established.setdefault(key, (fp, e))
            for key, fp in (p.get("identity") or {}).items():
                established.setdefault(key, (fp, e))
    return findings


def detect_repeated_action(events: Sequence[Event]) -> list[Finding]:
    """A tool with a lasting effect (writing the reply, closing the ticket) succeeded more
    than once: the agent did not notice the work was already done."""
    findings = []
    ends = [e for e in _tool_ends(events) if e.get("status") == "ok"]
    for tool in SIDE_EFFECT_TOOLS:
        hits = [e for e in ends if e.get("tool_name") == tool]
        if len(hits) < 2:
            continue
        ids, spans = _ids(hits)
        what = "closed the ticket" if tool == "submit_resolution" else "wrote a reply draft"
        findings.append(
            Finding(
                category="repeated_action",
                severity="high",
                title=f"{tool} ran {len(hits)} times",
                explanation=(
                    f"The agent {what} {len(hits)} times (events "
                    + ", ".join(f"#{e['sequence_no']}" for e in hits)
                    + "). It should happen once; every extra call saved another copy."
                ),
                evidence_event_ids=ids,
                evidence_span_ids=spans,
                detector="repeated_action",
            )
        )
    return findings


DETECTORS: tuple[Callable[[Sequence[Event]], list[Finding]], ...] = (
    detect_tool_schema_mismatch,
    detect_retry_loop,
    detect_tool_timeout,
    detect_budget_exhausted,
    detect_state_identity_mismatch,
    detect_repeated_action,
)


def analyze(events: Sequence[Event]) -> list[Finding]:
    """Run every detector. Findings are ordered by first evidence position."""
    findings = [f for detector in DETECTORS for f in detector(events)]
    position = {str(e["event_id"]): int(e["sequence_no"]) for e in events}
    return sorted(findings, key=lambda f: min(position.get(i, 0) for i in f.evidence_event_ids))
