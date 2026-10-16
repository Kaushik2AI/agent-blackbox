# FlightPath

**The flight recorder for AI agents.** (Repository: `agent-blackbox`.)
A recorder, debugger and recovery studio for AI agents.
Inspect every step of an agent run, fork from a saved checkpoint, change one condition
safely, replay the rest in a sandbox, and compare the outcome against a ground-truth
verifier.

> **Project status: M7 of 11 — MVP complete.** A sandboxed LangGraph support agent with
> six fixtures and ground-truth verifiers; a Python SDK that records every run as
> OpenTelemetry-style spans/events plus pre-step checkpoints; an idempotent, redacting
> ingest API; five rule-based failure detectors that cite their evidence; a replay engine
> that resumes a checkpoint as a **new** execution in a network-blocked sandbox with exactly
> one validated intervention; and a dashboard with an execution inspector, Replay Studio
> and original-vs-fork comparison. Benchmarking (M8), real-model runs on SCC (M9) and
> hardening/auth (M10) are not built yet.

## The interface

See [docs/design/flightpath-redesign.md](docs/design/flightpath-redesign.md): a horizontal
flight path per run, root cause kept apart from its symptoms, Simple and Technical views,
and a guided Replay Studio.

## Why this exists

When an agent fails, ordinary logs show an exception or a bad final answer, but not the
sequence that led there: which tool was proposed, with what arguments, what came back, how
many retries, and where recovery became impossible. Tracing alone is not new. Agent
BlackBox combines an open instrumentation contract, a **branchable** agent harness,
**controlled single-change interventions**, and **measured** recovery against objective
verifiers.

## Roadmap

| Milestone | What it delivers | Status |
|---|---|---|
| M0 | Specification: architecture, replay contract, data model, threat model, acceptance matrix | ✅ |
| M1 | Postgres + Redis + RQ, FastAPI `/healthz` `/readyz`, Alembic schema, Next.js status page, CI, SCC/no-Docker setup | ✅ |
| M2 | Sandboxed customer-support agent (LangGraph, stub model) with 5 fixtures and verifiers | ✅ |
| M3 | Python SDK (OTel-compatible) + idempotent, redacting event ingestion | ✅ |
| M4 | Execution inspector: runs list, React Flow graph, timeline, event inspector | ✅ |
| M5 | Rule-based failure detectors with evidence links and measured precision/recall | ✅ |
| M6 | Checkpoint replay engine: isolated forks, one validated intervention | ✅ |
| M7 | Replay Studio + original-vs-fork comparison (MVP complete) | ✅ |
| M8 | Reproducible 30–60 case benchmark with baselines and CIs | ⏳ next |
| M9 | BU SCC GPU batch evaluation (qsub) with an open-weight model | ⏳ |
| M10 | Hardening, auth, docs, demo | ⏳ |

## Quickstart

### On BU SCC (OnDemand VS Code / Desktop session — only Python + pip, no Docker/conda)

```bash
git clone https://github.com/<you>/agent-blackbox.git && cd agent-blackbox
make setup-scc     # Python venv + pip-installed Postgres/Redis/Node, random-password .env, migrations
make dev           # API + worker + web; prints the URL to open
```

Optional, for the **Live AI** agent on the home page (a real Qwen model on your SCC node):

```bash
make qwen-setup    # once: PyTorch + transformers + a Qwen2.5 model, then a one-question self-test
make dev           # now also starts the Qwen server ("Live AI: Qwen loading..." for 1-2 min)
```

It picks the model size from the node: Qwen2.5-3B on a GPU with 12 GB+, 1.5B on a smaller
GPU or a CPU node with 10 GB+ free RAM, otherwise 0.5B. Weights and pip downloads stay
inside the repo (`.cache/`), not your home quota. Force one with
`QWEN_MODEL=Qwen/Qwen2.5-3B-Instruct make qwen-setup`. On a CPU node expect roughly
10-20 s per AI step.

### On a laptop with Docker

```bash
cp .env.example .env   # set passwords
python3.11 -m venv .venv && source .venv/bin/activate
make install && make compose-up && make dev
```

Then open the printed URL. You should see **All systems ready** with live Postgres and
Redis latencies. Stop Redis (`make services-down` or `docker compose stop redis`) and the
page turns amber with the real error within 5 seconds.

Full instructions, cleanup and troubleshooting: [`docs/developer-runbook.md`](docs/developer-runbook.md).

## The demo agent

```bash
make demo        # all 5 fixtures x10, each compared with its expected baseline
make demo-fail   # the flagship failure: product_name passed instead of sku
```

```
fixture                        verifier  termination       errors           baseline
exchange_success               pass      completed         -                match x10
invalid_inventory_argument     fail      budget_exhausted  SKU_REQUIRED     match x10
persistent_inventory_timeout   fail      tool_failure      TIMEOUT          match x10
refund_out_of_stock            pass      completed         -                match x10
transient_inventory_timeout    pass      completed         TIMEOUT          match x10
```

(Output of `make demo` with the deterministic stub model; details in
[`packages/agent_harness/README.md`](packages/agent_harness/README.md).)

## Recording runs and inspecting them

```bash
make dev          # terminal 1: API + worker + web
make seed-demo    # terminal 2: run all 5 fixtures through the SDK -> ingest API -> Postgres
```

