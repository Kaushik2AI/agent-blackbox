"""Tool contracts: validation, explicit error codes, fault injection, sandbox-only effects."""

import pytest

from agent_harness.fixtures import load_fixture
from agent_harness.sandbox import Sandbox
from agent_harness.tools import TOOLS, ErrorCode, ToolError, execute_tool


@pytest.fixture
def sandbox() -> Sandbox:
    fx = load_fixture("exchange_success")
    return Sandbox.from_fixture(fx.world, {})


def test_allowlist_is_exactly_the_five_blueprint_tools() -> None:
    assert set(TOOLS) == {
        "lookup_order",
        "lookup_inventory",
        "get_policy",
        "draft_response",
        "submit_resolution",
    }


def test_product_name_instead_of_sku_is_sku_required(sandbox: Sandbox) -> None:
    with pytest.raises(ToolError) as err:
        execute_tool(sandbox, "lookup_inventory", {"product_name": "red backpack"})
    assert err.value.code is ErrorCode.SKU_REQUIRED


def test_malformed_sku_is_invalid_argument(sandbox: Sandbox) -> None:
    with pytest.raises(ToolError) as err:
        execute_tool(sandbox, "lookup_inventory", {"sku": "red-backpack"})
    assert err.value.code is ErrorCode.INVALID_ARGUMENT


def test_unknown_tool_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(ToolError) as err:
        execute_tool(sandbox, "send_email", {"to": "x@example.com"})
    assert err.value.code is ErrorCode.UNKNOWN_TOOL


def test_unknown_order_and_sku(sandbox: Sandbox) -> None:
    with pytest.raises(ToolError) as e1:
        execute_tool(sandbox, "lookup_order", {"order_id": "ORD-9999"})
    with pytest.raises(ToolError) as e2:
        execute_tool(sandbox, "lookup_inventory", {"sku": "SKU-NOPE"})
    assert (e1.value.code, e2.value.code) == (ErrorCode.ORDER_NOT_FOUND, ErrorCode.SKU_NOT_FOUND)


def test_valid_calls_return_contract_shaped_results(sandbox: Sandbox) -> None:
    order = execute_tool(sandbox, "lookup_order", {"order_id": "ORD-1001"})
    assert order["sku"] == "SKU-RED-004"
    inv = execute_tool(sandbox, "lookup_inventory", {"sku": order["sku"]})
    assert inv == {
        "sku": "SKU-RED-004",
        "available": True,
        "quantity": 12,
        "as_of": "2026-10-01T09:00:00Z",
    }


def test_injected_timeout_fires_then_clears() -> None:
    fx = load_fixture("exchange_success")
    sb = Sandbox.from_fixture(fx.world, {"lookup_inventory": 1})
    with pytest.raises(ToolError) as err:
        execute_tool(sb, "lookup_inventory", {"sku": "SKU-RED-004"})
    assert err.value.code is ErrorCode.TIMEOUT and err.value.retryable
    assert execute_tool(sb, "lookup_inventory", {"sku": "SKU-RED-004"})["available"] is True


def test_validation_happens_before_fault_injection() -> None:
    """A bad argument must surface as a validation error, not be masked by a timeout."""
    fx = load_fixture("exchange_success")
    sb = Sandbox.from_fixture(fx.world, {"lookup_inventory": 1})
    with pytest.raises(ToolError) as err:
        execute_tool(sb, "lookup_inventory", {"product_name": "x"})
    assert err.value.code is ErrorCode.SKU_REQUIRED
    assert sb.faults["lookup_inventory"] == 1


def test_side_effecting_tools_only_write_to_the_sandbox(sandbox: Sandbox) -> None:
    out = execute_tool(sandbox, "draft_response", {"customer_id": "C-17", "text": "hi"})
    assert out == {"draft_id": "draft-1", "stored": "sandbox"}
    out = execute_tool(sandbox, "submit_resolution", {"order_id": "ORD-1001", "choice": "refund"})
    assert out == {"resolution_id": "resolution-1", "stored": "sandbox"}
    assert [e.kind for e in sandbox.effects] == ["draft", "resolution"]


def test_extra_fields_are_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(ToolError) as err:
        execute_tool(
            sandbox,
            "submit_resolution",
            {"order_id": "ORD-1001", "choice": "refund", "amount": 10_000},
        )
    assert err.value.code is ErrorCode.INVALID_ARGUMENT
    assert sandbox.effects == []
