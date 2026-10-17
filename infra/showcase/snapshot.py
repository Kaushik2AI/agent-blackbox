"""Freeze a running FlightPath stack into static JSON for the read-only showcase.

    python infra/showcase/snapshot.py --api http://127.0.0.1:8000 --out apps/web/public/snapshot

Run against a fresh stack that has the demo runs and benchmark results loaded (the Pages
workflow does this). The script:

1. plays every scripted live scenario, so the showcase's live demo can replay it step by step;
2. applies FlightPath's suggested fix to every failed run that has one, so "Try the fix"
   opens a real before/after comparison;
3. writes every read the web app makes as a JSON file (layout in apps/web/lib/showcase.ts).

Everything written comes from the real API; nothing is invented. The web app built with
NEXT_PUBLIC_SHOWCASE=1 reads these files instead of calling the API.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

API = "/api/v1"
PER_RUN = ("timeline", "graph", "findings", "checkpoints", "replays", "suggested-fix")


class Snapshot:
    def __init__(self, base: str, out: Path) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=60)
        self.out = out
        self.files = 0

    # ------------------------------------------------------------------ io
    def get(self, path: str, **params: Any) -> Any:
        resp = self.http.get(
            path, params={k: v for k, v in params.items() if v is not None}
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        resp = self.http.post(path, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def write(self, rel: str, data: Any) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            path.write_text(data)
        else:
            path.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True))
        self.files += 1

    # ------------------------------------------------------------------ steps
    def play_live_scenarios(self) -> dict[str, str]:
        cfg = self.get(f"{API}/live/config")
        played: dict[str, str] = {}
        for sc in cfg["scenarios"]:
            if "scripted" not in sc["brains"]:
                continue
            run = self.post(
                f"{API}/live-runs", {"scenario": sc["id"], "brain": "scripted"}
            )
            live_id = run["live_id"]
            for _ in range(300):
                run = self.get(f"{API}/live-runs/{live_id}", after=0)
                if run["status"] in ("done", "error"):
                    break
                time.sleep(0.2)
            if run["status"] != "done":
                raise RuntimeError(
                    f"live scenario {sc['id']} ended {run['status']}: {run['error']}"
                )
            self.write(f"live/{sc['id']}.json", run)
            played[sc["id"]] = run["execution_id"]
        return played

    def all_executions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            page = self.get(f"{API}/executions", limit=200, offset=len(items))
            items += page["items"]
            if len(items) >= page["total"] or not page["items"]:
                return items

    def apply_suggested_fixes(
        self, executions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        index = []
        for ex in executions:
            if ex["status"] != "failed" or ex["parent_execution_id"]:
                continue
            fix = self.get(f"{API}/executions/{ex['id']}/suggested-fix")
            if not fix.get("available"):
                continue
            job = self.post(
                f"{API}/replays",
                {
                    **fix["request"],
                    "mode": "deterministic",
                    "sandbox": "fixture_only",
                    "idempotency_key": f"showcase-{uuid.uuid4()}",
                },
            )
            for _ in range(300):
                job = self.get(f"{API}/replays/{job['job_id']}")
                if job["status"] in ("succeeded", "failed"):
                    break
                time.sleep(0.2)
            index.append({"request": fix["request"], "job_id": job["job_id"]})
        return index

    def dump(
        self, live: dict[str, str], fixes: list[dict[str, Any]], git_sha: str
    ) -> None:
        self.write("health.json", self.get("/healthz") | {"environment": "showcase"})
        self.write("live-config.json", self.get(f"{API}/live/config"))
        self.write("agent-versions.json", self.get(f"{API}/agent-versions"))
        for project in (None, "demo", "benchmark"):
            self.write(
                f"overview/{project or 'all'}.json",
                self.get(f"{API}/overview", project=project),
            )

        executions = self.all_executions()
        self.write("executions.json", executions)
        jobs: set[str] = set()
        for ex in executions:
            eid = ex["id"]
            self.write(
                f"executions/{eid}/detail.json", self.get(f"{API}/executions/{eid}")
            )
            for part in PER_RUN:
                data = self.get(f"{API}/executions/{eid}/{part}")
                self.write(f"executions/{eid}/{part}.json", data)
                if part == "replays":
                    jobs.update(j["job_id"] for j in data)
        for job in sorted(jobs):
            detail = self.get(f"{API}/replays/{job}")
            self.write(f"replays/{job}/job.json", detail)
            if detail["status"] == "succeeded":
                self.write(
                    f"replays/{job}/comparison.json",
                    self.get(f"{API}/replays/{job}/comparison"),
                )

        sources = self.get(f"{API}/evaluations")
        self.write("evaluations.json", sources)
        for src in sources:
            sid = src["source"]
            self.write(f"evaluations/{sid}.json", self.get(f"{API}/evaluations/{sid}"))
            csv = self.http.get(f"{API}/evaluations/{sid}/runs.csv")
            csv.raise_for_status()
            self.write(f"evaluations/{sid}/runs.csv", csv.text)

        self.write(
            "index.json",
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "git_sha": git_sha,
                "executions": [e["id"] for e in executions],
                "replays": sorted(jobs),
                "live": live,
                "fixes": fixes,
            },
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python infra/showcase/snapshot.py")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default="apps/web/public/snapshot", type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        sha = ""
    snap = Snapshot(args.api, args.out)
    started = time.perf_counter()
    live = snap.play_live_scenarios()
    fixes = snap.apply_suggested_fixes(snap.all_executions())
    snap.dump(live, fixes, sha)
    size = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(
        f"snapshot: {snap.files} files, {size / 1e6:.1f} MB, {len(live)} live scenarios, "
        f"{len(fixes)} fixes applied, {time.perf_counter() - started:.0f}s -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
