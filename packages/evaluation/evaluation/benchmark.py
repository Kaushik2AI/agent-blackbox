"""Run the FlightPath benchmark and write its artifacts.

    # CPU, scripted agent (deterministic, ~1 minute). Rebuilds every artifact from scratch:
    python -m evaluation.benchmark run --out benchmark-results/benchmark_v1/scripted

    # Real model on a GPU (resumable; see infra/batch/ for scheduler job scripts):
    python -m evaluation.benchmark run --model hf:Qwen/Qwen2.5-3B-Instruct --repeats 3 \\
        --out benchmark-results/benchmark_v1/qwen2.5-3b --resume --traces

    # Recompute summary + charts from an existing runs.jsonl:
    python -m evaluation.benchmark report --out benchmark-results/benchmark_v1/scripted

Output folder: runs.jsonl (one line per run, the source of truth), runs.csv,
summary.json, summary.md, charts/*.svg, run_config.json, and traces.jsonl with --traces
(the recorded runs, importable into the app).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from agent_harness.fixtures import BenchmarkCase, benchmark_cases
from agent_harness.model import Model

from evaluation.arms import ARMS, CaseRunner, RunConfig
from evaluation.envcheck import environment
from evaluation.metrics import headline
from evaluation.report import load_runs, pct, write_all


def build_config(args: argparse.Namespace) -> RunConfig:
    spec: str = args.model
    if spec == "stub":
        return RunConfig(
            model_spec="stub",
            model_id="stub-planner-v1",
            seed=args.seed,
            random_draws=args.draws,
            repeats=args.repeats,
            environment=environment(device_info=False),
        )
    from agent_harness.llm import PROMPT_VERSION

    decoding: dict[str, Any] = {
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "prompt_version": PROMPT_VERSION,
    }
    if spec.startswith("hf:"):
        from evaluation.hf import HFGenerator, TransformersModel

        gen = HFGenerator(spec.removeprefix("hf:"), revision=args.revision)
        print(f"loading {gen.requested} ...", flush=True)
        gen.load()
        if gen.status != "ready":
            raise SystemExit(f"model failed to load: {gen.error}")
        print(
            f"loaded {gen.model_id} on {gen.device} ({gen.dtype}) in {gen.loaded_in_s}s", flush=True
        )
        model = TransformersModel(gen, args.temperature, args.max_tokens)
        env = environment()
        env.update(device=gen.device, dtype=gen.dtype)

        def factory(seed: int) -> Model | None:
            return model.reseed(seed)

        return RunConfig(
            model_spec=spec,
            model_id=gen.model_id,
            model_revision=gen.resolved_revision,
            decoding=decoding,
            seed=args.seed,
            random_draws=args.draws,
            repeats=args.repeats,
            price_per_1k_input=args.price_in,
            price_per_1k_output=args.price_out,
            environment=env,
            model_factory=factory,
        )
    if spec == "openai":
        from agent_harness.llm import LLMConfig, OpenAICompatModel

        base, key, name = (
            os.environ.get(k, "") for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
        )
        if not (base and key and name):
            raise SystemExit("--model openai needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        api_model = OpenAICompatModel(
            LLMConfig(
                base,
                key,
                name,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout_s=240,
            )
        )
        return RunConfig(
            model_spec=spec,
            model_id=name,
            decoding=decoding,
            seed=args.seed,
            random_draws=args.draws,
            repeats=args.repeats,
            price_per_1k_input=args.price_in,
            price_per_1k_output=args.price_out,
            environment=environment(device_info=False),
            model_factory=lambda seed: api_model,
        )
    raise SystemExit(f"unknown --model {spec!r}: use stub, openai or hf:<model id>")


def select_cases(args: argparse.Namespace) -> list[BenchmarkCase]:
    cases = list(benchmark_cases(args.benchmark))
    if not cases:
        raise SystemExit(f"no cases for {args.benchmark}; run python -m evaluation.dataset --write")
    if args.split != "all":
        cases = [c for c in cases if c.split == args.split]
    if args.family:
        cases = [c for c in cases if c.family in args.family]
    if args.limit:
        cases = cases[: args.limit]
    return cases


def cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    runs_path = out / "runs.jsonl"
    cfg = build_config(args)
    cases = select_cases(args)
    done: set[tuple[str, int]] = set()
    if runs_path.exists() and args.resume:
        for r in load_runs(runs_path):
            if r.get("model_spec") != cfg.model_spec or r.get("seed") != cfg.seed:
                raise SystemExit(
                    f"{runs_path} holds runs with a different model or seed; use a new --out"
                )
            done.add((r["case_id"], int(r["repeat"])))
        print(f"resuming: {len({c for c, _ in done})} cases already in {runs_path}")
    elif runs_path.exists():
        runs_path.unlink()  # a fresh run rebuilds every artifact from scratch
    out.mkdir(parents=True, exist_ok=True)
    traces = (out / "traces.jsonl").open("a" if args.resume else "w") if args.traces else None

    def trace_sink(key: str, batch: dict[str, Any]) -> None:
        if traces is not None:
            traces.write(json.dumps({"run_key": key, "batch": batch}) + "\n")

    config_doc = {k: v for k, v in vars(args).items() if k not in ("func",)} | {
        "model_id": cfg.model_id,
        "model_revision": cfg.model_revision,
        "environment": cfg.environment,
    }
    (out / "run_config.json").write_text(json.dumps(config_doc, indent=2, sort_keys=True) + "\n")

    runner = CaseRunner(cfg, trace_sink if traces else None)
    started = time.time()
    with runs_path.open("a") as fh:
        for i, case in enumerate(cases, 1):
            if all((case.case_id, rep) in done for rep in range(cfg.repeats)):
                continue
            records = runner.run_case(case, tuple(args.arms))
            records = [r for r in records if (r["case_id"], r["repeat"]) not in done]
            # One case at a time, flushed: an interrupted job resumes at the next case.
            fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
            fh.flush()
            os.fsync(fh.fileno())
            if traces is not None:
                traces.flush()
            passed = sum(1 for r in records if r["arm"] == "baseline" and r["passed"])
            print(
                f"[{i}/{len(cases)}] {case.case_id}: baseline {passed}/{cfg.repeats} passed, "
                f"{len(records)} runs",
                flush=True,
            )
    if traces is not None:
        traces.close()
    summary = write_all(load_runs(runs_path), out, runs_written=True)
    print(f"\nfinished in {time.time() - started:.1f}s; artifacts in {out}")
    for name, value in headline(summary).items():
        print(f"  {name:<16} {pct(value)}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    out = Path(args.out)
    summary = write_all(load_runs(out / "runs.jsonl"), out, runs_written=True)
    for name, value in headline(summary).items():
        print(f"  {name:<16} {pct(value)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.benchmark",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(required=True)
    run = sub.add_parser("run", help="run the benchmark and write all artifacts")
    run.add_argument("--out", default="benchmark-results/benchmark_v1/scripted")
    run.add_argument("--benchmark", default="benchmark_v1")
    run.add_argument("--model", default="stub", help="stub | openai | hf:<model id>")
    run.add_argument("--revision", default=None, help="model revision (commit) for hf: models")
    run.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    run.add_argument("--family", action="append", help="only these families (repeatable)")
    run.add_argument("--limit", type=int, default=0, help="only the first N cases (smoke tests)")
    run.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    run.add_argument("--draws", type=int, default=5, help="random-change draws per failed case")
    run.add_argument(
        "--repeats", type=int, default=1, help="baseline repeats per case (real models)"
    )
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--max-tokens", type=int, default=256)
    run.add_argument("--price-in", type=float, default=None, help="USD per 1k input tokens")
    run.add_argument("--price-out", type=float, default=None, help="USD per 1k output tokens")
    run.add_argument("--resume", action="store_true", help="continue an interrupted run in --out")
    run.add_argument("--traces", action="store_true", help="also write traces.jsonl for import")
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report", help="recompute summary and charts from runs.jsonl")
    rep.add_argument("--out", default="benchmark-results/benchmark_v1/scripted")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
