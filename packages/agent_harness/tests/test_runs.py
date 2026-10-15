"""End-to-end agent runs: outcomes, failure reasons, determinism, isolation, no network."""

import copy
import socket

import pytest

from agent_harness.fixtures import list_fixtures, load_fixture
from agent_harness.run_demo import main as cli
from agent_harness.runner import run_fixture

REQUIRED = {"exchange_success", "invalid_inventory_argument", "transient_inventory_timeout"}


def test_blueprint_required_fixtures_exist() -> None:
    assert REQUIRED <= set(list_fixtures())


@pytest.mark.parametrize("fixture_id", list_fixtures())
def test_every_fixture_matches_its_expected_baseline(fixture_id: str) -> None:
    run = run_fixture(fixture_id)
    base = load_fixture(fixture_id).expected_baseline
    assert run.verifier.passed is base.verifier_passed, run.verifier.reasons
    assert run.termination == base.termination
    assert run.error_codes == base.error_codes


def test_success_fixture_passes_with_correct_sandbox_state() -> None:
    run = run_fixture("exchange_success")
    assert run.verifier.passed and run.verifier.reasons == []
    assert [s["tool"] for s in run.history] == [
        "lookup_order",
        "lookup_inventory",
        "get_policy",
        "draft_response",
        "submit_resolution",
    ]
    resolutions = [e["payload"] for e in run.sandbox_effects if e["kind"] == "resolution"]
    assert resolutions == [{"order_id": "ORD-1001", "choice": "exchange"}]


def test_invalid_argument_fixture_fails_for_the_intended_reason() -> None:
    run = run_fixture("invalid_inventory_argument")
    inventory_calls = [s for s in run.history if s["tool"] == "lookup_inventory"]
    # The bug: product_name passed instead of sku, rejected with SKU_REQUIRED every time...
    assert inventory_calls and all(
        s["args"] == {"product_name": "red backpack"} and s["error_code"] == "SKU_REQUIRED"
        for s in inventory_calls
    )
    # ...the agent repeats it until the budget runs out, never reaching a resolution.
    assert run.termination == "budget_exhausted"
    assert run.tool_calls == load_fixture("invalid_inventory_argument").budget.max_tool_calls
    assert not run.verifier.passed
    assert "no_resolution_submitted" in run.verifier.reasons
    assert run.sandbox_effects == []


def test_transient_timeout_is_retried_and_recovers() -> None:
    run = run_fixture("transient_inventory_timeout")
    inv = [s for s in run.history if s["tool"] == "lookup_inventory"]
    assert [s["error_code"] for s in inv] == ["TIMEOUT", None]
    assert run.verifier.passed


def test_persistent_timeout_gives_up_after_retries() -> None:
    run = run_fixture("persistent_inventory_timeout")
    inv = [s for s in run.history if s["tool"] == "lookup_inventory"]
    assert len(inv) == 1 + load_fixture("persistent_inventory_timeout").model.max_retries_on_timeout
    assert run.termination == "tool_failure" and not run.verifier.passed


def test_out_of_stock_control_chooses_refund() -> None:
    run = run_fixture("refund_out_of_stock")
    resolutions = [e["payload"] for e in run.sandbox_effects if e["kind"] == "resolution"]
    assert resolutions == [{"order_id": "ORD-1001", "choice": "refund"}]
    assert run.verifier.passed


@pytest.mark.parametrize("fixture_id", sorted(REQUIRED))
def test_runs_are_deterministic_over_10_repeats(fixture_id: str) -> None:
    runs = [run_fixture(fixture_id) for _ in range(10)]
    assert len({r.execution_id for r in runs}) == 10  # each run is a new execution
    assert all(r.outcome_signature() == runs[0].outcome_signature() for r in runs)
    assert all(r.determinism == "deterministic" for r in runs)


def test_runs_do_not_mutate_fixtures_or_share_sandbox_state() -> None:
    before = copy.deepcopy(load_fixture("exchange_success").model_dump())
    a = run_fixture("exchange_success")
    b = run_fixture("exchange_success")
    # Each execution's sandbox starts empty: draft/resolution IDs restart at 1.
    assert [e["effect_id"] for e in a.sandbox_effects] == ["draft-1", "resolution-1"]
    assert [e["effect_id"] for e in b.sandbox_effects] == ["draft-1", "resolution-1"]
    assert load_fixture("exchange_success").model_dump() == before


def test_no_network_access_during_any_run(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[object] = []

    def forbid(self: socket.socket, address: object) -> None:
        attempts.append(address)
        raise AssertionError(f"network access attempted: {address}")

    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    for fid in list_fixtures():
        run_fixture(fid)
    assert attempts == []


def test_events_have_monotonic_sequence_numbers() -> None:
    run = run_fixture("transient_inventory_timeout")
    assert [e.sequence_no for e in run.events] == list(range(len(run.events)))
    assert run.events[0].type == "agent_start" and run.events[-1].type == "agent_end"


def test_cli_all_matches_baselines_and_exit_codes() -> None:
    assert cli(["--all", "--repeat", "3"]) == 0
    assert cli(["--fixture", "exchange_success"]) == 0
    assert cli(["--fixture", "invalid_inventory_argument"]) == 1
    assert cli(["--fixture", "does_not_exist"]) == 2
