"""The versioned benchmark dataset: synthetic customer-support cases in eight families.

    python -m evaluation.dataset --write     # (re)generate the committed JSONL
    python -m evaluation.dataset --check     # fail if the committed file has drifted

Cases are generated from a fixed seed, so the file is reproducible byte for byte. The
committed copy lives with the agent harness (agent_harness/benchmarks/) so every part of
the app (API, replay worker, importer) can resolve a case by its id.

The last two cases of every family are the held-out split. Nothing in FlightPath is
tuned on them: the repair policy and detectors are rule-based and were written against
the hand-made demo fixtures, not these cases.
"""

from __future__ import annotations

import argparse
import random
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from agent_harness.fixtures import BenchmarkCase, Fixture

VERSION = "benchmark_v1"
FIXTURE_VERSION = "bm1.0"
SEED = 20261016
HELDOUT_PER_FAMILY = 2

# family -> (number of cases, what the scripted agent does, expected detector categories)
FAMILIES: dict[str, tuple[int, str, list[str]]] = {
    "control_exchange": (8, "Item in stock; the agent should arrange an exchange.", []),
    "control_refund": (6, "Item out of stock; the right answer is a refund.", []),
    "control_recovered_timeout": (6, "The stock check times out once; a retry works.", []),
    "invalid_argument": (
        8,
        "The agent sends the product name instead of the product code and repeats it.",
        ["tool_schema_mismatch", "retry_loop", "budget_exhausted"],
    ),
    "repeat_loop": (
        6,
        "The agent writes the order id in lower case, the lookup rejects it, and it repeats.",
        ["tool_schema_mismatch", "retry_loop", "budget_exhausted"],
    ),
    "persistent_timeout": (
        6,
        "The stock system never answers; the agent gives up.",
        ["tool_timeout"],
    ),
    "stale_retrieval": (
        6,
        "An outdated cached stock record says 'out of stock', so the agent refunds "
        "instead of exchanging.",
        ["stale_data"],
    ),
    "wrong_identity": (
        6,
        "The agent looks up one order but closes the ticket on another customer's order.",
        ["state_identity_mismatch"],
    ),
}

PRODUCTS = [
    ("red backpack", "RED"),
    ("blue water bottle", "BLU"),
    ("green yoga mat", "GRN"),
    ("black headphones", "BLK"),
    ("white sneakers", "WHT"),
    ("grey hoodie", "GRY"),
    ("silver watch", "SLV"),
    ("orange tent", "ORG"),
    ("yellow raincoat", "YLW"),
    ("purple scarf", "PRP"),
]
DEFECTS = [
    "arrived with a broken zip",
    "arrived scratched",
    "stopped working after two days",
    "arrived in the wrong size",
    "has a torn seam",
    "arrived with a missing part",
]
POLICIES = {
    "exchange": {
        "text": "Delivered items may be exchanged for the same SKU within 30 days if in stock.",
        "version": "2026-09",
    },
    "refund": {
        "text": (
            "If an exchange is not possible, a full refund is issued within 30 days of delivery."
        ),
        "version": "2026-09",
    },
}


