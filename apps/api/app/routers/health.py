"""Liveness and readiness probes.

/healthz  - the process is up. Never touches dependencies.
/readyz   - every dependency answers right now: Postgres (and migrations are at head)
            and Redis. Returns 503 with per-check detail when anything is down, so the
            UI shows the real state instead of a hardcoded "OK".
"""

import time
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import get_engine

router = APIRouter(tags=["health"])

API_DIR = Path(__file__).resolve().parents[2]


class CheckResult(BaseModel):
    ok: bool
    latency_ms: float
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


def _expected_migration_head() -> str | None:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _check_database() -> CheckResult:
    start = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        expected = _expected_migration_head()
        elapsed = (time.perf_counter() - start) * 1000
        if current != expected:
            return CheckResult(
                ok=False,
                latency_ms=elapsed,
                detail=f"connected, but migration {current!r} != head {expected!r}; "
                "run `make migrate`",
            )
        return CheckResult(ok=True, latency_ms=elapsed, detail=f"migration head {current}")
    except SQLAlchemyError as exc:
        # Report the error class only: full messages can contain the connection string.
        return CheckResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            detail=f"database unavailable ({type(exc).__name__})",
        )


def _check_redis() -> CheckResult:
    settings = get_settings()
    start = time.perf_counter()
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.readiness_timeout_s,
            socket_timeout=settings.readiness_timeout_s,
        )
        client.ping()
        return CheckResult(ok=True, latency_ms=(time.perf_counter() - start) * 1000, detail="PONG")
    except RedisError as exc:
        return CheckResult(
            ok=False,
            latency_ms=(time.perf_counter() - start) * 1000,
            detail=f"redis unavailable ({type(exc).__name__})",
        )


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok", service="agent-blackbox-api", environment=get_settings().environment
    )


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
def readyz(response: Response) -> ReadyResponse:
    checks = {"database": _check_database(), "redis": _check_redis()}
    ready = all(c.ok for c in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ready" if ready else "not_ready", checks=checks)
