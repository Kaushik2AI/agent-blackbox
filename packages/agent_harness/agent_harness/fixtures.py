"""Versioned fixture tasks. Each fixture is an immutable JSON file in ./fixtures/.

`ground_truth` is what a CORRECT agent would leave in the sandbox; the verifier checks
the final sandbox against it. `expected_baseline` records how the stock (scripted) agent
is known to behave on this fixture; tests use it to prove failures happen for the
intended reason. Neither is ever shown to the agent.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Termination = Literal["completed", "budget_exhausted", "tool_failure", "error"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Task(_Strict):
    customer_id: str
    order_id: str
    request: Literal["exchange", "refund"]
    message: str


class ModelScript(_Strict):
    """Behaviour knobs for the deterministic stub model (see model.py)."""

    inventory_argument: Literal["sku", "product_name"] = "sku"
    max_retries_on_timeout: int = Field(default=2, ge=0)


class Budget(_Strict):
    max_tool_calls: int = Field(ge=1)


class Resolution(_Strict):
    order_id: str
    choice: Literal["exchange", "refund"]


class GroundTruth(_Strict):
    resolution: Resolution
    draft_customer_id: str


class ExpectedBaseline(_Strict):
    verifier_passed: bool
    termination: Termination
    error_codes: list[str]


class Fixture(_Strict):
    fixture_id: str
    fixture_version: str
    description: str
    task: Task
    world: dict[str, Any]
    faults: dict[str, int]
    model: ModelScript
    budget: Budget
    ground_truth: GroundTruth
    expected_baseline: ExpectedBaseline

    @property
    def content_hash(self) -> str:
        """SHA-256 of the canonical fixture JSON: identifies exactly what was run."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()


def _fixture_files() -> dict[str, Any]:
    root = resources.files("agent_harness") / "fixtures"
    return {p.name.removesuffix(".json"): p for p in root.iterdir() if p.name.endswith(".json")}


def list_fixtures() -> list[str]:
    return sorted(_fixture_files())


@cache
def load_fixture(fixture_id: str) -> Fixture:
    files = _fixture_files()
    if fixture_id not in files:
        raise KeyError(f"unknown fixture {fixture_id!r}; available: {', '.join(sorted(files))}")
    fixture = Fixture.model_validate_json(files[fixture_id].read_text())
    if fixture.fixture_id != fixture_id:
        raise ValueError(f"{fixture_id}.json declares fixture_id={fixture.fixture_id!r}")
    return fixture
