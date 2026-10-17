"""Benchmark import and read API against real Postgres: validation, secret rejection,
dedupe, trace ingestion, summaries and CSV."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from evaluation import benchmark
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client(migrated_db: str) -> Iterator[TestClient]:
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("bench")
    args = ["run", "--out", str(out), "--family", "invalid_argument", "--family",
            "control_exchange", "--split", "heldout", "--draws", "2", "--traces"]  # fmt: skip
    assert benchmark.main(args) == 0
    return out


def _import(folder: Path) -> object:
    from app.db import session_scope
    from app.services.evaluations import import_folder

    with session_scope() as s:
        return import_folder(s, folder, max_payload_bytes=32_000)


def test_import_is_idempotent_and_runs_open_in_the_app(client: TestClient, results: Path) -> None:
    first = _import(results)
    lines = len((results / "runs.jsonl").read_text().splitlines())
    assert first.imported == lines and not first.rejected  # type: ignore[attr-defined]
    assert first.traces_ingested > 0  # type: ignore[attr-defined]
    again = _import(results)
    assert again.imported == 0 and again.duplicates == lines  # type: ignore[attr-defined]

    sources = client.get("/api/v1/evaluations").json()
    assert len(sources) == 1
    src = sources[0]
    assert src["model_id"] == "stub-planner-v1" and src["cases"] == 4
    summary = client.get(f"/api/v1/evaluations/{src['source']}").json()
    allsplit = summary["splits"]["all"]
    assert allsplit["success"]["n"] == 4
    assert allsplit["repair_recovery"]["k"] == allsplit["failed_runs"]
    row = next(r for r in summary["case_rows"] if r["family"] == "invalid_argument")
    assert row["baseline"]["passed"] is False and row["repair"]["passed"] is True
    # The recorded baseline run is a normal run in the app.
    run = client.get(f"/api/v1/executions/{row['baseline']['execution_id']}")
    assert run.status_code == 200 and run.json()["task_id"] == row["case_id"]

    csv = client.get(f"/api/v1/evaluations/{src['source']}/runs.csv")
    assert csv.status_code == 200 and csv.text.startswith("run_key,")
    assert client.get("/api/v1/evaluations/nope").status_code == 404


def test_invalid_and_secret_records_are_rejected(client: TestClient, tmp_path: Path) -> None:
    good = {
        "schema": "flightpath-eval-run/1", "run_key": "k1", "benchmark_version": "b",
        "case_id": "c", "family": "f", "split": "dev", "arm": "baseline", "repeat": 0,
        "seed": 1, "model_spec": "stub", "model_id": "m", "agent_version": "a",
        "passed": True, "expected_findings": [],
    }  # fmt: skip
    leaky = {**good, "run_key": "k2", "note": "token hf_abcdefghijklmnopqrstuvwxyz0123456789"}
    bad = {**good, "run_key": "k3", "arm": "teleport"}
    (tmp_path / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in (good, leaky, bad)) + "\nnot json\n"
    )
    rep = _import(tmp_path)
    assert rep.imported == 1  # type: ignore[attr-defined]
    assert len(rep.rejected) == 3  # type: ignore[attr-defined]
    assert any("secret" in r for r in rep.rejected)  # type: ignore[attr-defined]


def test_results_without_traces_do_not_link_to_missing_runs(
    client: TestClient, results: Path, tmp_path: Path
) -> None:
    # traces.jsonl is large and not committed, so a cloned results folder often has only
    # runs.jsonl. Its cases must say "not imported" rather than link to a run that is absent.
    records = [json.loads(x) for x in (results / "runs.jsonl").read_text().splitlines() if x]
    for r in records:  # a separate source whose runs were never recorded in this database
        r["run_key"] += "-notrace"
        r["model_spec"] = "stub-without-traces"
        if r.get("execution_id"):
            r["execution_id"] = str(uuid.uuid4())
    (tmp_path / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    rep = _import(tmp_path)
    assert rep.imported == len(records) and rep.traces_ingested == 0  # type: ignore[attr-defined]
    src = next(
        s["source"]
        for s in client.get("/api/v1/evaluations").json()
        if s["model_spec"] == "stub-without-traces"
    )
    summary = client.get(f"/api/v1/evaluations/{src}").json()
    assert summary["case_rows"]
    for row in summary["case_rows"]:
        for arm in ("baseline", "repair"):
            if row.get(arm):
                assert row[arm]["execution_id"] is None
