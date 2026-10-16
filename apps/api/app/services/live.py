"""Live runs: start the support agent on a scenario, stream its steps while it works,
then store the finished trace like any other run (findings included).

Progress lives in Redis (`live:<id>` hash + `live:<id>:steps` list, 24 h TTL); the
finished trace goes through the normal ingest path, in-process.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent_harness.fixtures import load_fixture
from agent_harness.llm import ModelUnavailable
from blackbox_sdk.exporters import MemoryExporter
from blackbox_sdk.integrations.agent_harness import run_traced
from redis import Redis

from app.config import get_settings
from app.contracts import EventBatch
from app.services.ingest import ingest_batch
from app.services.llm import build_llm

TTL_S = 24 * 3600


@dataclass(frozen=True)
class Scenario:
    id: str
    fixture_id: str
    title: str
    blurb: str
    brains: tuple[str, ...]  # "llm" and/or "scripted"


# What a visitor can pick. Environment problems (stock, timeouts) are injected by the
# sandbox and work with any agent. The last two are bugs planted in the SCRIPTED agent's
# behaviour, so they only make sense with it; a real model makes its own mistakes.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "normal",
        "exchange_success",
        "Broken zip, wants an exchange",
        "Everything works. The agent should arrange an exchange.",
        ("llm", "scripted"),
    ),
    Scenario(
        "out_of_stock",
        "refund_out_of_stock",
        "Item is out of stock",
        "No replacement in stock, so the right answer is a refund.",
        ("llm", "scripted"),
    ),
    Scenario(
        "slow_stock",
        "transient_inventory_timeout",
        "Stock system is slow",
        "The stock check times out once, then works.",
        ("llm", "scripted"),
    ),
    Scenario(
        "stock_down",
        "persistent_inventory_timeout",
        "Stock system is down",
        "Every stock check times out. Watch how the agent copes.",
        ("llm", "scripted"),
    ),
    Scenario(
        "bug_wrong_input",
        "invalid_inventory_argument",
        "Agent bug: wrong input",
        "The scripted agent sends the product name instead of the product code.",
        ("scripted",),
    ),
    Scenario(
        "bug_wrong_order",
        "wrong_order_identity",
        "Agent bug: mixes up orders",
        "The scripted agent closes the ticket on someone else's order.",
        ("scripted",),
    ),
)
BY_ID = {s.id: s for s in SCENARIOS}


def expected_outcome(fixture_id: str) -> str:
    truth = load_fixture(fixture_id).ground_truth.resolution
    return f"{truth.choice.capitalize()} for order {truth.order_id}"


def default_message(fixture_id: str) -> str:
    return load_fixture(fixture_id).task.message


# ------------------------------------------------------------------ redis state
def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _hash(redis: Redis, key: str) -> dict[str, str]:
    return {_text(k): _text(v) for k, v in redis.hgetall(key).items()}


def _key(live_id: str) -> str:
    return f"live:{live_id}"


def create(redis: Redis, scenario: Scenario, brain: str, message: str | None) -> str:
    live_id = str(uuid.uuid4())
    redis.hset(
        _key(live_id),
        mapping={
            "status": "queued",
            "scenario": scenario.id,
            "fixture_id": scenario.fixture_id,
            "brain": brain,
            "message": message or "",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    redis.expire(_key(live_id), TTL_S)
    return live_id


def read(redis: Redis, live_id: str, after: int = 0) -> dict[str, Any] | None:
    info = _hash(redis, _key(live_id))
    if not info:
        return None
    steps = [json.loads(s) for s in redis.lrange(f"{_key(live_id)}:steps", after, -1)]
    return {
        "live_id": live_id,
        "status": info.get("status", "queued"),
        "scenario": info.get("scenario"),
        "brain": info.get("brain"),
        "execution_id": info.get("execution_id") or None,
        "error": info.get("error") or None,
        "verifier_passed": (
            None if "verifier_passed" not in info else info["verifier_passed"] == "1"
        ),
        "steps": steps,
        "next": after + len(steps),
    }


class _Progress:
    """Harness event sink that turns events into compact, UI-ready step records."""

    def __init__(self, redis: Redis, live_id: str) -> None:
        self.redis = redis
        self.key = f"{_key(live_id)}:steps"
        self.started = time.perf_counter()

    def push(self, record: dict[str, Any]) -> None:
        record["t_ms"] = round((time.perf_counter() - self.started) * 1000)
        self.redis.rpush(self.key, json.dumps(record, default=str))
        self.redis.expire(self.key, TTL_S)

    def __call__(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "model_decision":
            self.push(
                {
                    "kind": "decision",
                    "action": data["action"],
                    "tool": data.get("tool"),
                    "args": data.get("args"),
                    "reason": data.get("reason"),
                    "note": data.get("note") or None,
                    "tokens": data.get("usage") or None,
                    "unparsed": bool(data.get("unparsed")),
                }
            )
        elif event_type == "tool_call_end":
            self.push(
                {
                    "kind": "tool",
                    "call_index": data["call_index"],
                    "tool": data["tool"],
                    "args": data["args"],
                    "ok": data["ok"],
                    "result": data.get("result"),
                    "error_code": data.get("error_code"),
                    "error": data.get("error"),
                    "intervention": data.get("intervention"),
                }
            )
        elif event_type == "budget_exhausted":
            self.push({"kind": "budget", "max_tool_calls": data.get("max_tool_calls")})
        elif event_type == "agent_end":
            self.push(
                {
                    "kind": "end",
                    "termination": data.get("termination"),
                    "verifier_passed": data.get("verifier_passed"),
                }
            )


def execute(session_factory: Any, redis: Redis, live_id: str) -> dict[str, str]:
    """Worker side. Never raises for expected problems: they end up in the live record."""
    key = _key(live_id)
    info = _hash(redis, key)
    if not info:
        return {"live_id": live_id, "status": "missing"}
    if info.get("status") in ("done", "error"):
        return {"live_id": live_id, "status": info["status"]}
    redis.hset(key, "status", "running")
    brain = info["brain"]
    try:
        model = build_llm() if brain == "llm" else None
        exporter = MemoryExporter()
        run, _ = run_traced(
            info["fixture_id"],
            exporter,
            capture_content=True,
            model=model,
            message=info.get("message") or None,
            sink=_Progress(redis, live_id),
            extra_attributes={
                "live": {"live_id": live_id, "scenario": info["scenario"], "brain": brain}
            },
        )
        settings = get_settings()
        with session_factory() as session:
            for batch in exporter.batches:
                ingest_batch(
                    session,
                    EventBatch.model_validate(batch),
                    max_payload_bytes=settings.max_event_payload_bytes,
                )
        redis.hset(
            key,
            mapping={
                "status": "done",
                "execution_id": run.execution_id,
                "verifier_passed": "1" if run.verifier.passed else "0",
            },
        )
    except ModelUnavailable as exc:
        redis.hset(key, mapping={"status": "error", "error": f"The AI model is unavailable: {exc}"})
    except Exception as exc:  # noqa: BLE001 - reported to the visitor, logged by RQ
        redis.hset(
            key, mapping={"status": "error", "error": f"The run crashed ({type(exc).__name__})."}
        )
        raise
    return {"live_id": live_id, "status": "done"}
