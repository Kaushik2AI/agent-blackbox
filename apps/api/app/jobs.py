"""Background job queue (RQ on Redis).

ADR-001 picks RQ over Dramatiq: fewer moving parts, plain functions as jobs, and a
`SimpleWorker` that runs in-process for tests. In M1 the only job is `queue_selftest`,
which proves the API -> Redis -> worker -> result path works end to end. Replay and
evaluation jobs are added in M6/M8; nothing here pretends to replay anything.
"""

from datetime import UTC, datetime

from redis import Redis
from rq import Queue

from app.config import get_settings


def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_queue(connection: Redis | None = None) -> Queue:
    return Queue(get_settings().rq_queue_name, connection=connection or get_redis())


def queue_selftest(token: str) -> dict[str, str]:
    """Round-trip job: returns the token it was given plus the time the worker ran it."""
    return {"token": token, "processed_at": datetime.now(UTC).isoformat()}
