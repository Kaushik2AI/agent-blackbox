"""The real-model adapter, exercised against a fake OpenAI-compatible endpoint."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agent_harness.interventions import ReplaceToolArguments
from agent_harness.llm import (
    LLMConfig,
    ModelUnavailable,
    OpenAICompatModel,
    build_messages,
    parse_action,
)
from agent_harness.runner import run_fixture, run_from_checkpoint

CORRECT = [
    {"note": "find the order", "tool": "lookup_order", "args": {"order_id": "ORD-1001"}},
    {"note": "check stock", "tool": "lookup_inventory", "args": {"sku": "SKU-RED-004"}},
    {"note": "read policy", "tool": "get_policy", "args": {"policy_key": "exchange"}},
    {
        "note": "reply",
        "tool": "draft_response",
        "args": {"customer_id": "C-17", "text": "We will exchange your backpack."},
    },
    {
        "note": "close",
        "tool": "submit_resolution",
        "args": {"order_id": "ORD-1001", "choice": "exchange"},
    },
    {"note": "done", "finish": "completed"},
]


def fake_model(replies: list[str], seen: list[Any] | None = None) -> OpenAICompatModel:
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        text = queue.pop(0) if queue else json.dumps({"finish": "gave_up"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatModel(LLMConfig("https://fake.test/v1", "k", "qwen-test"), client=client)


def test_parse_action_tolerates_fences_and_chatter() -> None:
    assert parse_action('Sure!\n```json\n{"tool": "x", "args": {}}\n```') == {
        "tool": "x",
        "args": {},
    }
    assert parse_action('I think {"finish": "completed", "note": "ok"} done') == {
        "finish": "completed",
        "note": "ok",
    }
    assert parse_action('<think>maybe {"tool": "wrong"}</think>{"finish": "completed"}') == {
        "finish": "completed"
    }
    assert parse_action("no json here") is None
    assert parse_action('{"unrelated": 1}') is None


def test_correct_model_passes_the_verifier_and_records_usage() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    model = fake_model([json.dumps(a) for a in CORRECT])
    run = run_fixture("exchange_success", model=model, on_event=lambda t, d: events.append((t, d)))
    assert run.verifier.passed and run.termination == "completed"
    assert run.model_name == "llm:qwen-test"
    assert run.determinism == "controlled_stochastic"
    decisions = [d for t, d in events if t == "model_decision"]
    assert decisions[0]["note"] == "find the order"
    assert decisions[0]["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert run.history[0]["note"] == "find the order"


def test_wrong_argument_from_the_model_is_a_real_tool_error() -> None:
    bad = {"tool": "lookup_inventory", "args": {"product_name": "red backpack"}}
    replies = [json.dumps(CORRECT[0])] + [json.dumps(bad)] * 10
    run = run_fixture("exchange_success", model=fake_model(replies))
    assert not run.verifier.passed
    assert run.termination == "budget_exhausted"
    assert run.error_codes == ["SKU_REQUIRED"]


def test_history_is_replayed_into_the_conversation() -> None:
    seen: list[Any] = []
    run_fixture("exchange_success", model=fake_model([json.dumps(a) for a in CORRECT], seen))
    last = seen[-1]["messages"]
    assert last[0]["role"] == "system"
    assert "ORD-1001" in last[1]["content"]
    assert any("Result of lookup_order" in m["content"] for m in last if m["role"] == "user")


def test_the_model_is_told_when_the_ticket_is_closed() -> None:
    seen: list[Any] = []
    run_fixture("exchange_success", model=fake_model([json.dumps(a) for a in CORRECT], seen))
    last = [m["content"] for m in seen[-1]["messages"] if m["role"] == "user"]
    draft = next(m for m in last if m.startswith("Result of draft_response"))
    closed = next(m for m in last if m.startswith("Result of submit_resolution"))
    assert "Do not write another one" in draft
    assert "ticket is closed" in closed and '"finish": "completed"' in closed
    lookup = next(m for m in last if m.startswith("Result of lookup_order"))
    assert "\n" not in lookup


def test_unreadable_reply_is_retried_once_then_gives_up() -> None:
    run = run_fixture("exchange_success", model=fake_model(["hmm", "still no json"]))
    assert run.termination == "tool_failure"
    assert run.tool_calls == 0


def test_custom_message_reaches_the_model() -> None:
    seen: list[Any] = []
    run_fixture(
        "exchange_success",
        model=fake_model([json.dumps({"finish": "gave_up"})], seen),
        message="Zip broke on day one!",
    )
    assert "Zip broke on day one!" in seen[0]["messages"][1]["content"]


def test_http_errors_raise_model_unavailable() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no")))
    model = OpenAICompatModel(LLMConfig("https://fake.test/v1", "k", "m"), client=client)
    with pytest.raises(ModelUnavailable, match="HTTP 401"):
        model.next_action(
            {"task": {"customer_id": "C", "order_id": "O", "message": "m"}, "history": []}
        )


def test_checkpoint_resume_with_a_real_model_and_a_fix() -> None:
    bad = {"tool": "lookup_inventory", "args": {"product_name": "red backpack"}}
    checkpoints: list[dict[str, Any]] = []

    def grab(t: str, d: dict[str, Any]) -> None:
        if t == "checkpoint":
            checkpoints.append(d["document"])

    replies = [json.dumps(CORRECT[0])] + [json.dumps(bad)] * 10
    source = run_fixture("exchange_success", model=fake_model(replies), on_event=grab)
    assert not source.verifier.passed
    # Resume before call #1 with the right argument; the model then continues correctly.
    fork = run_from_checkpoint(
        checkpoints[1],
        [ReplaceToolArguments(call_index=1, arguments={"sku": "SKU-RED-004"})],
        model=fake_model([json.dumps(a) for a in CORRECT[2:]]),
    )
    assert fork.verifier.passed
    assert build_messages(checkpoints[1]["graph_state"])[2]["role"] == "assistant"


def test_control_characters_from_the_model_are_dropped() -> None:
    import httpx

    from agent_harness.llm import LLMConfig, OpenAICompatModel

    def handler(request: httpx.Request) -> httpx.Response:
        text = '\x00\x07{"note": "ok\x00", "finish": "completed"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    model = OpenAICompatModel(
        LLMConfig("https://fake.test/v1", "k", "m"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    text, _ = model._complete([])
    assert text == '{"note": "ok", "finish": "completed"}'
