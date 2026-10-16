"""Live demo: start the agent on a scenario and follow it step by step (polling), plus
one-click fix suggestions for failed runs."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.jobs import enqueue_live, get_redis
from app.services import live, ratelimit
from app.services.fixes import suggest_fix
from app.services.llm import llm_status

router = APIRouter(prefix="/api/v1", tags=["live demo"])
SessionDep = Annotated[Session, Depends(get_session)]


class ScenarioOut(BaseModel):
    id: str
    fixture_id: str
    title: str
    blurb: str
    brains: list[str]
    default_message: str
    expected: str


class LiveConfig(BaseModel):
    llm_available: bool
    llm_state: Literal["ready", "loading", "offline", "none"]
    llm_label: str
    public_demo: bool
    message_max_chars: int
    scenarios: list[ScenarioOut]


@router.get("/live/config", response_model=LiveConfig)
def live_config() -> LiveConfig:
    s = get_settings()
    state, label = llm_status(s)
    return LiveConfig(
        llm_available=state == "ready",
        llm_state=state,
        llm_label=label,
        public_demo=s.public_demo,
        message_max_chars=s.live_message_max_chars,
        scenarios=[
            ScenarioOut(
                id=sc.id,
                fixture_id=sc.fixture_id,
                title=sc.title,
                blurb=sc.blurb,
                brains=list(sc.brains),
                default_message=live.default_message(sc.fixture_id),
                expected=live.expected_outcome(sc.fixture_id),
            )
            for sc in live.SCENARIOS
        ],
    )


class LiveRunIn(BaseModel):
    scenario: str
    brain: Literal["llm", "scripted"]
    message: str | None = Field(default=None, max_length=2000)


class LiveRunOut(BaseModel):
    live_id: str
    status: str
    scenario: str | None
    brain: str | None
    execution_id: str | None
    error: str | None
    verifier_passed: bool | None
    steps: list[dict[str, Any]]
    next: int


@router.post("/live-runs", response_model=LiveRunOut, status_code=202)
def start_live_run(body: LiveRunIn, request: Request) -> LiveRunOut:
    s = get_settings()
    scenario = live.BY_ID.get(body.scenario)
    if scenario is None:
        raise HTTPException(422, f"unknown scenario {body.scenario!r}")
    if body.brain not in scenario.brains:
        raise HTTPException(
            422, f"scenario {scenario.id!r} does not run with the {body.brain} agent"
        )
    if body.brain == "llm":
        state, _ = llm_status(s)
        if state != "ready":
            reason = {
                "none": "The live AI isn't set up on this server. Use the scripted agent.",
                "loading": "The AI model is still loading. Try again in a minute.",
                "offline": "The AI model server isn't running. Use the scripted agent.",
            }[state]
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reason)
    message = (body.message or "").strip() or None
    if body.brain == "scripted":
        message = None  # the scripted agent never reads the message
    elif message is not None and len(message) > s.live_message_max_chars:
        raise HTTPException(422, f"message is longer than {s.live_message_max_chars} characters")
    redis = get_redis()
    if s.public_demo:
        try:
            ratelimit.check(
                redis,
                ratelimit.client_ip(request),
                per_ip_per_hour=s.live_runs_per_ip_per_hour if body.brain == "llm" else 60,
                llm=body.brain == "llm",
                llm_per_day=s.live_llm_runs_per_day,
            )
        except ratelimit.RateLimited as exc:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.message) from None
    live_id = live.create(redis, scenario, body.brain, message)
    enqueue_live(live_id)
    out = live.read(redis, live_id)
    assert out is not None
    return LiveRunOut(**out)


@router.get("/live-runs/{live_id}", response_model=LiveRunOut)
def get_live_run(live_id: uuid.UUID, after: int = 0) -> LiveRunOut:
    out = live.read(get_redis(), str(live_id), max(0, after))
    if out is None:
        raise HTTPException(404, "live run not found (they expire after 24 hours)")
    return LiveRunOut(**out)


@router.get("/executions/{execution_id}/suggested-fix")
def get_suggested_fix(execution_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    try:
        return suggest_fix(session, execution_id)
    except LookupError:
        raise HTTPException(404, f"execution {execution_id} not found") from None
