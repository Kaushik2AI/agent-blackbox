"""Real Redis + RQ round trip: enqueue -> worker executes -> result readable."""

import uuid

import pytest
from redis import Redis
from rq import Queue, SimpleWorker

from app.config import get_settings
from app.jobs import queue_selftest

pytestmark = pytest.mark.integration


def test_rq_job_round_trip() -> None:
    try:
        redis = Redis.from_url(get_settings().redis_url)
        redis.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {type(exc).__name__}")

    queue = Queue(f"blackbox-test-{uuid.uuid4().hex[:8]}", connection=redis)
    token = uuid.uuid4().hex
    job = queue.enqueue(queue_selftest, token)
    try:
        SimpleWorker([queue], connection=redis).work(burst=True)
        job.refresh()
        assert job.is_finished, job.get_status()
        assert job.return_value()["token"] == token
    finally:
        queue.delete(delete_jobs=True)
