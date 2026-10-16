"""The local Qwen server (infra/scc/qwen_server.py) and how the API reads its status.
The HTTP layer is tested with a fake engine; loading a real model is covered by
`make qwen-setup`, which runs a one-question self-test on the SCC node."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

SERVER = Path(__file__).resolve().parents[3] / "infra" / "scc" / "qwen_server.py"
spec = importlib.util.spec_from_file_location("qwen_server", SERVER)
assert spec and spec.loader
qs = importlib.util.module_from_spec(spec)
sys.modules["qwen_server"] = qs  # pydantic resolves the request models through it
spec.loader.exec_module(qs)


def test_json_complete_stops_after_the_first_whole_object() -> None:
    assert not qs.json_complete('{"tool": "lookup_order", "args": {"order_id": "ORD')
    assert qs.json_complete('{"tool": "x", "args": {}}')
    assert qs.json_complete('Sure! {"finish": "completed"} more text')
    # Braces inside strings do not count.
    assert not qs.json_complete('{"note": "use } carefully"')
    assert qs.json_complete('{"note": "a \\" } b", "finish": "completed"}')
    assert not qs.json_complete("no json here }")


def test_model_choice_fits_the_hardware() -> None:
    assert qs.choose_model("auto", 40.0, 8) == qs.LARGE
    assert qs.choose_model("auto", 8.0, 8) == qs.MEDIUM
    assert qs.choose_model("auto", None, 32) == qs.MEDIUM
    assert qs.choose_model("auto", None, 6) == qs.SMALL
    assert qs.choose_model("Qwen/Qwen2.5-7B-Instruct", None, 2) == "Qwen/Qwen2.5-7B-Instruct"
    assert qs.short_label(qs.MEDIUM, "cpu") == "Qwen2.5 1.5B · on SCC CPU"


class FakeEngine:
    def __init__(self, status: str = "ready") -> None:
        self.status = status
        self.error = ""
        self.model_id = qs.MEDIUM
        self.device = "cpu"
        self.calls: list[Any] = []

    def chat(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> dict:
        self.calls.append((messages, temperature, max_tokens))
        return {"text": '{"finish": "completed"}', "prompt_tokens": 30, "completion_tokens": 6}


def test_server_speaks_the_openai_chat_format_and_requires_the_key() -> None:
    engine = FakeEngine()
    client = TestClient(qs.build_app(engine, "secret"))
    body = {"model": "x", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}

    assert client.post("/v1/chat/completions", json=body).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.post("/v1/chat/completions", json=body, headers=bad).status_code == 401

    ok = {"Authorization": "Bearer secret"}
    resp = client.post("/v1/chat/completions", json=body, headers=ok)
    assert resp.status_code == 200
    out = resp.json()
    assert out["choices"][0]["message"]["content"] == '{"finish": "completed"}'
    assert out["usage"] == {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36}
    assert out["model"] == qs.MEDIUM
    assert engine.calls[0][2] == 50

    assert client.get("/v1/models", headers=ok).json()["data"][0]["id"] == qs.MEDIUM
    health = client.get("/health").json()  # no key needed: used by the API's status probe
    assert health["status"] == "ready" and health["label"].endswith("on SCC CPU")


def test_server_refuses_chats_while_loading() -> None:
    client = TestClient(qs.build_app(FakeEngine("loading"), "secret"))
    ok = {"Authorization": "Bearer secret"}
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body, headers=ok).status_code == 503
    assert client.get("/health").json()["status"] == "loading"


# ------------------------------------------------------------------ API side
@pytest.fixture
def local_llm(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.config import get_settings
    from app.services import llm

    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:59123/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "local-qwen")
    get_settings.cache_clear()
    llm._status_cache.clear()
    yield llm
    get_settings.cache_clear()
    llm._status_cache.clear()


def _health(monkeypatch: pytest.MonkeyPatch, reply: dict | None) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        assert url == "http://127.0.0.1:59123/health"
        if reply is None:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=reply)

    monkeypatch.setattr(httpx, "get", fake_get)


def test_local_model_status_follows_the_server(local_llm: Any, monkeypatch: Any) -> None:
    _health(monkeypatch, None)
    assert local_llm.llm_status()[0] == "offline"

    local_llm._status_cache.clear()
    _health(monkeypatch, {"status": "loading", "model": "", "label": ""})
    assert local_llm.llm_status()[0] == "loading"

    local_llm._status_cache.clear()
    _health(
        monkeypatch,
        {"status": "ready", "model": qs.MEDIUM, "label": "Qwen2.5 1.5B · on SCC CPU"},
    )
    assert local_llm.llm_status() == ("ready", "Qwen2.5 1.5B · on SCC CPU")
    # Traces name the model that was really loaded, not the placeholder in .env.
    assert local_llm.llm_model_name() == f"llm:{qs.MEDIUM}"
    assert local_llm.build_llm().config.model == qs.MEDIUM


def test_hosted_api_is_not_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.services import llm

    monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    get_settings.cache_clear()
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("must not probe"))
    try:
        assert llm.llm_status()[0] == "ready"
    finally:
        get_settings.cache_clear()
