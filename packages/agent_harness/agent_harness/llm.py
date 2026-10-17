"""Real-model adapter: any OpenAI-compatible chat endpoint (OpenRouter, DashScope, vLLM on
a GPU server, Ollama, ...). The default target is a Qwen instruct model.

The model is asked for ONE JSON action per turn instead of native tool calling, because
JSON-in-text works the same on every provider and every model size:

    {"note": "why", "tool": "lookup_order", "args": {"order_id": "ORD-1001"}}
    {"note": "why", "finish": "completed"}        # or "gave_up"

The conversation is rebuilt from the graph state on every turn (it is never kept in the
adapter), so a run resumed from a checkpoint sees exactly the history it had.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent_harness.model import Action, Finish, ToolCall
from agent_harness.tools import TOOLS

# Bumped whenever the prompt or the conversation format changes; recorded with results.
PROMPT_VERSION = "2"

# Status lines added after a successful call with a lasting effect. Without them a small
# model sees "Result of submit_resolution: {...}" and often starts the reply-and-close
# sequence again, which saves duplicates (seen with Qwen2.5-3B in the first GPU run).
_DONE_NOTES = {
    "draft_response": "The reply draft is saved. Do not write another one.",
    "submit_resolution": (
        "The resolution is saved and the ticket is closed. Nothing is left to do: "
        'answer with {"note": "<short summary>", "finish": "completed"}.'
    ),
}


class ModelUnavailable(RuntimeError):
    """The model endpoint could not be reached or refused the request."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    label: str = ""
    temperature: float = 0.2
    max_tokens: int = 400
    timeout_s: float = 45.0
    extra_headers: dict[str, str] = field(default_factory=dict)


def _tool_lines() -> str:
    lines = []
    for name, spec in TOOLS.items():
        schema = spec.input_model.model_json_schema()
        params = []
        for pname, prop in schema.get("properties", {}).items():
            kind = prop.get("type", "string")
            if "enum" in prop:
                kind = " | ".join(json.dumps(v) for v in prop["enum"])
            elif "pattern" in prop:
                kind = f"string matching {prop['pattern']}"
            params.append(f"{pname}: {kind}")
        lines.append(f"- {name}({', '.join(params)}): {spec.description}")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are a customer-support agent for an online shop. Resolve the ticket
by calling tools, one at a time.

Tools:
{_tool_lines()}

How to work:
1. Look up the order.
2. If the customer wants an exchange, check stock for the order's product.
3. Choose "exchange" if they asked for one and the item is in stock, otherwise "refund".
   Read the policy for the option you chose.
4. Write ONE reply draft for the customer, then submit ONE resolution, then finish.
   draft_response and submit_resolution each save something permanent: call each of them
   exactly once. After submit_resolution succeeds the ticket is closed; finish right away.

Answer with ONE JSON object and nothing else:
{{"note": "<short sentence: what you do and why>", "tool": "<tool name>", "args": {{...}}}}
When everything is done:
{{"note": "<short summary>", "finish": "completed"}}
If you cannot continue:
{{"note": "<why>", "finish": "gave_up"}}"""


def build_messages(state: dict[str, Any]) -> list[dict[str, str]]:
    task = state["task"]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"New ticket. Customer id: {task['customer_id']}. "
                f"Order id: {task['order_id']}.\nCustomer message: {task['message']}"
            ),
        },
    ]
    for step in state["history"]:
        action: dict[str, Any] = {"tool": step["tool"], "args": step["args"]}
        if step.get("note"):
            action = {"note": step["note"], **action}
        messages.append({"role": "assistant", "content": json.dumps(action)})
        if step["ok"]:
            body = f"Result of {step['tool']}: {json.dumps(step['result'])}"
            if step["tool"] in _DONE_NOTES:
                body += "\n" + _DONE_NOTES[step["tool"]]
        else:
            body = f"Error from {step['tool']}: {step['error_code']}: {step.get('error', '')}"
        messages.append({"role": "user", "content": body})
    return messages


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_action(text: str) -> dict[str, Any] | None:
    """First JSON object in the reply (code fences and chatter around it are tolerated;
    a reasoning model's <think>...</think> block is ignored)."""
    text = _THINK.sub("", text)
    fenced = _FENCE.search(text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start in [i for i, ch in enumerate(candidate) if ch == "{"]:
            try:
                value, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and ("tool" in value or "finish" in value):
                return value
    return None


def to_action(obj: dict[str, Any]) -> tuple[Action, str]:
    note = str(obj.get("note") or "")[:300]
    if "finish" in obj:
        return Finish("completed" if obj["finish"] == "completed" else "tool_failure"), note
    raw = obj.get("args")
    args: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    return ToolCall(str(obj["tool"]), args), note


class OpenAICompatModel:
    """Model protocol implementation backed by a chat-completions endpoint."""

    def __init__(self, config: LLMConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.name = f"llm:{config.model}"
        self.client = client or httpx.Client(timeout=config.timeout_s)
        # Details of the most recent decision, read by the graph for tracing.
        self.last_call: dict[str, Any] = {}

    def _complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        cfg = self.config
        try:
            resp = self.client.post(
                cfg.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {cfg.api_key}", **cfg.extra_headers},
                json={
                    "model": cfg.model,
                    "messages": messages,
                    "temperature": cfg.temperature,
                    "max_tokens": cfg.max_tokens,
                },
            )
        except httpx.HTTPError as exc:
            raise ModelUnavailable(
                f"could not reach the model API ({type(exc).__name__})"
            ) from None
        if resp.status_code != 200:
            raise ModelUnavailable(f"model API answered HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"] or ""
            # Control characters (a confused small model emits them) are dropped.
            text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelUnavailable("model API returned an unexpected response") from None
        usage = body.get("usage") or {}
        return text, {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        }

    def next_action(self, state: dict[str, Any]) -> Action:
        messages = build_messages(state)
        started = time.perf_counter()
        tokens = {"input_tokens": 0, "output_tokens": 0}
        text = ""
        obj: dict[str, Any] | None = None
        for attempt in range(2):
            text, usage = self._complete(messages)
            tokens = {k: tokens[k] + usage[k] for k in tokens}
            obj = parse_action(text)
            if obj is not None:
                break
            if attempt == 0:
                messages = [
                    *messages,
                    {"role": "assistant", "content": text[:2000]},
                    {"role": "user", "content": "Reply with exactly one JSON object as specified."},
                ]
        if obj is None:
            action: Action = Finish("tool_failure")
            note = "The model's reply could not be read as an action."
        else:
            action, note = to_action(obj)
        self.last_call = {
            "note": note,
            "usage": tokens,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "unparsed": obj is None,
            "raw_preview": text[:300] if obj is None else None,
        }
        return action
