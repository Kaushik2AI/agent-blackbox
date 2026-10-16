"""Benchmark results (M8/M9): sources, summaries with intervals, CSV export."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.evaluations import list_sources, source_csv, source_summary

router = APIRouter(prefix="/api/v1/evaluations", tags=["benchmark"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def evaluations(session: SessionDep) -> list[dict[str, Any]]:
    """Every imported benchmark run (one per benchmark, model, revision and seed)."""
    return list_sources(session)


@router.get("/{source}")
def evaluation(source: str, session: SessionDep) -> dict[str, Any]:
    summary = source_summary(session, source)
    if summary is None:
        raise HTTPException(404, f"no benchmark results for {source!r}")
    return summary


@router.get("/{source}/runs.csv", response_class=PlainTextResponse)
def evaluation_csv(source: str, session: SessionDep) -> PlainTextResponse:
    text = source_csv(session, source)
    if text is None:
        raise HTTPException(404, f"no benchmark results for {source!r}")
    return PlainTextResponse(
        text,
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="benchmark-{source}.csv"'},
    )
