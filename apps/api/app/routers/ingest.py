"""POST /api/v1/events:batch - idempotent, redacting, size-limited ingestion."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.config import get_settings
from app.contracts import EventBatch, IngestResult
from app.db import session_scope
from app.services.ingest import IngestConflict, ingest_batch

router = APIRouter(prefix="/api/v1", tags=["ingest"])


def _token_ok(request: Request, expected: str) -> bool:
    """Public deployments only accept batches that carry INGEST_TOKEN (the demo's own
    seeding and workers write in-process and never need it)."""
    sent = request.headers.get("x-ingest-token", "")
    return bool(expected) and secrets.compare_digest(sent, expected)


@router.post(
    "/events:batch",
    response_model=IngestResult,
    responses={409: {}, 413: {}, 422: {}},
    summary="Ingest one execution's spans, events and artifact references",
)
async def ingest(request: Request) -> IngestResult:
    settings = get_settings()
    if settings.public_demo and not _token_ok(request, settings.ingest_token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "ingest is closed on the public demo (missing token)"
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_ingest_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "batch too large")
    body = await request.body()
    if len(body) > settings.max_ingest_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "batch too large")
    try:
        batch = EventBatch.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors(include_url=False)],
        ) from None

    def work() -> IngestResult:
        with session_scope() as session:
            return ingest_batch(session, batch, max_payload_bytes=settings.max_event_payload_bytes)

    try:
        return await run_in_threadpool(work)
    except IngestConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
