"""M4 read APIs backed by real ingested runs."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from blackbox_sdk.exporters import HttpExporter
from blackbox_sdk.integrations.agent_harness import run_traced
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client(migrated_db: str) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def seed(client: TestClient, fixture: str) -> str:
    run, _ = run_traced(fixture, HttpExporter("", client=client), capture_content=True)
    return run.execution_id


def test_list_filters_and_pagination(client: TestClient) -> None:
    failed_id = seed(client, "invalid_inventory_argument")
    ok_id = seed(client, "exchange_success")

    failed = client.get("/api/v1/executions", params={"status": "failed", "limit": 200}).json()
    assert failed_id in {i["id"] for i in failed["items"]}
    assert all(i["status"] == "failed" for i in failed["items"])

    by_task = client.get(
        "/api/v1/executions", params={"task_id": "invalid_inventory_argument", "limit": 200}
    ).json()
    item = next(i for i in by_task["items"] if i["id"] == failed_id)
    assert item["error_codes"] == ["SKU_REQUIRED"] and item["tool_calls"] == 8
    assert item["termination"] == "budget_exhausted" and item["verifier_passed"] is False
    assert item["agent_version"]["model_name"] == "stub-planner-v1"

    version = item["agent_version"]["id"]
    same_version = client.get(
        "/api/v1/executions", params={"agent_version_id": version, "limit": 200}
    ).json()
    assert {failed_id, ok_id} <= {i["id"] for i in same_version["items"]}

    page1 = client.get("/api/v1/executions", params={"limit": 1, "offset": 0}).json()
    page2 = client.get("/api/v1/executions", params={"limit": 1, "offset": 1}).json()
    assert page1["total"] >= 2 and page1["items"][0]["id"] != page2["items"][0]["id"]

    future = client.get("/api/v1/executions", params={"since": "2999-01-01T00:00:00Z"}).json()
    assert future["total"] == 0


def test_detail_timeline_and_graph(client: TestClient) -> None:
    eid = seed(client, "invalid_inventory_argument")
    detail = client.get(f"/api/v1/executions/{eid}").json()
    assert detail["span_count"] == 18 and detail["event_count"] == 28
    assert {a["type"] for a in detail["artifacts"]} == {"fixture", "sandbox_state"}

    timeline = client.get(f"/api/v1/executions/{eid}/timeline").json()
    assert [e["sequence_no"] for e in timeline["events"]] == list(range(28))
    failing = [e for e in timeline["events"] if e["status"] == "error" and e["tool_name"]]
    assert failing[0]["payload"]["input_redacted"] == {"product_name": "red backpack"}
    assert failing[0]["payload"]["error_code"] == "SKU_REQUIRED"

    graph = client.get(f"/api/v1/executions/{eid}/graph").json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    root = next(n for n in graph["nodes"] if n["parent_span_id"] is None)
    assert root["kind"] == "agent" and root["status"] == "error"
    bad = [n for n in graph["nodes"] if n["error_code"] == "SKU_REQUIRED"]
    assert len(bad) == 7 and all(n["tool_name"] == "lookup_inventory" for n in bad)
    parent_edges = [e for e in graph["edges"] if e["kind"] == "parent"]
    next_edges = [e for e in graph["edges"] if e["kind"] == "next"]
    assert len(parent_edges) == 17 and len(next_edges) == 16
    assert all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"])


def test_overview_counts_real_runs(client: TestClient) -> None:
    before = client.get("/api/v1/overview").json()
    seed(client, "exchange_success")
    seed(client, "invalid_inventory_argument")
    after = client.get("/api/v1/overview").json()
    assert after["total"] - before["total"] == 2
    assert after["succeeded"] - before["succeeded"] == 1
    assert after["failed"] - before["failed"] == 1
    assert (
        after["failure_tags"]["SKU_REQUIRED"] - before["failure_tags"].get("SKU_REQUIRED", 0) == 1
    )
    assert after["median_duration_ms"] is not None
    assert after["total_tokens"] is None  # the stub model reports no token usage


def test_unknown_execution_is_404_and_bad_id_422(client: TestClient) -> None:
    assert client.get(f"/api/v1/executions/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/v1/executions/{uuid.uuid4()}/graph").status_code == 404
    assert client.get("/api/v1/executions/not-a-uuid").status_code == 422


def test_agent_versions_listing(client: TestClient) -> None:
    seed(client, "exchange_success")
    versions = client.get("/api/v1/agent-versions").json()
    assert any(v["agent"] == "support-agent" for v in versions)


def test_graph_order_follows_execution_order(client: TestClient) -> None:
    """Spans starting in the same millisecond must still come out in execution order:
    model decision, tool call, model decision, tool call..."""
    eid = seed(client, "exchange_success")
    nodes = sorted(
        client.get(f"/api/v1/executions/{eid}/graph").json()["nodes"], key=lambda n: n["order"]
    )
    kinds = [n["kind"] for n in nodes]
    assert kinds == ["agent"] + ["llm", "tool"] * 5 + ["llm"]
    tools = [n["tool_name"] for n in nodes if n["kind"] == "tool"]
    assert tools == [
        "lookup_order",
        "lookup_inventory",
        "get_policy",
        "draft_response",
        "submit_resolution",
    ]
