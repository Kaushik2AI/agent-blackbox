"""CLI for the demo agent.

    python -m agent_harness.run_demo --list
    python -m agent_harness.run_demo --fixture invalid_inventory_argument
    python -m agent_harness.run_demo --fixture exchange_success --json
    python -m agent_harness.run_demo --all            # every fixture vs. its expected baseline
    python -m agent_harness.run_demo --all --repeat 10

Exit codes: single fixture -> 0 if the ground-truth verifier passed, 1 if it failed.
--all -> 0 if every fixture behaved exactly as its expected baseline on every repeat.
"""

from __future__ import annotations

import argparse
import json
import sys

from agent_harness.fixtures import list_fixtures, load_fixture
from agent_harness.runner import RunResult, run_fixture

_TTY = sys.stdout.isatty()
GREEN, RED, DIM, BOLD, RESET = (
    ("\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m") if _TTY else ("",) * 5
)


def _color(ok: bool, text: str) -> str:
    return f"{GREEN if ok else RED}{text}{RESET}"


def _short(value: object, width: int = 45) -> str:
    text = json.dumps(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def print_run(r: RunResult) -> None:
    print(
        f"{BOLD}{r.fixture_id}{RESET} (v{r.fixture_version}, model {r.model_name}, {r.determinism})"
    )
    print(f"{DIM}execution {r.execution_id}{RESET}")
    for step in r.history:
        status = "ok " if step["ok"] else step["error_code"]
        print(
            f"  #{step['call_index']:<2} {step['tool']:<18} {_short(step['args']):<45} "
            f"{_color(step['ok'], status)}"
        )
    print(
        f"  termination: {r.termination}   tool calls: {r.tool_calls}   "
        f"elapsed: {r.elapsed_ms:.1f} ms"
    )
    for effect in r.sandbox_effects:
        print(f"  sandbox {effect['kind']}: {_short(effect['payload'], 90)}")
    verdict = "PASSED" if r.verifier.passed else "FAILED"
    reasons = f" ({', '.join(r.verifier.reasons)})" if r.verifier.reasons else ""
    print(f"  verifier: {_color(r.verifier.passed, verdict)}{reasons}\n")


def matches_baseline(r: RunResult) -> bool:
    b = load_fixture(r.fixture_id).expected_baseline
    return (
        r.verifier.passed == b.verifier_passed
        and r.termination == b.termination
        and r.error_codes == b.error_codes
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_harness.run_demo")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", help="fixture id to run")
    group.add_argument("--all", action="store_true", help="run every fixture")
    group.add_argument("--list", action="store_true", help="list fixtures")
    parser.add_argument("--json", action="store_true", help="print the full RunResult as JSON")
    parser.add_argument("--repeat", type=int, default=1, help="repeat runs (determinism check)")
    args = parser.parse_args(argv)

    if args.list:
        for fid in list_fixtures():
            fx = load_fixture(fid)
            print(f"{fid:<30} v{fx.fixture_version}  {fx.description}")
        return 0

    if args.fixture:
        try:
            load_fixture(args.fixture)
        except KeyError as exc:
            print(exc.args[0], file=sys.stderr)
            return 2
        runs = [run_fixture(args.fixture) for _ in range(args.repeat)]
        if args.json:
            print(runs[-1].model_dump_json(indent=2))
        else:
            print_run(runs[-1])
        if args.repeat > 1:
            same = all(r.outcome_signature() == runs[0].outcome_signature() for r in runs)
            print(f"repeat x{args.repeat}: {'identical' if same else 'DIFFERENT'} outcomes")
            if not same:
                return 1
        return 0 if runs[-1].verifier.passed else 1

    all_ok = True
    print(f"{'fixture':<30} {'verifier':<9} {'termination':<17} {'errors':<16} baseline")
    for fid in list_fixtures():
        runs = [run_fixture(fid) for _ in range(args.repeat)]
        stable = all(r.outcome_signature() == runs[0].outcome_signature() for r in runs)
        ok = stable and all(matches_baseline(r) for r in runs)
        all_ok &= ok
        r = runs[0]
        label = f"match x{args.repeat}" if ok else ("UNSTABLE" if not stable else "MISMATCH")
        print(
            f"{fid:<30} {'pass' if r.verifier.passed else 'fail':<9} {r.termination:<17} "
            f"{','.join(r.error_codes) or '-':<16} {_color(ok, label)}"
        )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
