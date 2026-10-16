"""Tool contracts and sandbox implementations for the demo support agent.

Every tool:
  * has a Pydantic input model (extra fields forbidden) and output model, exported as
    JSON Schema in packages/contracts/tools.v1.json;
  * reports failures as a ToolError with an explicit ErrorCode (never a bare exception);
  * reads/writes ONLY the per-execution Sandbox passed to it. No tool can send email,
    take payment, or open a network connection: there is no code path that does.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_harness.sandbox import Sandbox

TOOL_CONTRACT_VERSION = "1.0"


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SKU_REQUIRED = "SKU_REQUIRED"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"


class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


SKU_PATTERN = r"^SKU-[A-Z0-9-]+$"
ORDER_PATTERN = r"^ORD-[0-9]+$"


# ------------------------------------------------------------------ contracts
class LookupOrderInput(_Strict):
    order_id: str = Field(pattern=ORDER_PATTERN)


class LookupOrderOutput(_Strict):
    order_id: str
    customer_id: str
    sku: str
    product_name: str
    shipping_status: Literal["processing", "shipped", "delivered"]


class LookupInventoryInput(_Strict):
    sku: str = Field(pattern=SKU_PATTERN, description="Stock keeping unit, e.g. SKU-RED-004")


class LookupInventoryOutput(_Strict):
    sku: str
    available: bool
    quantity: int = Field(ge=0)
    as_of: str = Field(description="Fixture timestamp of the inventory snapshot (ISO 8601)")


class GetPolicyInput(_Strict):
    policy_key: Literal["exchange", "refund"]


class GetPolicyOutput(_Strict):
    policy_key: str
    text: str
    version: str


class DraftResponseInput(_Strict):
    customer_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)


class DraftResponseOutput(_Strict):
    draft_id: str
    stored: Literal["sandbox"] = "sandbox"


class SubmitResolutionInput(_Strict):
    order_id: str = Field(pattern=ORDER_PATTERN)
    choice: Literal["exchange", "refund"]


class SubmitResolutionOutput(_Strict):
    resolution_id: str
    stored: Literal["sandbox"] = "sandbox"


# ------------------------------------------------------------------ implementations
def _lookup_order(sb: Sandbox, args: LookupOrderInput) -> LookupOrderOutput:
    order = sb.world["orders"].get(args.order_id)
    if order is None:
        raise ToolError(ErrorCode.ORDER_NOT_FOUND, f"no order {args.order_id}")
    return LookupOrderOutput(order_id=args.order_id, **order)


STALE_FAULT = "stale:lookup_inventory"


def _lookup_inventory(sb: Sandbox, args: LookupInventoryInput) -> LookupInventoryOutput:
    # Stale-retrieval fault: an outdated cached record is served instead of the live one
    # (e.g. "out of stock" from last month while the item is back in stock).
    stale = sb.world.get("stale_inventory", {}).get(args.sku)
    if stale is not None and sb.consume_fault(STALE_FAULT):
        return LookupInventoryOutput(sku=args.sku, **stale)
    item = sb.world["inventory"].get(args.sku)
    if item is None:
        raise ToolError(ErrorCode.SKU_NOT_FOUND, f"no inventory record for {args.sku}")
    return LookupInventoryOutput(sku=args.sku, **item)


def _get_policy(sb: Sandbox, args: GetPolicyInput) -> GetPolicyOutput:
    policy = sb.world["policies"].get(args.policy_key)
    if policy is None:
        raise ToolError(ErrorCode.POLICY_NOT_FOUND, f"no policy {args.policy_key}")
    return GetPolicyOutput(policy_key=args.policy_key, **policy)


def _draft_response(sb: Sandbox, args: DraftResponseInput) -> DraftResponseOutput:
    draft_id = sb.record_effect("draft", args.model_dump())
    return DraftResponseOutput(draft_id=draft_id)


def _submit_resolution(sb: Sandbox, args: SubmitResolutionInput) -> SubmitResolutionOutput:
    resolution_id = sb.record_effect("resolution", args.model_dump())
    return SubmitResolutionOutput(resolution_id=resolution_id)


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    impl: Callable[[Sandbox, Any], BaseModel]
    side_effect: Literal["none", "sandbox_write"]


# The allowlist. Anything not in this dict cannot be called by the agent or by replay.
TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="lookup_order",
            description="Fetch an order: SKU, product, shipping.",
            input_model=LookupOrderInput,
            output_model=LookupOrderOutput,
            impl=_lookup_order,
            side_effect="none",
        ),
        ToolSpec(
            name="lookup_inventory",
            description="Availability for one SKU.",
            input_model=LookupInventoryInput,
            output_model=LookupInventoryOutput,
            impl=_lookup_inventory,
            side_effect="none",
        ),
        ToolSpec(
            name="get_policy",
            description="Refund/exchange policy text.",
            input_model=GetPolicyInput,
            output_model=GetPolicyOutput,
            impl=_get_policy,
            side_effect="none",
        ),
        ToolSpec(
            name="draft_response",
            description="Store a reply draft in the sandbox. Never sends anything.",
            input_model=DraftResponseInput,
            output_model=DraftResponseOutput,
            impl=_draft_response,
            side_effect="sandbox_write",
        ),
        ToolSpec(
            name="submit_resolution",
            description="Record a resolution in the sandbox.",
            input_model=SubmitResolutionInput,
            output_model=SubmitResolutionOutput,
            impl=_submit_resolution,
            side_effect="sandbox_write",
        ),
    ]
}


def _validation_code(tool: str, exc: ValidationError) -> ErrorCode:
    missing = {".".join(str(p) for p in e["loc"]) for e in exc.errors() if e["type"] == "missing"}
    if tool == "lookup_inventory" and "sku" in missing:
        return ErrorCode.SKU_REQUIRED
    return ErrorCode.INVALID_ARGUMENT


def execute_tool(sb: Sandbox, name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Validate arguments, apply fault injection, run the tool. Raises ToolError."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(ErrorCode.UNKNOWN_TOOL, f"{name!r} is not an allowlisted tool")
    try:
        args = spec.input_model.model_validate(raw_args)
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise ToolError(_validation_code(name, exc), f"invalid arguments: {fields}") from None
    if sb.consume_fault(name):
        raise ToolError(ErrorCode.TIMEOUT, f"{name} timed out (injected fault)", retryable=True)
    result = spec.impl(sb, args)
    return spec.output_model.model_validate(result.model_dump()).model_dump()


def tool_json_schemas() -> dict[str, Any]:
    return {
        "contract_version": TOOL_CONTRACT_VERSION,
        "error_codes": [c.value for c in ErrorCode],
        "tools": {
            name: {
                "description": spec.description,
                "side_effect": spec.side_effect,
                "input": spec.input_model.model_json_schema(),
                "output": spec.output_model.model_json_schema(),
            }
            for name, spec in sorted(TOOLS.items())
        },
    }
