"""M3 ingestion against real Postgres: real agent runs, idempotency, ordering, redaction,
limits, provenance. Data is proven with SQL queries, not just API responses."""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from agent_harness.fixtures import load_fixture
from blackbox_sdk.exporters import HttpExporter, MemoryExporter
from blackbox_sdk.integrations.agent_harness import run_traced
from blackbox_sdk.recorder import Recorder, Resource
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration
URL = "/api/v1/events:batch"


@pytest.fixture
def client(migrated_db: str) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def sql(migrated_db: str) -> Any:
    engine = create_engine(migrated_db)

    def query(statement: str, **params: Any) -> list[Any]:
        with engine.connect() as conn:
            return list(conn.execute(text(statement), params))

    return query


def recorded(fixture: str, **kw: bool) -> dict[str, Any]:
    mem = MemoryExporter()
    run_traced(fixture, mem, **kw)
    return mem.batches[0]


def crafted_batch(**execution: Any) -> tuple[Recorder, dict[str, Any]]:
    rec = Recorder(
        resource=Resource(
            project="tests", agent="crafted", git_sha="abc", config_hash="def", model_name="none"
        ),
        execution_id=str(uuid.uuid4()),
        task_id="crafted",
        capture_content=True,
    )
    root = rec.start_span("root", "agent")
    child = rec.start_span("child", "tool", parent=root)
    rec.add_event(child, "tool_call_end", status="ok", payload={"x": 1})
    rec.end_span(child)
    rec.end_span(root)
    batch = rec.to_batches()[0]
    batch["execution"].update(execution)
    return rec, batch


# ------------------------------------------------------------------ real agent runs
def test_real_agent_run_is_persisted_with_correct_trace(client: TestClient, sql: Any) -> None:
    run, (resp,) = run_traced("invalid_inventory_argument", HttpExporter("", client=client))
    eid = run.execution_id
    assert resp["spans_new"] == 18 and resp["events_new"] == resp["events_received"] == 28

    (row,) = sql("SELECT status, attributes_json FROM executions WHERE id = :id", id=eid)
    assert row.status == "failed"
    assert row.attributes_json["derived"]["error_codes"] == ["SKU_REQUIRED"]
    assert row.attributes_json["derived"]["tool_calls"] == 8

    # Every non-root span's parent exists; exactly one root.
    orphans = sql(
        "SELECT count(*) FROM spans c WHERE c.execution_id = :id AND c.parent_span_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM spans p WHERE p.execution_id = c.execution_id "
        "AND p.span_id = c.parent_span_id)",
        id=eid,
    )
    roots = sql(
        "SELECT count(*) FROM spans WHERE execution_id = :id AND parent_span_id IS NULL", id=eid
    )
    assert orphans[0][0] == 0 and roots[0][0] == 1

    failing = sql(
        "SELECT e.tool_name, e.payload_json, s.status FROM events e JOIN spans s "
        "ON s.execution_id = e.execution_id AND s.span_id = e.span_id WHERE e.execution_id = :id "
        "AND e.event_type = 'tool_call_end' AND e.status = 'error' ORDER BY e.sequence_no",
        id=eid,
    )
    assert len(failing) == 7
    assert all(r.tool_name == "lookup_inventory" and r.status == "error" for r in failing)
    assert failing[0].payload_json["error_code"] == "SKU_REQUIRED"
    assert failing[0].payload_json["input_redacted"] == {"product_name": "<str len=12>"}

    seq = [
        r[0]
        for r in sql(
            "SELECT sequence_no FROM events WHERE execution_id = :id ORDER BY sequence_no", id=eid
        )
    ]
    assert seq == list(range(28))


def test_successful_run_is_succeeded(client: TestClient, sql: Any) -> None:
    run, _ = run_traced("exchange_success", HttpExporter("", client=client))
    (row,) = sql("SELECT status FROM executions WHERE id = :id", id=run.execution_id)
    assert row.status == "succeeded"


# ------------------------------------------------------------------ idempotency & ordering
def test_duplicate_batches_create_no_new_rows(client: TestClient, sql: Any) -> None:
    batch = recorded("transient_inventory_timeout")
    eid = batch["execution"]["execution_id"]
    first = client.post(URL, json=batch).json()
    counts = lambda: (  # noqa: E731
        sql("SELECT count(*) FROM events WHERE execution_id = :id", id=eid)[0][0],
        sql("SELECT count(*) FROM spans WHERE execution_id = :id", id=eid)[0][0],
        sql("SELECT count(*) FROM artifacts WHERE execution_id = :id", id=eid)[0][0],
    )
    before = counts()
    second = client.post(URL, json=batch).json()
    third = client.post(URL, json=batch).json()
    assert first["events_new"] == len(batch["events"]) > 0
    assert second["events_new"] == third["events_new"] == 0
    assert second["events_duplicate"] == len(batch["events"])
    assert second["spans_new"] == 0 and second["artifacts_new"] == 0
    assert counts() == before


def test_out_of_order_batches_and_missing_parents(client: TestClient, sql: Any) -> None:
    batch = recorded("exchange_success")
    eid = batch["execution"]["execution_id"]
    root = next(s for s in batch["spans"] if s["parent_span_id"] is None)
    children = [s for s in batch["spans"] if s is not root]

    # 1) events alone, before any span exists
    events_only = {**copy.deepcopy(batch), "spans": [], "artifacts": []}
    assert client.post(URL, json=events_only).status_code == 200
    # 2) children whose parent has not arrived yet
    assert client.post(URL, json={**batch, "spans": children, "events": []}).status_code == 200
    graph = client.get(f"/api/v1/executions/{eid}/graph").json()
    assert all(n["orphan"] for n in graph["nodes"])
    # 3) the root finally arrives
    assert client.post(URL, json={**batch, "spans": [root], "events": []}).status_code == 200
    graph = client.get(f"/api/v1/executions/{eid}/graph").json()
    assert not any(n["orphan"] for n in graph["nodes"])
    assert sql("SELECT count(*) FROM events WHERE execution_id = :id", id=eid)[0][0] == len(
        batch["events"]
    )


