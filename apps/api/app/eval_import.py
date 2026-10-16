"""Import benchmark results into the app.

    python -m app.eval_import benchmark-results/benchmark_v1/scripted
    python -m app.eval_import /path/to/gpu-results/qwen2.5-3b     # copied back from a GPU job

Validates every record, rejects anything secret-shaped, dedupes on run_key (safe to run
twice) and ingests traces.jsonl when present, so each run can be opened in the app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.db import session_scope
from app.services.evaluations import import_folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval_import")
    parser.add_argument("folder", type=Path, help="results folder (or a runs.jsonl file)")
    args = parser.parse_args(argv)
    settings = get_settings()
    with session_scope() as session:
        report = import_folder(
            session, args.folder.resolve(), max_payload_bytes=settings.max_event_payload_bytes
        )
    print(
        f"read {report.read} records: {report.imported} imported, "
        f"{report.duplicates} already present, {len(report.rejected)} rejected; "
        f"traces: {report.traces_ingested} ingested, {report.traces_rejected} skipped"
    )
    for problem in report.rejected[:20]:
        print(f"  rejected {problem}")
    for src in sorted(report.sources):
        print(f"  source {src}  (open /benchmark in the app)")
    return 1 if report.rejected and not report.imported and not report.duplicates else 0


if __name__ == "__main__":
    sys.exit(main())
