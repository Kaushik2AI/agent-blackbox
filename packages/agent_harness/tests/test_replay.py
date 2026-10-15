"""Checkpoints, resume and interventions at the harness level (M6 core)."""

import copy
from typing import Any

import pytest

from agent_harness.interventions import (
    InterventionError,
    ReplaceToolArguments,
    ReplaceToolResult,
    validate_intervention,
)
from agent_harness.runner import (
    CheckpointMismatch,
    checkpoint_sha256,
    run_fixture,
    run_from_checkpoint,
)


def checkpoints(fixture: str) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    run_fixture(fixture, on_event=lambda t, d: seen.append(d) if t == "checkpoint" else None)
    return seen


def test_a_pre_step_checkpoint_precedes_every_tool_call() -> None:
    run = run_fixture("invalid_inventory_argument")
    cps = checkpoints("invalid_inventory_argument")
    assert [c["call_index"] for c in cps] == list(range(run.tool_calls))
    first_inventory = cps[1]["document"]
    assert first_inventory["graph_state"]["pending"] == {
        "tool": "lookup_inventory",
        "args": {"product_name": "red backpack"},
    }
    assert first_inventory["graph_state"]["tool_calls"] == 1
    assert all(c["sha256"] == checkpoint_sha256(c["document"]) for c in cps)


def test_checkpoints_are_deterministic_across_runs() -> None:
    a = [c["sha256"] for c in checkpoints("exchange_success")]
    b = [c["sha256"] for c in checkpoints("exchange_success")]
    assert a == b


def test_resume_without_intervention_reproduces_the_failure() -> None:
    doc = checkpoints("invalid_inventory_argument")[1]["document"]
    fork = run_from_checkpoint(doc)
    assert fork.termination == "budget_exhausted" and not fork.verifier.passed
    assert fork.resumed_from_call_index == 1


def test_fixing_the_sku_argument_recovers_the_run() -> None:
    doc = checkpoints("invalid_inventory_argument")[1]["document"]
    fix = validate_intervention(
        ReplaceToolArguments(call_index=1, arguments={"sku": "SKU-RED-004"}), "lookup_inventory"
    )
    fork = run_from_checkpoint(doc, [fix])
    assert fork.verifier.passed, fork.verifier.reasons
    assert fork.termination == "completed"
    assert fork.history[1]["args"] == {"sku": "SKU-RED-004"} and fork.history[1]["ok"]
    assert fork.history[1]["intervention"] == "replace_tool_argument"
    assert [s["tool"] for s in fork.history] == [
        "lookup_order",
        "lookup_inventory",
        "get_policy",
        "draft_response",
        "submit_resolution",
    ]


def test_replacing_a_timed_out_result_recovers_the_persistent_timeout() -> None:
    doc = checkpoints("persistent_inventory_timeout")[1]["document"]
    result = {
        "sku": "SKU-RED-004",
        "available": True,
        "quantity": 12,
        "as_of": "2026-10-01T09:00:00Z",
    }
    fix = validate_intervention(ReplaceToolResult(call_index=1, result=result), "lookup_inventory")
    fork = run_from_checkpoint(doc, [fix])
    assert fork.verifier.passed and fork.history[1]["intervention"] == "replace_tool_result"


def test_interventions_must_match_the_tool_contract() -> None:
    with pytest.raises(InterventionError, match="sku"):
        validate_intervention(
            ReplaceToolArguments(1, {"product_name": "red backpack"}), "lookup_inventory"
        )
    with pytest.raises(InterventionError, match="Extra inputs"):
        validate_intervention(
            ReplaceToolArguments(1, {"sku": "SKU-RED-004", "drop_table": True}), "lookup_inventory"
        )
    with pytest.raises(InterventionError):
        validate_intervention(ReplaceToolResult(1, {"available": "maybe"}), "lookup_inventory")
    with pytest.raises(InterventionError, match="allowlisted"):
        validate_intervention(ReplaceToolArguments(1, {}), "send_email")


def test_interventions_before_the_checkpoint_are_rejected() -> None:
    doc = checkpoints("invalid_inventory_argument")[3]["document"]
    with pytest.raises(InterventionError, match="before the checkpoint"):
        run_from_checkpoint(doc, [ReplaceToolArguments(1, {"sku": "SKU-RED-004"})])


def test_resume_never_mutates_the_checkpoint_or_source() -> None:
    cp = checkpoints("invalid_inventory_argument")[1]
    before = copy.deepcopy(cp["document"])
    run_from_checkpoint(cp["document"], [ReplaceToolArguments(1, {"sku": "SKU-RED-004"})])
    assert cp["document"] == before and checkpoint_sha256(cp["document"]) == cp["sha256"]


def test_fork_sandbox_is_independent() -> None:
    doc = checkpoints("exchange_success")[3]["document"]  # before draft_response
    a = run_from_checkpoint(doc)
    b = run_from_checkpoint(doc)
    assert [e["effect_id"] for e in a.sandbox_effects] == ["draft-1", "resolution-1"]
    assert [e["effect_id"] for e in b.sandbox_effects] == ["draft-1", "resolution-1"]
    assert doc["sandbox"]["effects"] == []


def test_tampered_or_stale_checkpoints_are_refused() -> None:
    doc = copy.deepcopy(checkpoints("exchange_success")[1]["document"])
    doc["fixture_sha256"] = "0" * 64
    with pytest.raises(CheckpointMismatch, match="fixture content"):
        run_from_checkpoint(doc)
    doc = copy.deepcopy(checkpoints("exchange_success")[1]["document"])
    doc["harness_version"] = "0.0.1"
    with pytest.raises(CheckpointMismatch, match="harness"):
        run_from_checkpoint(doc)


def test_identity_bug_fixture_fails_on_the_wrong_order() -> None:
    run = run_fixture("wrong_order_identity")
    assert not run.verifier.passed
    assert any(r.startswith("wrong_resolution") for r in run.verifier.reasons)
