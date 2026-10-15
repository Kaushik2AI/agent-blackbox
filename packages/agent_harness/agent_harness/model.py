"""Model interface and the deterministic stub model.

`StubModel` is a scripted planner standing in for an LLM so the whole platform runs on a
CPU with identical results every time (replay class `deterministic`). Its behaviour on a
fixture is fully determined by the fixture's `model` script:

  * inventory_argument="sku"           -> calls lookup_inventory(sku=...) correctly
  * inventory_argument="product_name"  -> calls lookup_inventory(product_name=...), the
                                          flagship bug, and naively repeats failed calls
  * max_retries_on_timeout             -> how many times a TIMEOUT is retried
  * resolution_order_id                -> submit the resolution for this (wrong) order id

A real LLM adapter (M9) implements the same `Model` protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agent_harness.fixtures import ModelScript


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Finish:
    reason: Literal["completed", "tool_failure"]


Action = ToolCall | Finish


class Model(Protocol):
    name: str

    def next_action(self, state: dict[str, Any]) -> Action: ...


class StubModel:
    name = "stub-planner-v1"

    def __init__(self, script: ModelScript) -> None:
        self.script = script

    def next_action(self, state: dict[str, Any]) -> Action:
        history: list[dict[str, Any]] = state["history"]
        if history and not history[-1]["ok"]:
            return self._after_failure(history)

        task = state["task"]
        obs = state["observations"]
        if "order" not in obs:
            return ToolCall("lookup_order", {"order_id": task["order_id"]})
        order = obs["order"]
        if "inventory" not in obs:
            if self.script.inventory_argument == "product_name":
                return ToolCall("lookup_inventory", {"product_name": order["product_name"]})
            return ToolCall("lookup_inventory", {"sku": order["sku"]})

        choice = (
            "exchange"
            if task["request"] == "exchange" and obs["inventory"]["available"]
            else "refund"
        )
        if choice not in obs.get("policies", {}):
            return ToolCall("get_policy", {"policy_key": choice})
        if "draft_id" not in obs:
            return ToolCall(
                "draft_response",
                {"customer_id": task["customer_id"], "text": _draft_text(order, choice)},
            )
        if "resolution_id" not in obs:
            # resolution_order_id simulates an identity bug: the model "remembers" the wrong
            # order between steps (see the wrong_order_identity fixture).
            order_id = self.script.resolution_order_id or order["order_id"]
            return ToolCall("submit_resolution", {"order_id": order_id, "choice": choice})
        return Finish("completed")

    def _after_failure(self, history: list[dict[str, Any]]) -> Action:
        last = history[-1]
        retry = ToolCall(last["tool"], dict(last["args"]))
        if last["error_code"] == "TIMEOUT":
            consecutive = 0
            for step in reversed(history):
                if step["ok"] or step["tool"] != last["tool"]:
                    break
                consecutive += 1
            return (
                retry
                if consecutive <= self.script.max_retries_on_timeout
                else Finish("tool_failure")
            )
        # Naive behaviour on validation errors: repeat the same call unchanged. This is the
        # failure mode the invalid_inventory_argument fixture exists to exhibit.
        return retry


def _draft_text(order: dict[str, Any], choice: str) -> str:
    action = "arrange an exchange" if choice == "exchange" else "issue a full refund"
    return (
        f"Hi, sorry about the problem with your {order['product_name']} "
        f"(order {order['order_id']}). We will {action} for you."
    )
