"""Background job queue (RQ on Redis).

ADR-001 picks RQ over Dramatiq: fewer moving parts, plain functions as jobs, and a
`SimpleWorker` that runs in-process for tests. In M1 the only job is `queue_selftest`,
which proves the API -> Redis -> worker -> result path works end to end. `run_replay_job`
(M6) resumes a checkpoint in the sandbox; see app/services/replay.py.
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


def run_replay_job(job_id: str) -> dict[str, str]:
    """RQ entry point. Idempotent: re-running a finished job does nothing."""
    import uuid

    from app.db import session_scope
    from app.services.replay import execute_job

    with session_scope() as session:
        job = execute_job(session, uuid.UUID(job_id))
        return {"job_id": job_id, "status": job.status.value}


def enqueue_replay(job_id: str) -> None:
    get_queue().enqueue(
        run_replay_job,
        job_id,
        job_id=f"replay-{job_id}",
        job_timeout=300,
        result_ttl=86400,
        failure_ttl=86400,
    )