Open the web UI → **Runs** → `invalid_inventory_argument` → click the red
`execute_tool lookup_inventory` node: the inspector shows `SKU_REQUIRED`, the
`validation_error` type and the offending `product_name` argument. Every number and node
on screen comes from rows written by the ingest API.

## The flagship demo: fail → diagnose → fork → verified recovery

1. **Runs** → `invalid_inventory_argument`. Findings at the top (all *verified*, each citing
   event IDs): `tool_schema_mismatch`, `retry_loop`, `budget_exhausted`.
2. **⑂ Replay Studio** → checkpoint *before call #1 · lookup_inventory* is pre-selected →
   replace the arguments `{"product_name": "red backpack"}` with `{"sku": "SKU-RED-004"}` →
   **Run replay** → confirm.
3. The RQ worker restores the checkpoint into a **new** execution (parent = original),
   blocks all network access, applies the one change and re-runs the remaining steps for
   real. The ground-truth verifier passes.
4. **Compare original vs fork**: the exact intervention record, step-by-step alignment
   (first divergence at call #1), the final sandbox diff (a draft and an `exchange`
   resolution now exist), both graphs, and an explicit causal-claim caveat. The original
   run's rows are byte-for-byte unchanged (tested).

The same flow runs as an automated browser test (`e2e/replay.spec.ts`).

## Failure detectors (M5)

```
$ make eval-detectors
detectors v1.0, labels v1.0, 6 fixtures (metadata-only traces)

category                    TP  FP  FN  TN  precision  recall    F1
tool_schema_mismatch         1   0   0   5       1.00    1.00  1.00
retry_loop                   1   0   0   5       1.00    1.00  1.00
tool_timeout                 1   0   0   5       1.00    1.00  1.00
budget_exhausted             1   0   0   5       1.00    1.00  1.00
state_identity_mismatch      1   0   0   5       1.00    1.00  1.00

micro precision 1.00, micro recall 1.00
Caveat: 6 hand-labelled fixtures written by the same team as the detectors; no held-out set yet (M8). Treat as a regression check, not a generalisation claim.
```

Those numbers are recomputed from scratch on every run (real agent → SDK in metadata-only
mode → detectors → comparison with `packages/analysis_engine/analysis_engine/labels/v1.json`).
Six fixtures is a regression check, not evidence of generalisation; M8 adds a larger,
held-out benchmark.

## Checks

```bash
make check            # ruff + mypy --strict + tsc, API tests, web tests, production build
make test-web-smoke   # with `make dev` running: browser path -> Next.js -> FastAPI -> deps
```

Test inventory (M7): 5 Playwright browser tests (adds the full flagship replay flow and the
disabled-replay case), 20 replay/findings API tests against real Postgres/Redis (fork
immutability by row fingerprint, checkpoint hash tampering, six kinds of rejected
interventions, metadata-only runs refused, idempotency keys, crash recovery of a half-written
fork, blocked network access, independent forks, a real RQ worker), 11 harness replay
tests, 9 detector tests, 3 new SDK tests. Earlier milestones: 3 Playwright browser tests (find and open the real failing run with
the keyboard, click the failing span, see the error; overview matches the API; live
readiness), 14 SDK tests (span tree, OTel-style IDs, ordering, metadata-only default,
opt-in content, client-side redaction, retrying exporter, JSONL export), 46 API tests
including 22 new ingest/read tests against real Postgres (real agent runs persisted and
checked with SQL, duplicate batches, out-of-order and missing-parent batches, late span
ends, terminal-status protection, unknown schema_version, 413 limits, payload truncation,
server-side redaction of a non-redacting client, provenance), 7 web unit tests, and
31 demo-agent tests (tool contracts and error codes, fault injection,
every fixture vs. baseline, failure-reason checks, 10x determinism, per-run isolation,
no-network guard, contract drift), 10 API tests (health, readiness failure reporting
without secret leakage, migrations up/down, foreign keys, fork self-parent check, real RQ
job round trip, config parsing) and 5 web tests (4 unit, 1 live smoke).

## Architecture

```
Demo agent ──► BlackBox SDK ──POST /api/v1/events:batch──┐
                                                          ▼
Browser ──► Next.js (only exposed port) ──/backend/*──► FastAPI ──► PostgreSQL
                                                          └──────► Redis ◄── RQ worker
```

Design documents:

- [Architecture, lifecycle, UX spec, task graph](docs/architecture.md)
- [Replay contract: visualization vs checkpoint replay vs counterfactual](docs/replay-contract.md)
- [Data model and event contract v1.0](docs/data-model.md)
- [Threat model](docs/threat-model.md)
- [User stories → acceptance tests, MVP boundary](docs/acceptance-matrix.md)
- [ADR-001: stack, queue, SCC environment, license](docs/decisions/ADR-001-core-stack.md)
- [Original blueprint](docs/blueprint.md)

## Safety principles (binding on all later milestones)

- Metadata-only capture by default; secrets redacted before anything is stored.
- Replays create **new** executions; the original run is never modified.
- Replays use only simulated, allowlisted tools; no real email, payment or network calls.
- Success is decided by ground-truth verifiers, never by the model's own claim.
- Rule-based findings are evidence; LLM explanations are labelled *hypothesis*.
- Every number in this README will come from a runnable script.

## License

[Apache-2.0](LICENSE) — rationale in ADR-001.
