"""M5 findings + M6 replay against real Postgres/Redis: eligibility, interventions,
lineage, immutability, idempotency, crash recovery, network isolation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agent_harness.tools import TOOLS
from blackbox_sdk.exporters import HttpExporter
from blackbox_sdk.integrations.agent_harness import run_traced
from fastapi.testclient import TestClient
from redis import Redis
from rq import SimpleWorker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def client(migrated_db: str) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def db(migrated_db: str) -> Iterator[Session]:
    with Session(create_engine(migrated_db)) as s:
        yield s


def seed(client: TestClient, fixture: str, content: bool = True) -> str:
    run, _ = run_traced(fixture, HttpExporter("", client=client), capture_content=content)
    return run.execution_id


def checkpoint(client: TestClient, eid: str, step: int) -> dict[str, Any]:
    cps = client.get(f"/api/v1/executions/{eid}/checkpoints").json()
    return next(c for c in cps if c["step_index"] == step)


def sku_fix(eid: str, cp: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "source_execution_id": eid,
        "checkpoint_id": cp["checkpoint_id"],
        "intervention": {
            "type": "replace_tool_argument",
            "target_span_id": cp["target_span_id"],
            "field": "sku",
            "value": "SKU-RED-004",
            "remove_fields": ["product_name"],
        },
        **extra,
    }


def run_job(job_id: str) -> dict[str, Any]:
    from app.db import session_scope
    from app.services.replay import execute_job

    with session_scope() as s:
        job = execute_job(s, uuid.UUID(job_id))
        return {"status": job.status.value, "error": job.error, "result": job.result_json}


def fingerprint(eid: str) -> str:
    from app.db import session_scope
    from app.services.replay import fingerprint_rows

    with session_scope() as s:
        return fingerprint_rows(s, uuid.UUID(eid))


# ------------------------------------------------------------------ M5 findings
def test_findings_are_stored_at_ingest_and_cite_real_events(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument", content=False)
    body = client.get(f"/api/v1/executions/{eid}/findings").json()
    cats = {f["category"] for f in body["findings"]}
    assert cats == {"tool_schema_mismatch", "retry_loop", "budget_exhausted"}
    events = {
        e["event_id"] for e in client.get(f"/api/v1/executions/{eid}/timeline").json()["events"]
    }
    spans = {n["id"] for n in client.get(f"/api/v1/executions/{eid}/graph").json()["nodes"]}
    for f in body["findings"]:
        assert set(f["evidence_event_ids"]) <= events and set(f["evidence_span_ids"]) <= spans
        assert f["kind"] == "verified" and f["detector_version"] == "1.1"


def test_healthy_run_has_no_findings_and_identity_bug_is_caught(client: TestClient) -> None:
    ok = seed(client, "exchange_success", content=False)
    assert client.get(f"/api/v1/executions/{ok}/findings").json()["findings"] == []
    bad = seed(client, "wrong_order_identity", content=False)
    (f,) = client.get(f"/api/v1/executions/{bad}/findings").json()["findings"]
    assert f["category"] == "state_identity_mismatch" and f["severity"] == "critical"


def test_findings_policy_can_deny_a_project(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import _clear_caches

    eid = seed(client, "invalid_inventory_argument", content=False)
    monkeypatch.setenv("FINDINGS_ALLOWED_PROJECTS", "some-other-project")
    _clear_caches()
    try:
        assert client.get(f"/api/v1/executions/{eid}/findings").status_code == 403
    finally:
        monkeypatch.delenv("FINDINGS_ALLOWED_PROJECTS")
        _clear_caches()


# ------------------------------------------------------------------ checkpoints
def test_checkpoints_eligible_only_when_state_was_captured(client: TestClient) -> None:
    content = client.get(
        f"/api/v1/executions/{seed(client, 'invalid_inventory_argument')}/checkpoints"
    ).json()
    assert len(content) == 8 and all(c["eligible"] for c in content)
    assert content[1]["tool_name"] == "lookup_inventory"
    assert content[1]["recorded_arguments"] == {"product_name": "red backpack"}
    meta = client.get(
        f"/api/v1/executions/{seed(client, 'invalid_inventory_argument', False)}/checkpoints"
    ).json()
    assert meta and not any(c["eligible"] for c in meta)
    assert "metadata-only" in meta[0]["reasons"][0]


# ------------------------------------------------------------------ flagship replay
def test_flagship_fix_recovers_the_run_and_source_stays_immutable(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument")
    before = fingerprint(eid)
    cp = checkpoint(client, eid, 1)
    resp = client.post("/api/v1/replays", json=sku_fix(eid, cp))
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "queued" and job["replay_level"] == "controlled_counterfactual"
    assert job["intervention"]["arguments"] == {"sku": "SKU-RED-004"}
    assert job["intervention"]["original_arguments"] == {"product_name": "red backpack"}

    outcome = run_job(job["job_id"])
    assert outcome["status"] == "succeeded", outcome
    assert outcome["result"]["fork_verifier_passed"] is True

    fork = client.get(f"/api/v1/executions/{job['fork_execution_id']}").json()
    assert fork["status"] == "succeeded" and fork["parent_execution_id"] == eid
    assert fingerprint(eid) == before  # byte-for-byte unchanged at domain level
    assert (
        client.get(f"/api/v1/executions/{job['fork_execution_id']}/findings").json()["findings"]
        == []
    )

    cmp = client.get(f"/api/v1/replays/{job['job_id']}/comparison").json()
    assert cmp["outcome_changed"] and cmp["source"]["status"] == "failed"
    assert cmp["fork"]["status"] == "succeeded" and cmp["first_divergence_call_index"] == 1
    step1 = next(s for s in cmp["steps"] if s["call_index"] == 1)
    assert step1["intervened"] and step1["source"]["error_code"] == "SKU_REQUIRED"
    assert step1["fork"]["arguments"] == {"sku": "SKU-RED-004"}
    assert next(s for s in cmp["steps"] if s["call_index"] == 0)["inherited"]
    assert any(d["path"].startswith("$[1]") and d["change"] == "added" for d in cmp["state_diff"])
    assert cmp["fork"]["metrics"]["tool_calls_executed_in_fork"] == 4


def test_plain_checkpoint_replay_reproduces_the_original(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument")
    cp = checkpoint(client, eid, 1)
    job = client.post(
        "/api/v1/replays", json={"source_execution_id": eid, "checkpoint_id": cp["checkpoint_id"]}
    ).json()
    assert job["replay_level"] == "checkpoint_replay"
    assert run_job(job["job_id"])["result"]["fork_verifier_passed"] is False
    cmp = client.get(f"/api/v1/replays/{job['job_id']}/comparison").json()
    assert not cmp["outcome_changed"] and cmp["first_divergence_call_index"] is None


def test_replace_tool_result_recovers_persistent_timeout(client: TestClient) -> None:
    eid = seed(client, "persistent_inventory_timeout")
    cp = checkpoint(client, eid, 1)
    result = {
        "sku": "SKU-RED-004",
        "available": True,
        "quantity": 12,
        "as_of": "2026-10-01T09:00:00Z",
    }
    job = client.post(
        "/api/v1/replays",
        json={
            "source_execution_id": eid,
            "checkpoint_id": cp["checkpoint_id"],
            "intervention": {
                "type": "replace_tool_result",
                "target_span_id": cp["target_span_id"],
                "result": result,
            },
        },
    ).json()
    assert run_job(job["job_id"])["result"]["fork_verifier_passed"] is True


# ------------------------------------------------------------------ rejections
@pytest.mark.parametrize(
    "case",
    ["schema", "before_checkpoint", "not_a_tool", "bad_result", "stochastic", "foreign_checkpoint"],
)
def test_invalid_replay_requests_are_rejected(client: TestClient, case: str) -> None:
    eid = seed(client, "invalid_inventory_argument")
    cp1, cp3 = checkpoint(client, eid, 1), checkpoint(client, eid, 3)
    req = sku_fix(eid, cp1)
    if case == "schema":
        req["intervention"] = {
            **req["intervention"],
            "field": "product_name",
            "value": "blue backpack",
            "remove_fields": [],
        }
    elif case == "before_checkpoint":
        req["checkpoint_id"] = cp3["checkpoint_id"]
    elif case == "not_a_tool":
        graph = client.get(f"/api/v1/executions/{eid}/graph").json()
        req["intervention"]["target_span_id"] = next(
            n["id"] for n in graph["nodes"] if n["kind"] == "llm"
        )
    elif case == "bad_result":
        req["intervention"] = {
            "type": "replace_tool_result",
            "target_span_id": cp1["target_span_id"],
            "result": {"available": "maybe"},
        }
    elif case == "stochastic":
        req["mode"] = "controlled_stochastic"
    elif case == "foreign_checkpoint":
        other = seed(client, "exchange_success")
        req["checkpoint_id"] = checkpoint(client, other, 1)["checkpoint_id"]
    resp = client.post("/api/v1/replays", json=req)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reasons"]


def test_metadata_only_runs_cannot_be_replayed(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument", content=False)
    cp = checkpoint(client, eid, 1)
    resp = client.post(
        "/api/v1/replays", json={"source_execution_id": eid, "checkpoint_id": cp["checkpoint_id"]}
    )
    assert resp.status_code == 422 and "metadata-only" in resp.text


def test_checkpoint_hash_mismatch_makes_it_ineligible(
    client: TestClient, artifact_dir: Path, db: Session
) -> None:
    eid = seed(client, "invalid_inventory_argument")
    cp = checkpoint(client, eid, 1)
    uri = db.execute(
        text("SELECT state_artifact_uri FROM checkpoints WHERE id = :i"), {"i": cp["checkpoint_id"]}
    ).scalar_one()
    path = artifact_dir / uri
    path.write_text(path.read_text().replace("red backpack", "red backpacK"))
    tampered = checkpoint(client, eid, 1)
    assert not tampered["eligible"] and "hash mismatch" in tampered["reasons"][0]
    assert client.post("/api/v1/replays", json=sku_fix(eid, cp)).status_code == 422


# ------------------------------------------------------------------ idempotency & crashes
def test_same_idempotency_key_returns_the_same_job(client: TestClient, db: Session) -> None:
    eid = seed(client, "invalid_inventory_argument")
    req = sku_fix(eid, checkpoint(client, eid, 1), idempotency_key="demo-key-" + eid)
    first = client.post("/api/v1/replays", json=req)
    second = client.post("/api/v1/replays", json=req)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    run_job(first.json()["job_id"])
    run_job(first.json()["job_id"])  # a duplicate delivery of the same job is a no-op
    forks = db.execute(
        text("SELECT count(*) FROM executions WHERE parent_execution_id = :e"), {"e": eid}
    ).scalar_one()
    assert forks == 1


def test_crashed_attempt_is_cleaned_up_and_retried(client: TestClient, db: Session) -> None:
    eid = seed(client, "invalid_inventory_argument")
    job = client.post("/api/v1/replays", json=sku_fix(eid, checkpoint(client, eid, 1))).json()
    fork_id = job["fork_execution_id"]
    # Simulate a worker that died mid-ingest: a half-written fork and a 'running' job.
    db.execute(
        text(
            "INSERT INTO executions (id, project_id, agent_version_id, parent_execution_id, "
            "status, task_id, attributes_json) SELECT :f, project_id, agent_version_id, id, "
            "'running', task_id, '{}'::jsonb FROM executions WHERE id = :e"
        ),
        {"f": fork_id, "e": eid},
    )
    db.execute(
        text("UPDATE replay_jobs SET status = 'running', attempts = 1 WHERE id = :j"),
        {"j": job["job_id"]},
    )
    db.commit()
    outcome = run_job(job["job_id"])
    assert outcome["status"] == "succeeded"
    fork = client.get(f"/api/v1/executions/{fork_id}").json()
    assert fork["status"] == "succeeded" and fork["event_count"] > 0
    assert client.get(f"/api/v1/replays/{job['job_id']}").json()["attempts"] == 2


# ------------------------------------------------------------------ isolation
def test_forbidden_network_access_fails_the_replay(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    import socket

    eid = seed(client, "invalid_inventory_argument")
    job = client.post("/api/v1/replays", json=sku_fix(eid, checkpoint(client, eid, 1))).json()
    original = TOOLS["lookup_inventory"].impl

    def leaky(sb: Any, args: Any) -> Any:
        socket.create_connection(("example.com", 80), timeout=1)  # must never succeed
        return original(sb, args)

    monkeypatch.setattr(TOOLS["lookup_inventory"], "impl", leaky)
    outcome = run_job(job["job_id"])
    assert outcome["status"] == "failed"
    assert "isolation incident" in (outcome["error"] or "")
    assert outcome["result"]["isolation_incidents"] == 1
    assert (
        db.execute(
            text("SELECT count(*) FROM executions WHERE id = :f"), {"f": job["fork_execution_id"]}
        ).scalar_one()
        == 0
    )
    # The guard is gone afterwards: the database is still reachable.
    assert client.get("/readyz").json()["checks"]["database"]["ok"]


def test_forks_are_independent(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument")
    cp = checkpoint(client, eid, 1)
    a = client.post("/api/v1/replays", json=sku_fix(eid, cp, idempotency_key="a-" + eid)).json()
    b = client.post("/api/v1/replays", json=sku_fix(eid, cp, idempotency_key="b-" + eid)).json()
    assert a["fork_execution_id"] != b["fork_execution_id"]
    for j in (a, b):
        assert run_job(j["job_id"])["result"]["fork_verifier_passed"]
    src = client.get(f"/api/v1/executions/{eid}").json()
    assert src["attributes"]["final_sandbox"] == []  # the source sandbox gained nothing


def test_queued_job_runs_on_a_real_rq_worker(client: TestClient) -> None:
    from app.jobs import get_queue

    eid = seed(client, "invalid_inventory_argument")
    job = client.post("/api/v1/replays", json=sku_fix(eid, checkpoint(client, eid, 1))).json()
    queue = get_queue()
    SimpleWorker([queue], connection=queue.connection).work(burst=True)
    final = client.get(f"/api/v1/replays/{job['job_id']}").json()
    assert final["status"] == "succeeded" and final["result"]["fork_verifier_passed"]
    assert isinstance(queue.connection, Redis)
