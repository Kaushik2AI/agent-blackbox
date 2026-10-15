"""Ground-truth verifier. Judges ONLY the final sandbox state against the fixture's
ground truth. It never reads the model's own claims about success."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_harness.fixtures import Fixture
from agent_harness.sandbox import Sandbox

VERIFIER_VERSION = "1.0"


class VerifierResult(BaseModel):
    verifier_version: str = VERIFIER_VERSION
    passed: bool
    checks: dict[str, bool]
    reasons: list[str]


def verify(fixture: Fixture, sandbox: Sandbox, tool_calls: int) -> VerifierResult:
    truth = fixture.ground_truth
    resolutions = sandbox.effects_of("resolution")
    drafts = sandbox.effects_of("draft")
    expected: dict[str, Any] = truth.resolution.model_dump()

    checks = {
        "exactly_one_resolution": len(resolutions) == 1,
        "resolution_matches_ground_truth": resolutions == [expected],
        "draft_for_customer": any(d["customer_id"] == truth.draft_customer_id for d in drafts),
        "at_most_one_draft": len(drafts) <= 1,
        "within_tool_budget": tool_calls <= fixture.budget.max_tool_calls,
    }
    reasons = []
    if not resolutions:
        reasons.append("no_resolution_submitted")
    elif not checks["resolution_matches_ground_truth"]:
        reasons.append(f"wrong_resolution: got {resolutions}, expected {expected}")
    if not checks["draft_for_customer"]:
        reasons.append("no_draft_for_customer")
    if not checks["at_most_one_draft"]:
        reasons.append("duplicate_drafts")
    if not checks["within_tool_budget"]:
        reasons.append("tool_budget_exceeded")
    return VerifierResult(passed=all(checks.values()), checks=checks, reasons=reasons)