def test_span_end_arriving_later_is_merged(client: TestClient, sql: Any) -> None:
    _, batch = crafted_batch()
    eid = batch["execution"]["execution_id"]
    open_spans = copy.deepcopy(batch)
    for s in open_spans["spans"]:
        s["end_ms"], s["status"] = None, "unset"
    client.post(URL, json=open_spans)
    client.post(URL, json=batch)
    rows = sql("SELECT status, end_ms FROM spans WHERE execution_id = :id", id=eid)
    assert all(r.status == "ok" and r.end_ms is not None for r in rows)


def test_late_nonterminal_status_does_not_overwrite_terminal(client: TestClient, sql: Any) -> None:
    _, batch = crafted_batch(status="failed")
    eid = batch["execution"]["execution_id"]
    client.post(URL, json=batch)
    late = copy.deepcopy(batch)
    late["execution"]["status"] = "running"
    client.post(URL, json=late)
    assert sql("SELECT status FROM executions WHERE id = :id", id=eid)[0][0] == "failed"


# ------------------------------------------------------------------ validation & limits
def test_unknown_schema_version_is_rejected_and_nothing_stored(
    client: TestClient, sql: Any
) -> None:
    _, batch = crafted_batch()
    for version in ["2.0", "0.9"]:
        resp = client.post(URL, json={**batch, "schema_version": version})
        assert resp.status_code == 422 and "unsupported schema_version" in resp.text
    eid = batch["execution"]["execution_id"]
    assert sql("SELECT count(*) FROM executions WHERE id = :id", id=eid)[0][0] == 0


def test_malformed_ids_are_rejected(client: TestClient) -> None:
    _, batch = crafted_batch()
    bad = copy.deepcopy(batch)
    bad["spans"][0]["span_id"] = "not-hex"
    assert client.post(URL, json=bad).status_code == 422


def test_oversized_request_is_rejected_with_413(client: TestClient) -> None:
    _, batch = crafted_batch()
    batch["events"][0]["payload"]["blob"] = "x" * 2_100_000
    assert client.post(URL, json=batch).status_code == 413


def test_oversized_payload_is_stored_as_truncation_marker(client: TestClient, sql: Any) -> None:
    _, batch = crafted_batch()
    batch["events"][0]["payload"]["blob"] = "y" * 50_000
    resp = client.post(URL, json=batch).json()
    assert resp["payloads_truncated"] == 1
    (row,) = sql(
        "SELECT payload_json FROM events WHERE execution_id = :id",
        id=batch["execution"]["execution_id"],
    )
    assert row.payload_json["_truncated"] is True and len(row.payload_json["sha256"]) == 64


def test_secrets_are_redacted_server_side_before_storage(client: TestClient, sql: Any) -> None:
    """A client that does NOT redact still cannot get secrets into the database."""
    _, batch = crafted_batch()
    batch["events"][0]["payload"] = {
        "Authorization": "Bearer live-token-123456789",
        "apiKey": "plain-value-123",
        "note": "use sk-PROJECTKEY1234567890ABCD or mail ceo@example.com",
        "nested": [{"password": "hunter2"}],
    }
    batch["spans"][0]["attributes"] = {"client_secret": "s3cr3t"}
    resp = client.post(URL, json=batch).json()
    assert resp["redactions"] >= 6
    eid = batch["execution"]["execution_id"]
    stored = json.dumps(
        [r[0] for r in sql("SELECT payload_json FROM events WHERE execution_id = :id", id=eid)]
        + [r[0] for r in sql("SELECT attributes_json FROM spans WHERE execution_id = :id", id=eid)]
    )
    for secret in [
        "live-token-123456789",
        "plain-value-123",
        "sk-PROJECTKEY1234567890ABCD",
        "ceo@example.com",
        "hunter2",
        "s3cr3t",
    ]:
        assert secret not in stored


def test_execution_cannot_switch_agent_version(client: TestClient) -> None:
    _, batch = crafted_batch()
    client.post(URL, json=batch)
    other = copy.deepcopy(batch)
    other["resource"]["agent_version"]["git_sha"] = "different"
    assert client.post(URL, json=other).status_code == 409


# ------------------------------------------------------------------ provenance
def test_provenance_is_recorded(client: TestClient, sql: Any) -> None:
    run, _ = run_traced("exchange_success", HttpExporter("", client=client))
    fixture = load_fixture("exchange_success")
    (row,) = sql(
        "SELECT e.attributes_json, v.git_sha, v.config_hash, v.model_name FROM executions e "
        "JOIN agent_versions v ON v.id = e.agent_version_id WHERE e.id = :id",
        id=run.execution_id,
    )
    attrs = row.attributes_json
    assert attrs["fixture"] == {
        "id": "exchange_success",
        "version": "1.0.0",
        "sha256": fixture.content_hash,
    }
    assert attrs["sdk"]["name"] == "blackbox-sdk" and attrs["determinism"] == "deterministic"
    assert row.model_name == "stub-planner-v1" and len(row.config_hash) == 64 and row.git_sha
    artifacts = {
        r.uri: r.sha256
        for r in sql(
            "SELECT uri, sha256 FROM artifacts WHERE execution_id = :id", id=run.execution_id
        )
    }
    assert artifacts["fixture://exchange_success@1.0.0"] == fixture.content_hash
    assert any(u.startswith("sandbox-state://") for u in artifacts)
