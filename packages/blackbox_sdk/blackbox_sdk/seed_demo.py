"""Seed the database with REAL demo-agent runs, recorded by the SDK and sent through the
ingest API (nothing is written to the DB directly).

    python -m blackbox_sdk.seed_demo                      # every fixture once
    python -m blackbox_sdk.seed_demo --repeat 3 --capture-content
    python -m blackbox_sdk.seed_demo --jsonl runs.jsonl   # offline: write batches to a file

--capture-content stores argument/result VALUES (after redaction). The demo fixtures are
synthetic, so this is safe here; for real agents leave it off (metadata only).
"""

from __future__ import annotations

import argparse
import os
import sys

from agent_harness.fixtures import list_fixtures

from blackbox_sdk.exporters import ExportError, HttpExporter, JsonlExporter
from blackbox_sdk.integrations.agent_harness import Exporter, run_traced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m blackbox_sdk.seed_demo")
    parser.add_argument(
        "--api", default=os.environ.get("API_INTERNAL_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--jsonl", help="write batches to this file instead of the API")
    parser.add_argument("--fixtures", help="comma-separated fixture ids (default: all)")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--capture-content", action="store_true")
    args = parser.parse_args(argv)

    exporter: Exporter = JsonlExporter(args.jsonl) if args.jsonl else HttpExporter(args.api)
    fixtures = args.fixtures.split(",") if args.fixtures else list_fixtures()
    target = args.jsonl or args.api
    print(
        f"Recording {len(fixtures)} fixture(s) x{args.repeat} -> {target} "
        f"(capture: {'content' if args.capture_content else 'metadata only'})"
    )
    try:
        for fixture_id in fixtures:
            for _ in range(args.repeat):
                run, responses = run_traced(
                    fixture_id, exporter, capture_content=args.capture_content
                )
                new = sum(r.get("events_new", 0) for r in responses)
                verdict = "pass" if run.verifier.passed else "fail"
                print(f"  {fixture_id:<30} {verdict:<5} {run.execution_id}  events stored: {new}")
    except ExportError as exc:
        print(f"\nERROR: {exc}\nIs the API running? Start it with `make dev`.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
