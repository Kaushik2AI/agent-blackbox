"""The two kinds of single change the benchmark compares.

* plan_repair: the change FlightPath would suggest, built only from what the run itself
  recorded (the same rules as the app's one-click fix). It never reads the ground truth.
* random_intervention: a random change of the same kind (one tool call, one valid input
  or output from the same world), the baseline that a real fix must beat.

Both return a contract-valid intervention plus the call index to restart before.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from agent_harness.interventions import (
    Intervention,
    ReplaceToolArguments,
    ReplaceToolResult,
    validate_intervention,
)
from agent_harness.runner import RunResult

_BAD_INPUT = {"SKU_REQUIRED", "INVALID_ARGUMENT", "SKU_NOT_FOUND"}

# call index -> pre-step checkpoint document (as emitted by the harness)
Checkpoints = dict[int, dict[str, Any]]


@dataclass(frozen=True)
class Change:
    intervention: Intervention
    tool: str
    label: str

    @property
    def call_index(self) -> int:
        return self.intervention.call_index

    def describe(self) -> dict[str, Any]:
        payload = (
            self.intervention.arguments
            if isinstance(self.intervention, ReplaceToolArguments)
            else self.intervention.result
        )
        return {
            "type": self.intervention.type,
            "call_index": self.call_index,
            "tool": self.tool,
            "label": self.label,
            "payload": payload,
        }


def _world(checkpoints: Checkpoints, call_index: int) -> dict[str, Any]:
    world: dict[str, Any] = checkpoints[call_index]["sandbox"]["world"]
    return world


def plan_repair(run: RunResult, checkpoints: Checkpoints) -> Change | None:
    history = run.history
    order = next((s["result"] for s in history if s["tool"] == "lookup_order" and s["ok"]), None)
    for i, step in enumerate(history):
        idx = int(step["call_index"])
        if idx not in checkpoints:
            continue
        if not step["ok"]:
            recovered = any(s["ok"] and s["tool"] == step["tool"] for s in history[i + 1 :])
            if recovered:
                continue
            code = step["error_code"]
            change: Intervention | None = None
            label = ""
            if (
                step["tool"] == "lookup_inventory"
                and code in _BAD_INPUT
                and isinstance(order, dict)
                and order.get("sku")
                and step["args"].get("sku") != order["sku"]
            ):
                change = ReplaceToolArguments(idx, {"sku": order["sku"]})
                label = "use the product code from the order"
            elif code in ("ORDER_NOT_FOUND", "INVALID_ARGUMENT") and step["tool"] == "lookup_order":
                ticket = checkpoints[idx]["graph_state"]["task"]["order_id"]
                change = ReplaceToolArguments(idx, {"order_id": ticket})
                label = "look up the order id from the ticket"
            elif code == "TIMEOUT":
                world = _world(checkpoints, idx)
                args = step["args"]
                if step["tool"] == "lookup_inventory" and args.get("sku") in world["inventory"]:
                    change = ReplaceToolResult(
                        idx, {"sku": args["sku"], **world["inventory"][args["sku"]]}
                    )
                elif step["tool"] == "lookup_order" and args.get("order_id") in world["orders"]:
                    change = ReplaceToolResult(
                        idx, {"order_id": args["order_id"], **world["orders"][args["order_id"]]}
                    )
                label = "answer as the system would have"
            if change is None:
                return None
            return Change(validate_intervention(change, step["tool"]), step["tool"], label)
        if (
            step["tool"] == "submit_resolution"
            and isinstance(order, dict)
            and step["args"].get("order_id") not in (None, order.get("order_id"))
        ):
            fixed = ReplaceToolArguments(
                idx, {"order_id": order["order_id"], "choice": step["args"].get("choice")}
            )
            return Change(
                validate_intervention(fixed, step["tool"]),
                step["tool"],
                "submit for the order that was looked up",
            )
    return None


def _valid_args(tool: str, world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    orders = sorted(world["orders"])
    if tool == "lookup_order":
        return {"order_id": rng.choice(orders)}
    if tool == "lookup_inventory":
        return {"sku": rng.choice(sorted(world["inventory"]))}
    if tool == "get_policy":
        return {"policy_key": rng.choice(sorted(world["policies"]))}
    if tool == "draft_response":
        customer = world["orders"][rng.choice(orders)]["customer_id"]
        return {"customer_id": customer, "text": "We are looking into your request."}
    if tool == "submit_resolution":
        return {"order_id": rng.choice(orders), "choice": rng.choice(["exchange", "refund"])}
    raise ValueError(f"no random arguments for {tool}")


def _valid_result(tool: str, world: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    if tool == "lookup_order":
        oid = rng.choice(sorted(world["orders"]))
        return {"order_id": oid, **world["orders"][oid]}
    if tool == "lookup_inventory":
        sku = rng.choice(sorted(world["inventory"]))
        return {"sku": sku, **world["inventory"][sku]}
    if tool == "get_policy":
        key = rng.choice(sorted(world["policies"]))
        return {"policy_key": key, **world["policies"][key]}
    if tool == "draft_response":
        return {"draft_id": "draft-1"}
    if tool == "submit_resolution":
        return {"resolution_id": "resolution-1"}
    raise ValueError(f"no random result for {tool}")


def random_intervention(run: RunResult, checkpoints: Checkpoints, rng: random.Random) -> Change:
    """One random, contract-valid change to one recorded tool call."""
    steps = [s for s in run.history if int(s["call_index"]) in checkpoints]
    if not steps:
        raise ValueError("no checkpointed tool call to change")
    step = rng.choice(steps)
    idx = int(step["call_index"])
    world = _world(checkpoints, idx)
    change: Intervention
    if rng.random() < 0.5:
        change = ReplaceToolArguments(idx, _valid_args(step["tool"], world, rng))
        label = "random input"
    else:
        change = ReplaceToolResult(idx, _valid_result(step["tool"], world, rng))
        label = "random answer"
    return Change(validate_intervention(change, step["tool"]), step["tool"], label)


def restart_point(run: RunResult, repair: Change | None, checkpoints: Checkpoints) -> int:
    """Where the no-change replay restarts: the repair's step, else the first failing
    step, else the second step (or the first, for one-step runs)."""
    if repair is not None:
        return repair.call_index
    failing = next((int(s["call_index"]) for s in run.history if not s["ok"]), None)
    if failing is not None and failing in checkpoints:
        return failing
    indexes = sorted(checkpoints)
    return indexes[1] if len(indexes) > 1 else indexes[0]
