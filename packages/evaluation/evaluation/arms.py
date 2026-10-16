"""Run one benchmark case through the four arms and return one record per run.

Arms (all on the same case, same agent, same world):
  baseline   the agent from scratch
  no_change  restart from a saved step with nothing changed (does replay reproduce?)
  repair     restart from the failing step with FlightPath's suggested change
  random     restart from a random step with a random valid change (R draws)

Each run is traced by the real SDK into memory, so detectors see exactly what the app
would store, and the batches can be written out for import into the app.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_harness import __version__ as harness_version
from agent_harness.fixtures import BenchmarkCase
from agent_harness.model import Model
from agent_harness.runner import RunResult
from analysis_engine.detectors import analyze
from blackbox_sdk.exporters import MemoryExporter
from blackbox_sdk.integrations.agent_harness import replay_traced, run_traced

from evaluation import __version__ as evaluation_version
from evaluation.repair import Change, Checkpoints, plan_repair, random_intervention, restart_point

RECORD_SCHEMA = "flightpath-eval-run/1"
ARMS = ("baseline", "no_change", "repair", "random")


@dataclass
class RunConfig:
    """Everything that determines a benchmark run (recorded with every row)."""

    model_spec: str = "stub"
    model_id: str = "stub-planner-v1"
    model_revision: str | None = None
    decoding: dict[str, Any] | None = None
    seed: int = 7
    random_draws: int = 5
    repeats: int = 1
    price_per_1k_input: float | None = None
    price_per_1k_output: float | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    # Builds the model for a run; None means the fixture's scripted stub.
    model_factory: Callable[[int], Model | None] = field(default=lambda seed: None, repr=False)


def run_key(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _usage(batches: list[dict[str, Any]]) -> tuple[int, int]:
    for batch in batches:
        usage = (batch.get("execution") or {}).get("attributes", {}).get("usage")
        if usage:
            return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    return 0, 0


def _events(batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for b in batches for e in b.get("events", [])]


def _cost(cfg: RunConfig, tin: int, tout: int) -> float | None:
    if cfg.price_per_1k_input is None or cfg.price_per_1k_output is None:
        return None
    return round(tin / 1000 * cfg.price_per_1k_input + tout / 1000 * cfg.price_per_1k_output, 6)


class CaseRunner:
    def __init__(self, cfg: RunConfig, trace_sink: Callable[[str, dict[str, Any]], None] | None):
        self.cfg = cfg
        self.trace_sink = trace_sink

    def _record(
        self,
        case: BenchmarkCase,
        arm: str,
        repeat: int,
        draw: int | None,
        run: RunResult,
        batches: list[dict[str, Any]],
        execution_id: str,
        parent: str | None,
        change: Change | None,
        restart: int | None,
        findings: list[str] | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = run_key(
            case.benchmark_version, case.case_id, arm, repeat, draw,
            self.cfg.model_spec, self.cfg.model_revision, self.cfg.seed,
        )  # fmt: skip
        tin, tout = _usage(batches)
        if self.trace_sink is not None:
            for batch in batches:
                self.trace_sink(key, batch)
        record: dict[str, Any] = {
            "schema": RECORD_SCHEMA,
            "run_key": key,
            "benchmark_version": case.benchmark_version,
            "case_id": case.case_id,
            "family": case.family,
            "split": case.split,
            "arm": arm,
            "repeat": repeat,
            "draw": draw,
            "seed": self.cfg.seed,
            "model_spec": self.cfg.model_spec,
            "model_id": self.cfg.model_id,
            "model_revision": self.cfg.model_revision,
            "decoding": self.cfg.decoding,
            "determinism": run.determinism,
            "agent_version": harness_version,
            "evaluation_version": evaluation_version,
            "fixture_version": case.fixture.fixture_version,
            "fixture_sha256": case.fixture.content_hash,
            "passed": run.verifier.passed,
            "termination": run.termination,
            "tool_calls": run.tool_calls,
            "error_codes": run.error_codes,
            "verifier_reasons": run.verifier.reasons,
            "findings": findings,
            "expected_findings": case.expected_findings,
            "restart_call_index": restart,
            "intervention": change.describe() if change else None,
            "elapsed_ms": run.elapsed_ms,
            "tokens_in": tin,
            "tokens_out": tout,
            "cost_usd": _cost(self.cfg, tin, tout),
            "execution_id": execution_id,
            "parent_execution_id": parent,
            "environment": self.cfg.environment,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if extra:
            record.update(extra)
        return record

    def _fork(
        self,
        case: BenchmarkCase,
        checkpoints: Checkpoints,
        restart: int,
        change: Change | None,
        parent: str,
        seed: int,
    ) -> tuple[RunResult, list[dict[str, Any]], str]:
        mem = MemoryExporter()
        fork_id = str(uuid.uuid4())
        run, _ = replay_traced(
            checkpoints[restart],
            [change.intervention] if change else [],
            mem,
            fork_execution_id=fork_id,
            parent_execution_id=parent,
            extra_attributes={"benchmark": {"case_id": case.case_id, "restart": restart}},
            project="benchmark",
            model=self.cfg.model_factory(seed),
        )
        return run, mem.batches, fork_id

    def run_case(self, case: BenchmarkCase, arms: tuple[str, ...] = ARMS) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for repeat in range(self.cfg.repeats):
            base_seed = int(run_key(self.cfg.seed, case.case_id, repeat), 16) % (2**31)
            checkpoints: Checkpoints = {}

            def collect(
                event_type: str, data: dict[str, Any], cps: Checkpoints = checkpoints
            ) -> None:
                if event_type == "checkpoint":
                    cps[int(data["call_index"])] = data["document"]

            mem = MemoryExporter()
            base, _ = run_traced(
                case.case_id,
                mem,
                capture_content=True,
                project="benchmark",
                model=self.cfg.model_factory(base_seed),
                sink=collect,
                extra_attributes={"benchmark": {"case_id": case.case_id, "arm": "baseline"}},
            )
            base_id = str(mem.batches[0]["execution"]["execution_id"])
            findings: list[str] = sorted({str(f.category) for f in analyze(_events(mem.batches))})
            repair = None if base.verifier.passed else plan_repair(base, checkpoints)
            restart = restart_point(base, repair, checkpoints) if checkpoints else None
            if "baseline" in arms:
                out.append(
                    self._record(case, "baseline", repeat, None, base, mem.batches, base_id,
                                 None, None, None, findings)
                )  # fmt: skip
            if not checkpoints or restart is None:
                continue
            if "no_change" in arms:
                run, batches, fid = self._fork(case, checkpoints, restart, None, base_id, base_seed)
                same = run.verifier.passed == base.verifier.passed and (
                    run.termination == base.termination
                    and run.sandbox_effects == base.sandbox_effects
                )
                out.append(
                    self._record(case, "no_change", repeat, None, run, batches, fid, base_id,
                                 None, restart, None,
                                 {"replay_valid": same, "baseline_passed": base.verifier.passed})
                )  # fmt: skip
            if base.verifier.passed:
                continue  # repair and random are measured on failed runs
            if "repair" in arms:
                if repair is None:
                    out.append(
                        self._skipped(case, "repair", repeat, None, base_id, "no repair rule")
                    )
                else:
                    run, batches, fid = self._fork(
                        case, checkpoints, repair.call_index, repair, base_id, base_seed
                    )
                    out.append(
                        self._record(case, "repair", repeat, None, run, batches, fid, base_id,
                                     repair, repair.call_index, None)
                    )  # fmt: skip
            if "random" in arms:
                for draw in range(self.cfg.random_draws):
                    rng = random.Random(int(run_key("random", base_seed, draw), 16))
                    change = random_intervention(base, checkpoints, rng)
                    run, batches, fid = self._fork(
                        case, checkpoints, change.call_index, change, base_id, base_seed + draw + 1
                    )
                    out.append(
                        self._record(case, "random", repeat, draw, run, batches, fid, base_id,
                                     change, change.call_index, None)
                    )  # fmt: skip
        return out

    def _skipped(
        self, case: BenchmarkCase, arm: str, repeat: int, draw: int | None, parent: str, why: str
    ) -> dict[str, Any]:
        """A row that records an arm could not run (it still counts in denominators)."""
        key = run_key(
            case.benchmark_version, case.case_id, arm, repeat, draw,
            self.cfg.model_spec, self.cfg.model_revision, self.cfg.seed,
        )  # fmt: skip
        return {
            "schema": RECORD_SCHEMA,
            "run_key": key,
            "benchmark_version": case.benchmark_version,
            "case_id": case.case_id,
            "family": case.family,
            "split": case.split,
            "arm": arm,
            "repeat": repeat,
            "draw": draw,
            "seed": self.cfg.seed,
            "model_spec": self.cfg.model_spec,
            "model_id": self.cfg.model_id,
            "model_revision": self.cfg.model_revision,
            "decoding": self.cfg.decoding,
            "agent_version": harness_version,
            "evaluation_version": evaluation_version,
            "fixture_version": case.fixture.fixture_version,
            "fixture_sha256": case.fixture.content_hash,
            "passed": False,
            "skipped": why,
            "parent_execution_id": parent,
            "expected_findings": case.expected_findings,
            "environment": self.cfg.environment,
            "created_at": datetime.now(UTC).isoformat(),
        }


def base_environment() -> dict[str, Any]:
    return {"python": platform.python_version(), "platform": platform.platform(terse=True)}


def canonical(record: dict[str, Any]) -> str:
    """Fields that must be identical between two runs of a deterministic benchmark."""
    volatile = {"elapsed_ms", "execution_id", "parent_execution_id", "created_at", "environment"}
    return json.dumps({k: v for k, v in record.items() if k not in volatile}, sort_keys=True)
