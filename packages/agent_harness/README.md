# agent_harness — the sandboxed demo agent (M2)

A customer-support agent built as a LangGraph state machine. It handles one kind of task
("my order arrived broken, can I exchange it?") using five **simulated** tools. Nothing it
does can leave the process: drafts and resolutions are written to a per-run sandbox.

```bash
python -m agent_harness.run_demo --list
python -m agent_harness.run_demo --fixture invalid_inventory_argument
python -m agent_harness.run_demo --fixture exchange_success --json
python -m agent_harness.run_demo --all --repeat 10      # every fixture vs. its baseline
```

## Pieces

| File | What it is |
|---|---|
| `tools.py` | Tool contracts (Pydantic in/out, `extra="forbid"`), explicit `ErrorCode`s, the allowlist `TOOLS`. JSON Schemas are committed in `packages/contracts/tools.v1.json`. |
| `sandbox.py` | Per-execution deep copy of the fixture world + side-effect store + fault injection. |
| `model.py` | `Model` protocol and `StubModel`, a **scripted** planner standing in for an LLM so runs are deterministic on CPU. A real model adapter (M9) implements the same protocol. |
| `graph.py` | LangGraph `StateGraph`: `model → tool → model … → END`, tool-call budget, JSON-serialisable state (checkpointable in M6), event hooks for the M3 SDK. |
| `verifier.py` | Ground-truth verifier: checks the final sandbox against the fixture's `ground_truth`. Never trusts the model. |
| `fixtures/*.json` | Versioned tasks (world, faults, model script, budget, ground truth, expected baseline). |
| `run_demo.py` | CLI. |
| `interventions.py` (M6) | `ReplaceToolArguments` / `ReplaceToolResult`, validated against the tool contracts. |
| `runner.run_from_checkpoint` (M6) | Resume a pre-step checkpoint in a new execution with an independent sandbox copy; re-executes the suffix for real. |

## Fixtures (v1.0.0)

| Fixture | Scenario | Verifier | Termination | Tool errors |
|---|---|---|---|---|
| `exchange_success` | Happy path, item in stock → exchange | pass | completed | – |
| `refund_out_of_stock` | Control: out of stock → refund | pass | completed | – |
| `invalid_inventory_argument` | **Flagship failure:** `product_name` passed instead of `sku`, same bad call repeated until the 8-call budget is gone | fail | budget_exhausted | SKU_REQUIRED |
| `transient_inventory_timeout` | One injected timeout, retry recovers | pass | completed | TIMEOUT |
| `persistent_inventory_timeout` | Timeouts outlast 2 retries, agent gives up | fail | tool_failure | TIMEOUT |
| `wrong_order_identity` | Identity bug: looks up ORD-1001, resolves ORD-1002 | fail | completed | – |

These rows are what `--all` checks on every run (and CI checks 10× per fixture).

## Honest notes

- The stub model is a deterministic script, not an LLM. Its failure on
  `invalid_inventory_argument` is configured by the fixture (`model.inventory_argument`)
  so the failure is reproducible; that is the point of a debugging fixture.
- `expected_baseline` describes the stub's known behaviour and is used only by tests.
  `ground_truth` is what a correct agent should achieve and is what the verifier checks.

## Benchmark cases

`agent_harness/benchmarks/benchmark_v1.jsonl` holds 52 generated cases (see
`packages/evaluation`). They load by id like any fixture (`load_fixture("bm1-...")`), so
benchmark runs can be replayed in the app. Two knobs exist only for them: the model script's
`order_id_case: "lower"` (a malformed order id, retried in a loop) and the
`stale:lookup_inventory` fault (an outdated cached stock record is served once).