def _case(family: str, index: int, rng: random.Random) -> BenchmarkCase:
    count, description, expected = FAMILIES[family]
    products = rng.sample(PRODUCTS, 4)  # the customer's item + 3 decoys in the same world
    skus = [f"SKU-{code}-{rng.randint(100, 999)}" for _, code in products]
    customers = [f"C-{rng.randint(100, 999)}" for _ in range(3)]
    order_ids = [f"ORD-{rng.randint(2000, 9999)}" for _ in range(3)]
    while len(set(order_ids)) < 3 or len(set(customers)) < 3 or len(set(skus)) < 4:
        return _case(family, index, rng)  # astronomically rare; keep ids unique

    name, _ = products[0]
    orders = {
        order_ids[0]: {
            "customer_id": customers[0],
            "sku": skus[0],
            "product_name": name,
            "shipping_status": "delivered",
        },
        order_ids[1]: {
            "customer_id": customers[1],
            "sku": skus[1],
            "product_name": products[1][0],
            "shipping_status": "delivered",
        },
        order_ids[2]: {
            "customer_id": customers[2],
            "sku": skus[2],
            "product_name": products[2][0],
            "shipping_status": "shipped",
        },
    }
    in_stock = family != "control_refund"
    inventory: dict[str, Any] = {
        sku: {
            "available": bool(rng.random() < 0.7),
            "quantity": rng.randint(0, 40),
            "as_of": "2026-10-01T09:00:00Z",
        }
        for sku in skus[1:]
    }
    inventory[skus[0]] = {
        "available": in_stock,
        "quantity": rng.randint(3, 40) if in_stock else 0,
        "as_of": "2026-10-01T09:00:00Z",
    }
    for rec in inventory.values():
        if not rec["available"]:
            rec["quantity"] = 0
    world: dict[str, Any] = {"orders": orders, "inventory": inventory, "policies": POLICIES}
    faults: dict[str, int] = {}
    model: dict[str, Any] = {"inventory_argument": "sku", "max_retries_on_timeout": 2}
    if family == "control_recovered_timeout":
        faults["lookup_inventory"] = 1
    elif family == "persistent_timeout":
        faults["lookup_inventory"] = 6
    elif family == "invalid_argument":
        model["inventory_argument"] = "product_name"
    elif family == "repeat_loop":
        model["order_id_case"] = "lower"
    elif family == "stale_retrieval":
        world["stale_inventory"] = {
            skus[0]: {"available": False, "quantity": 0, "as_of": "2026-08-12T09:00:00Z"}
        }
        faults["stale:lookup_inventory"] = 1
    elif family == "wrong_identity":
        model["resolution_order_id"] = order_ids[1]

    case_id = f"bm1-{family.replace('_', '-')}-{index + 1:02d}"
    fixture = Fixture.model_validate(
        {
            "fixture_id": case_id,
            "fixture_version": FIXTURE_VERSION,
            "description": description,
            "task": {
                "customer_id": customers[0],
                "order_id": order_ids[0],
                "request": "exchange",
                "message": f"My {name} {rng.choice(DEFECTS)}. Can I exchange it?",
            },
            "world": world,
            "faults": faults,
            "model": model,
            "budget": {"max_tool_calls": 8},
            "ground_truth": {
                "resolution": {
                    "order_id": order_ids[0],
                    "choice": "exchange" if in_stock else "refund",
                },
                "draft_customer_id": customers[0],
            },
            # How the scripted agent behaves, by construction of the family.
            "expected_baseline": _expected_baseline(family),
        }
    )
    return BenchmarkCase(
        case_id=case_id,
        benchmark_version=VERSION,
        family=family,
        split="heldout" if index >= count - HELDOUT_PER_FAMILY else "dev",
        expected_findings=expected,
        fixture=fixture,
    )


def _expected_baseline(family: str) -> dict[str, Any]:
    table: dict[str, tuple[bool, str, list[str]]] = {
        "control_exchange": (True, "completed", []),
        "control_refund": (True, "completed", []),
        "control_recovered_timeout": (True, "completed", ["TIMEOUT"]),
        "invalid_argument": (False, "budget_exhausted", ["SKU_REQUIRED"]),
        "repeat_loop": (False, "budget_exhausted", ["INVALID_ARGUMENT"]),
        "persistent_timeout": (False, "tool_failure", ["TIMEOUT"]),
        "stale_retrieval": (False, "completed", []),
        "wrong_identity": (False, "completed", []),
    }
    passed, termination, codes = table[family]
    return {"verifier_passed": passed, "termination": termination, "error_codes": codes}


def build_cases(seed: int = SEED) -> list[BenchmarkCase]:
    rng = random.Random(seed)
    return [_case(family, i, rng) for family, (n, _, _) in FAMILIES.items() for i in range(n)]


def to_jsonl(cases: list[BenchmarkCase]) -> str:
    return "".join(c.model_dump_json() + "\n" for c in cases)


def committed_path() -> Path:
    return Path(str(resources.files("agent_harness") / "benchmarks" / f"{VERSION}.jsonl"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.dataset")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="regenerate the committed file")
    group.add_argument("--check", action="store_true", help="fail if the committed file drifted")
    args = parser.parse_args(argv)
    text = to_jsonl(build_cases())
    path = committed_path()
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {len(text.splitlines())} cases to {path}")
        return 0
    if not path.is_file() or path.read_text() != text:
        print(f"{path} is missing or differs from the generator; run --write", file=sys.stderr)
        return 1
    print(f"{path}: {len(text.splitlines())} cases, matches the generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
