"""One-click fix suggestions for a failed run.

A suggestion is an ordinary replay request (checkpoint + exactly one intervention) built
from what the run itself recorded: e.g. the product code the agent had already seen in
the order, or the stock level the sandbox would have returned. It is a hypothesis to
test, not a claimed root cause; the replay's verifier decides whether it worked.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Checkpoint, Event, Execution, ExecutionStatus
from app.services.checkpoints import load_and_check

_BAD_INPUT = {"SKU_REQUIRED", "INVALID_ARGUMENT", "SKU_NOT_FOUND"}


def _tool_steps(session: Session, execution_id: uuid.UUID) -> list[dict[str, Any]]:
    steps = []
    for e in session.scalars(
        select(Event)
        .where(Event.execution_id == execution_id, Event.event_type == "tool_call_end")
        .order_by(Event.sequence_no)
    ):
        p = e.payload_json or {}
        if p.get("capture") != "content":
            continue
        steps.append(
            {
                "call_index": (e.attributes_json or {}).get("call_index"),
                "tool": e.tool_name,
                "args": p.get("input_redacted") or {},
                "ok": e.status == "ok",
                "output": p.get("output"),
                "error_code": p.get("error_code"),
                "span_id": e.span_id,
            }
        )
    return steps


def _none(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def suggest_fix(session: Session, execution_id: uuid.UUID) -> dict[str, Any]:
    ex = session.get(Execution, execution_id)
    if ex is None:
        raise LookupError(execution_id)
    if ex.status == ExecutionStatus.SUCCEEDED:
        return _none("This run passed, so there is nothing to fix.")
    steps = _tool_steps(session, execution_id)
    if not steps:
        return _none("This run was recorded without step details, so it can't be re-run.")
    order = next((s["output"] for s in steps if s["tool"] == "lookup_order" and s["ok"]), None)

    plan: dict[str, Any] | None = None
    for i, step in enumerate(steps):
        if not step["ok"]:
            code = step["error_code"]
            recovered = any(s["ok"] and s["tool"] == step["tool"] for s in steps[i + 1 :])
            if recovered:
                continue  # e.g. a timeout the agent retried successfully
            if (
                step["tool"] == "lookup_inventory"
                and code in _BAD_INPUT
                and isinstance(order, dict)
                and order.get("sku")
                and step["args"].get("sku") != order["sku"]
            ):
                plan = {
                    "step": step,
                    "type": "replace_tool_argument",
                    "value": {"sku": order["sku"]},
                    "label": f"Use the product code {order['sku']}",
                    "explanation": (
                        "The stock check needs a product code. The order the agent had "
                        f"already looked up says the code is {order['sku']}."
                    ),
                }
            elif code == "TIMEOUT":
                plan = {
                    "step": step,
                    "type": "replace_tool_result",
                    "value": None,  # filled from the checkpoint's sandbox below
                    "label": f"Pretend {step['tool'].replace('_', ' ')} answered",
                    "explanation": (
                        "The system never answered. Re-run as if it had returned its real "
                        "data, to check that the rest of the agent works."
                    ),
                }
            elif code in ("ORDER_NOT_FOUND", "INVALID_ARGUMENT") and step["tool"] == "lookup_order":
                plan = {
                    "step": step,
                    "type": "replace_tool_argument",
                    "value": None,  # the ticket's order id, from the checkpoint
                    "label": "Look up the order from the ticket",
                    "explanation": "The agent asked for an order that doesn't exist.",
                }
            break
        if (
            step["tool"] == "submit_resolution"
            and isinstance(order, dict)
            and step["args"].get("order_id") not in (None, order.get("order_id"))
        ):
            plan = {
                "step": step,
                "type": "replace_tool_argument",
                "value": {"order_id": order["order_id"], "choice": step["args"].get("choice")},
                "label": f"Submit for the right order ({order['order_id']})",
                "explanation": (
                    f"The agent looked up {order['order_id']} but closed "
                    f"{step['args'].get('order_id')}."
                ),
            }
            break
    if plan is None:
        return _none(
            "No one-click fix for this kind of failure. You can still try your own change "
            "in Replay Studio."
        )

    step = plan["step"]
    checkpoint = session.scalars(
        select(Checkpoint).where(
            Checkpoint.execution_id == execution_id,
            Checkpoint.step_index == step["call_index"],
        )
    ).first()
    if checkpoint is None:
        return _none("No saved checkpoint before that step.")
    check = load_and_check(checkpoint)
    if not check.eligible or check.document is None:
        return _none("This run can't be re-run: " + "; ".join(check.reasons))
    doc = check.document
    value = plan["value"]
    if plan["type"] == "replace_tool_result":
        world = doc["sandbox"]["world"]
        args = step["args"]
        if step["tool"] == "lookup_inventory" and args.get("sku") in world["inventory"]:
            value = {"sku": args["sku"], **world["inventory"][args["sku"]]}
        elif step["tool"] == "lookup_order" and args.get("order_id") in world["orders"]:
            value = {"order_id": args["order_id"], **world["orders"][args["order_id"]]}
        else:
            return _none("No one-click fix: the sandbox has no answer for that call.")
    elif value is None:
        value = {"order_id": doc["graph_state"]["task"]["order_id"]}

    intervention: dict[str, Any] = {
        "type": plan["type"],
        "target_span_id": step["span_id"],
    }
    intervention["arguments" if plan["type"] == "replace_tool_argument" else "result"] = value
    return {
        "available": True,
        "label": plan["label"],
        "explanation": plan["explanation"],
        "call_index": step["call_index"],
        "tool": step["tool"],
        "before": step["args"],
        "request": {
            "source_execution_id": str(execution_id),
            "checkpoint_id": str(checkpoint.id),
            "intervention": intervention,
        },
    }
