"""Live demo runs, one-click fixes, real-model replays and public-deployment guards,
against real Postgres/Redis. The real model is a fake OpenAI-compatible endpoint."""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from agent_harness.llm import LLMConfig, OpenAICompatModel
from fastapi.testclient import TestClient

from app.services.sandbox_guard import SandboxViolation, no_network

pytestmark = pytest.mark.integration

CORRECT = [
    {"note": "find the order", "tool": "lookup_order", "args": {"order_id": "ORD-1001"}},
    {"note": "check stock", "tool": "lookup_inventory", "args": {"sku": "SKU-RED-004"}},
    {"note": "policy", "tool": "get_policy", "args": {"policy_key": "exchange"}},
    {"tool": "draft_response", "args": {"customer_id": "C-17", "text": "Exchange on its way."}},
    {"tool": "submit_resolution", "args": {"order_id": "ORD-1001", "choice": "exchange"}},
    {"finish": "completed"},
]
BAD_STOCK = {"note": "check stock", "tool": "lookup_inventory", "args": {"product_name": "bag"}}


def fake_llm(replies: list[dict[str, Any]]) -> OpenAICompatModel:
    queue = [json.dumps(r) for r in replies]

    def handler(request: httpx.Request) -> httpx.Response:
        text = queue.pop(0) if queue else json.dumps({"finish": "gave_up"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    return OpenAICompatModel(
        LLMConfig("https://fake.test/v1", "k", "qwen-test"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def settings_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    from app.config import get_settings

    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
def client(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app.config import get_settings
    from app.main import create_app

    # Hermetic: ignore any real model configured in the developer's .env.
    monkeypatch.setenv("LLM_BASE_URL", "https://fake.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setattr("app.routers.live.enqueue_live", lambda live_id: None)
    monkeypatch.setattr("app.routers.replays.enqueue_replay", lambda job_id: None)
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def work_live(live_id: str) -> None:
    from app.db import session_scope
    from app.jobs import get_redis
    from app.services.live import execute

    execute(session_scope, get_redis(), live_id)


def work_replay(job_id: str) -> dict[str, Any]:
    from app.db import session_scope
    from app.services.replay import execute_job

    with session_scope() as s:
        job = execute_job(s, uuid.UUID(job_id))
        return {"status": job.status.value, "error": job.error, "result": job.result_json}


def live_run(client: TestClient, scenario: str, brain: str = "scripted", **extra: Any) -> dict:
    resp = client.post("/api/v1/live-runs", json={"scenario": scenario, "brain": brain, **extra})
    assert resp.status_code == 202, resp.text
    live_id = resp.json()["live_id"]
    work_live(live_id)
    out = client.get(f"/api/v1/live-runs/{live_id}").json()
    assert out["status"] == "done", out
    return out


# ------------------------------------------------------------------ config and runs
def test_config_lists_scenarios_and_hides_the_ai_without_a_key(client: TestClient) -> None:
    cfg = client.get("/api/v1/live/config").json()
    assert cfg["llm_available"] is False
    ids = [s["id"] for s in cfg["scenarios"]]
    assert ids[0] == "normal" and "bug_wrong_input" in ids
    bug = next(s for s in cfg["scenarios"] if s["id"] == "bug_wrong_input")
    assert bug["brains"] == ["scripted"]
    assert bug["expected"] == "Exchange for order ORD-1001"


def test_scripted_live_run_streams_steps_and_stores_the_trace(client: TestClient) -> None:
    out = live_run(client, "bug_wrong_input")
    kinds = [s["kind"] for s in out["steps"]]
    assert kinds[0] == "decision" and kinds[-1] == "end"
    tools = [s for s in out["steps"] if s["kind"] == "tool"]
    assert tools[1]["error_code"] == "SKU_REQUIRED"
    assert out["verifier_passed"] is False
    assert "budget" in kinds
    eid = out["execution_id"]
    findings = client.get(f"/api/v1/executions/{eid}/findings").json()["findings"]
    assert {f["category"] for f in findings} >= {"tool_schema_mismatch", "retry_loop"}
    # Polling with `after` returns only new steps.
    again = client.get(f"/api/v1/live-runs/{out['live_id']}?after={out['next']}").json()
    assert again["steps"] == [] and again["next"] == out["next"]


def test_unknown_scenario_and_wrong_brain_are_rejected(client: TestClient) -> None:
    assert (
        client.post("/api/v1/live-runs", json={"scenario": "nope", "brain": "scripted"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/live-runs", json={"scenario": "bug_wrong_input", "brain": "llm"}
        ).status_code
        == 422
    )
    resp = client.post("/api/v1/live-runs", json={"scenario": "normal", "brain": "llm"})
    assert resp.status_code == 503
    assert client.get(f"/api/v1/live-runs/{uuid.uuid4()}").status_code == 404


def test_real_model_live_run(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_env(monkeypatch, LLM_API_KEY="test-key", LLM_MODEL="qwen-test")
    monkeypatch.setattr("app.services.live.build_llm", lambda: fake_llm(CORRECT))
    out = live_run(client, "normal", "llm", message="My zip broke, exchange please")
    assert out["verifier_passed"] is True
    first = out["steps"][0]
    assert first["note"] == "find the order"
    assert first["tokens"] == {"input_tokens": 50, "output_tokens": 5}
    detail = client.get(f"/api/v1/executions/{out['execution_id']}").json()
    assert detail["agent_version"]["model_name"] == "llm:qwen-test"
    assert detail["attributes"]["usage"]["total_tokens"] == 6 * 55


def test_model_outage_is_reported_not_crashed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_env(monkeypatch, LLM_API_KEY="test-key")
    broken = OpenAICompatModel(
        LLMConfig("https://fake.test/v1", "k", "m"),
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )
    monkeypatch.setattr("app.services.live.build_llm", lambda: broken)
    resp = client.post("/api/v1/live-runs", json={"scenario": "normal", "brain": "llm"})
    work_live(resp.json()["live_id"])
    out = client.get(f"/api/v1/live-runs/{resp.json()['live_id']}").json()
    assert out["status"] == "error" and "HTTP 429" in out["error"]


# ------------------------------------------------------------------ one-click fixes
@pytest.mark.parametrize(
    ("scenario", "fix_type", "label"),
    [
        ("bug_wrong_input", "replace_tool_argument", "SKU-RED-004"),
        ("stock_down", "replace_tool_result", "Pretend"),
        ("bug_wrong_order", "replace_tool_argument", "ORD-1001"),
        ("stale_stock", "replace_tool_result", "current stock record"),
    ],
)
def test_suggested_fix_turns_the_failure_into_a_pass(
    client: TestClient, scenario: str, fix_type: str, label: str
) -> None:
    out = live_run(client, scenario)
    assert out["verifier_passed"] is False
    fix = client.get(f"/api/v1/executions/{out['execution_id']}/suggested-fix").json()
    assert fix["available"], fix
    assert label in fix["label"]
    assert fix["request"]["intervention"]["type"] == fix_type
    resp = client.post("/api/v1/replays", json=fix["request"])
    assert resp.status_code == 202, resp.text
    result = work_replay(resp.json()["job_id"])
    assert result["status"] == "succeeded", result
    assert result["result"]["fork_verifier_passed"] is True


def test_no_fix_for_passing_or_unfixable_runs(client: TestClient) -> None:
    ok = live_run(client, "normal")
    fix = client.get(f"/api/v1/executions/{ok['execution_id']}/suggested-fix").json()
    assert fix == {"available": False, "reason": "This run passed, so there is nothing to fix."}
    assert client.get(f"/api/v1/executions/{uuid.uuid4()}/suggested-fix").status_code == 404


def test_real_model_replay_uses_the_model_and_is_stochastic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_env(monkeypatch, LLM_API_KEY="test-key", LLM_MODEL="qwen-test")
    monkeypatch.setattr(
        "app.services.live.build_llm", lambda: fake_llm([CORRECT[0]] + [BAD_STOCK] * 10)
    )
    out = live_run(client, "normal", "llm")
    assert out["verifier_passed"] is False
    fix = client.get(f"/api/v1/executions/{out['execution_id']}/suggested-fix").json()
    assert fix["available"] and fix["request"]["intervention"]["arguments"] == {
        "sku": "SKU-RED-004"
    }
    monkeypatch.setattr("app.services.replay.build_llm", lambda: fake_llm(CORRECT[2:]))
    # The fake model needs no network; allow nothing so the guard is still exercised.
    monkeypatch.setattr("app.services.replay.llm_hosts", lambda: [])
    job = client.post("/api/v1/replays", json=fix["request"]).json()
    assert job["replay_mode"] == "controlled_stochastic"
    result = work_replay(job["job_id"])
    assert result["result"]["fork_verifier_passed"] is True
    assert result["result"]["determinism"] == "controlled_stochastic"

    # A different model configured later cannot replay this run.
    settings_env(monkeypatch, LLM_MODEL="other-model")
    resp = client.post(
        "/api/v1/replays", json={**fix["request"], "idempotency_key": "other-model-1"}
    )
    assert resp.status_code == 422 and "now runs llm:other-model" in resp.text


# ------------------------------------------------------------------ public guards
def test_public_mode_requires_the_ingest_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_env(monkeypatch, PUBLIC_DEMO="true", INGEST_TOKEN="s3cret-token-value")  # noqa: S106
    resp = client.post("/api/v1/events:batch", json={})
    assert resp.status_code == 403
    resp = client.post(
        "/api/v1/events:batch", json={}, headers={"x-ingest-token": "s3cret-token-value"}
    )
    assert resp.status_code == 422  # past the gate; the empty batch itself is invalid


def test_public_mode_rate_limits_real_model_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_env(monkeypatch, PUBLIC_DEMO="true", LLM_API_KEY="k", LIVE_RUNS_PER_IP_PER_HOUR="2")
    ip = {"x-forwarded-for": f"203.0.113.{uuid.uuid4().int % 250}, 10.0.0.1"}
    body = {"scenario": "normal", "brain": "llm"}
    codes = [client.post("/api/v1/live-runs", json=body, headers=ip).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
    # The scripted agent has its own, larger allowance.
    resp = client.post(
        "/api/v1/live-runs", json={"scenario": "normal", "brain": "scripted"}, headers=ip
    )
    assert resp.status_code == 202


def test_network_guard_allows_only_listed_destinations() -> None:
    from redis import Redis

    from app.config import get_settings

    redis = Redis.from_url(get_settings().redis_url)
    port = redis.connection_pool.connection_kwargs["port"]
    incidents: list[str] = []
    with no_network(incidents, allow=[("127.0.0.1", port)]):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        with pytest.raises(SandboxViolation):
            socket.create_connection(("127.0.0.1", 9), timeout=2)
    assert len(incidents) == 1
    # Outside the guard everything is restored.
    socket.create_connection(("127.0.0.1", port), timeout=2).close()
