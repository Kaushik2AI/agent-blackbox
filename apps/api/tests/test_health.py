"""Health/readiness behaviour.

Unit tests point the API at ports where nothing listens, proving /readyz reports a
real failure (503) instead of a hardcoded success. Integration tests use real services.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def unreachable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import _clear_caches

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("READINESS_TIMEOUT_S", "0.5")
    _clear_caches()
    yield
    monkeypatch.undo()
    _clear_caches()


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def test_healthz_is_dependency_free(unreachable_env: None) -> None:
    resp = _client().get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_reports_real_failures(unreachable_env: None) -> None:
    resp = _client().get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["ok"] is False
    assert body["checks"]["redis"]["ok"] is False
    # Connection strings (and their passwords) must never leak into the response.
    assert "nobody:x" not in resp.text


@pytest.mark.integration
def test_readyz_ready_when_services_up_and_migrated(migrated_db: str) -> None:
    resp = _client().get("/readyz")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] and body["checks"]["redis"]["ok"]


def test_cors_origins_accepts_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:3000, http://localhost:3000")
    settings = Settings(database_url="postgresql+psycopg://x@h/d", redis_url="redis://h")
    assert settings.cors_origins == ["http://127.0.0.1:3000", "http://localhost:3000"]
