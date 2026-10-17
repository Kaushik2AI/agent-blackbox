"""Benchmark: dataset drift, statistics, repair rules, metrics, reproducibility, resume."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_harness.fixtures import benchmark_cases, load_fixture
from agent_harness.runner import run_fixture

from evaluation import benchmark, dataset
from evaluation.arms import CaseRunner, RunConfig, canonical
from evaluation.hf import TransformersModel, choose_model, json_complete
from evaluation.metrics import main_cause, summarize
from evaluation.report import bar_chart_svg, to_csv
from evaluation.stats import quantile, rate, wilson


# ------------------------------------------------------------------ dataset
def test_committed_dataset_matches_the_generator() -> None:
    assert dataset.main(["--check"]) == 0


def test_dataset_shape_and_heldout_split() -> None:
    cases = benchmark_cases()
    assert 30 <= len(cases) <= 60
    assert len({c.case_id for c in cases}) == len(cases)
    for family, (n, _, _) in dataset.FAMILIES.items():
        fam = [c for c in cases if c.family == family]
        assert len(fam) == n
        assert [c.split for c in fam].count("heldout") == dataset.HELDOUT_PER_FAMILY


@pytest.mark.parametrize("case", benchmark_cases(), ids=lambda c: c.case_id)
def test_every_case_behaves_as_its_family_says(case: Any) -> None:
    # Cases resolve by id like any fixture, and the scripted agent fails for the
    # intended reason (or passes, for controls).
    assert load_fixture(case.case_id) == case.fixture
    run = run_fixture(case.case_id)
    exp = case.fixture.expected_baseline
    assert run.verifier.passed == exp.verifier_passed
    assert run.termination == exp.termination
    assert run.error_codes == exp.error_codes


def test_demo_fixture_hashes_did_not_change() -> None:
    # Adding the order_id_case knob must not invalidate checkpoints saved before it.
    import hashlib

    fixture = load_fixture("exchange_success")
    data = fixture.model_dump(mode="json")
    assert data["model"]["order_id_case"] is None
    data["model"].pop("order_id_case")
    legacy = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    assert fixture.content_hash == legacy


# ------------------------------------------------------------------ statistics
def test_wilson_interval_matches_reference_values() -> None:
    lo, hi = wilson(8, 10)  # type: ignore[misc]
    assert (round(lo, 4), round(hi, 4)) == (0.4902, 0.9433)
    lo, hi = wilson(0, 6)  # type: ignore[misc]
    assert lo == 0.0 and round(hi, 4) == 0.3903
    assert wilson(0, 0) is None
    with pytest.raises(ValueError):
        wilson(5, 4)


def test_rate_and_quantile() -> None:
    assert rate(0, 0) == {"k": 0, "n": 0, "rate": None, "ci_low": None, "ci_high": None}
    assert rate(3, 4)["rate"] == 0.75
    assert quantile([], 0.5) is None
    assert quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert quantile([5.0], 0.95) == 5.0


# ------------------------------------------------------------------ metric math
def _rec(case: str, arm: str, passed: bool, **kw: Any) -> dict[str, Any]:
    base = {
        "benchmark_version": "t", "case_id": case, "family": kw.pop("family", "f"), "split": "dev",
        "arm": arm, "repeat": 0, "draw": kw.pop("draw", None), "seed": 1, "model_spec": "stub",
        "model_id": "m", "agent_version": "x", "passed": passed, "expected_findings": [],
        "findings": [], "elapsed_ms": 1.0, "tokens_in": 0, "tokens_out": 0, "cost_usd": None,
        "restart_call_index": 1,
    }  # fmt: skip
    base.update(kw)
    return base


def test_metrics_use_failed_runs_as_the_recovery_denominator() -> None:
    records = [
        _rec("a", "baseline", True),
        _rec("b", "baseline", False),
        _rec("c", "baseline", False),
        _rec("d", "baseline", False),
        _rec("a", "no_change", True, replay_valid=True),
        _rec("b", "no_change", False, replay_valid=True),
        _rec("c", "no_change", True, replay_valid=False),
        _rec("d", "no_change", False, replay_valid=True),
        _rec("b", "repair", True),
        _rec("c", "repair", True),  # recovered, but the no-change replay also passed
        {**_rec("d", "repair", False), "skipped": "no repair rule"},
        _rec("b", "random", True, draw=0),
        _rec("b", "random", False, draw=1),
        _rec("c", "random", False, draw=0),
        _rec("c", "random", False, draw=1),
    ]
    s = summarize(records)["splits"]["all"]
    assert s["success"]["k"] == 1 and s["success"]["n"] == 4
    assert s["failed_runs"] == 3
    assert (s["repair_coverage"]["k"], s["repair_coverage"]["n"]) == (2, 3)
    assert (s["repair_recovery"]["k"], s["repair_recovery"]["n"]) == (2, 3)  # skipped counts
    assert (s["repair_recovery_when_attempted"]["k"], s["repair_recovery_when_attempted"]["n"]) == (
        2,
        2,
    )
    assert (s["random_recovery"]["k"], s["random_recovery"]["n"]) == (1, 4)
    assert (s["random_any_draw_recovers"]["k"], s["random_any_draw_recovers"]["n"]) == (1, 2)
    assert (s["replay_validity"]["k"], s["replay_validity"]["n"]) == (3, 4)
    assert (s["false_benefit"]["k"], s["false_benefit"]["n"]) == (1, 2)
    assert (s["no_change_recovery"]["k"], s["no_change_recovery"]["n"]) == (1, 3)


def test_detector_scoring() -> None:
    records = [
        _rec("a", "baseline", False, expected_findings=["retry_loop"], findings=["retry_loop"]),
        _rec("b", "baseline", False, expected_findings=["retry_loop"], findings=[]),
        _rec("c", "baseline", True, expected_findings=[], findings=["retry_loop"]),
    ]
    det = summarize(records)["splits"]["all"]["detectors"]
    loop = det["per_category"]["retry_loop"]
    assert (loop["tp"], loop["fp"], loop["fn"]) == (1, 1, 1)
    assert det["coverage_on_failed"]["k"] == 1 and det["coverage_on_failed"]["n"] == 2
    assert det["false_alarm_on_passed"]["k"] == 1
    assert det["failure_causes"] == {"none": 1, "retry_loop": 1}


def test_main_cause_follows_the_app_priority() -> None:
    assert main_cause(["budget_exhausted", "retry_loop", "tool_schema_mismatch"]) == (
        "tool_schema_mismatch"
    )
    assert main_cause(["budget_exhausted", "repeated_action"]) == "repeated_action"
    assert main_cause([]) == "none"


# ------------------------------------------------------------------ runner
def _cases(*families: str) -> list[Any]:
    return [c for c in benchmark_cases() if c.family in families][:2]


def test_arms_on_a_failing_case_and_repair_beats_the_controls() -> None:
    runner = CaseRunner(RunConfig(random_draws=3), None)
    case = _cases("invalid_argument")[0]
    rows = runner.run_case(case)
    arms = [r["arm"] for r in rows]
    assert arms == ["baseline", "no_change", "repair", "random", "random", "random"]
    by = {r["arm"]: r for r in rows}
    assert by["baseline"]["passed"] is False
    assert set(by["baseline"]["findings"]) == {
        "tool_schema_mismatch",
        "retry_loop",
        "budget_exhausted",
    }
    assert by["no_change"]["replay_valid"] is True and by["no_change"]["passed"] is False
    assert by["repair"]["passed"] is True
    assert by["repair"]["intervention"]["payload"] == {
        "sku": case.fixture.world["orders"][case.fixture.task.order_id]["sku"]
    }
    assert by["repair"]["parent_execution_id"] == by["baseline"]["execution_id"]


def test_passing_case_runs_only_baseline_and_no_change() -> None:
    rows = CaseRunner(RunConfig(), None).run_case(_cases("control_exchange")[0])
    assert [r["arm"] for r in rows] == ["baseline", "no_change"]


def test_stale_retrieval_is_an_honest_gap() -> None:
    rows = CaseRunner(RunConfig(random_draws=1), None).run_case(_cases("stale_retrieval")[0])
    by = {r["arm"]: r for r in rows}
    assert by["baseline"]["passed"] is False and by["baseline"]["findings"] == []
    assert by["repair"]["skipped"] == "no repair rule"


def test_benchmark_is_reproducible_and_resumable(tmp_path: Path) -> None:
    args = ["run", "--family", "invalid_argument", "--family", "control_refund", "--draws", "2"]
    a, b = tmp_path / "a", tmp_path / "b"
    assert benchmark.main([*args, "--out", str(a)]) == 0
    assert benchmark.main([*args, "--out", str(b), "--limit", "3"]) == 0  # "interrupted"
    assert benchmark.main([*args, "--out", str(b), "--resume", "--traces"]) == 0

    def rows(p: Path) -> list[str]:
        recs = [json.loads(x) for x in (p / "runs.jsonl").read_text().splitlines()]
        return sorted(canonical(r) for r in recs)

    assert rows(a) == rows(b)  # same runs, nothing duplicated by the resume

    def metrics(p: Path) -> dict[str, Any]:
        splits = json.loads((p / "summary.json").read_text())["splits"]
        for block in splits.values():
            block.pop("latency")  # wall-clock time is the only thing allowed to differ
        return dict(splits)

    assert metrics(a) == metrics(b)
    for name in ("runs.csv", "summary.md", "charts/recovery.svg", "charts/families.svg"):
        assert (a / name).is_file()
    traces = [json.loads(x) for x in (b / "traces.jsonl").read_text().splitlines()]
    assert traces and all({"run_key", "batch"} <= t.keys() for t in traces)


def test_csv_and_chart_render() -> None:
    rec = _rec("a", "repair", True, intervention={"type": "replace_tool_argument", "tool": "x"})
    text = to_csv([rec])
    assert text.splitlines()[0].startswith("run_key,") and "replace_tool_argument" in text
    svg = bar_chart_svg("T", "S", [("x", rate(3, 4)), ("y", rate(0, 0))])
    assert svg.startswith("<svg") and "75%" in svg and "no runs" in svg


# ------------------------------------------------------------------ GPU helpers (no GPU needed)
def test_json_stop_and_model_choice() -> None:
    assert not json_complete('{"tool": "x", "args": {')
    assert json_complete('ok {"finish": "completed"} trailing')
    assert choose_model("auto", 40.0, 4) == "Qwen/Qwen2.5-3B-Instruct"
    assert choose_model("auto", None, 4) == "Qwen/Qwen2.5-0.5B-Instruct"


class _SeededFakeGenerator:
    """Stands in for a sampling model: always takes the right steps, but the reply text
    depends on the sampling seed, like real sampling would."""

    model_id = "fake/sampler"

    def __init__(self) -> None:
        self.seeds: list[int | None] = []

    def chat(
        self, messages: list[dict[str, str]], temperature: float, max_tokens: int, seed: int | None
    ) -> dict[str, Any]:
        import re

        self.seeds.append(seed)
        ticket = messages[1]["content"]
        order = re.search(r"Order id: (\S+?)\.", ticket)
        customer = re.search(r"Customer id: (\S+?)\.", ticket)
        assert order and customer
        done = sum(m["role"] == "assistant" for m in messages)
        sku = ""
        for m in messages:
            if m["content"].startswith("Result of lookup_order: "):
                sku = json.loads(m["content"].split(": ", 1)[1].splitlines()[0])["sku"]
        actions: list[dict[str, Any]] = [
            {"tool": "lookup_order", "args": {"order_id": order.group(1)}},
            {"tool": "lookup_inventory", "args": {"sku": sku}},
            {"tool": "get_policy", "args": {"policy_key": "exchange"}},
            {
                "tool": "draft_response",
                "args": {"customer_id": customer.group(1), "text": f"reply {seed}"},
            },
            {
                "tool": "submit_resolution",
                "args": {"order_id": order.group(1), "choice": "exchange"},
            },
            {"finish": "completed"},
        ]
        text = json.dumps(actions[min(done, 5)])
        return {"text": text, "prompt_tokens": 1, "completion_tokens": 1}


def test_a_sampling_model_replays_exactly_from_a_saved_step() -> None:
    gen = _SeededFakeGenerator()
    model = TransformersModel(gen, 0.7, 64)  # type: ignore[arg-type]
    cfg = RunConfig(model_spec="hf:fake", model_id="fake/sampler", model_factory=model.reseed)
    rows = CaseRunner(cfg, None).run_case(_cases("control_exchange")[0])
    by = {r["arm"]: r for r in rows}
    assert by["baseline"]["passed"] is True
    # The replay restarts mid-run, yet samples the same reply text as the original.
    assert by["no_change"]["restart_call_index"] > 0
    assert by["no_change"]["replay_valid"] is True
    assert all(s is not None for s in gen.seeds)
