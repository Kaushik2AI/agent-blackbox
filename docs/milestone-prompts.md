# Agent BlackBox - Project 1 Only
## Copy/Paste Coding Prompts for Codex, Claude Code, or another coding agent

**Workflow:** Open an empty `agent-blackbox` repo in your coding agent. Provide the engineering blueprint document as context. Send the MASTER prompt once, then prompts M0-M10 **one at a time**. Never ask the coding agent to generate the entire unverified system in a single pass. Review every diff and test report before moving forward.

---

## MASTER - Permanent engineering instructions (send first)

```text
You are my principal AI infrastructure engineer, technical architect, security reviewer, and full-stack coding partner. We are building exactly ONE project: Agent BlackBox, a production-style AI Agent Flight Recorder, Debugger, and Recovery Studio. No unrelated product or feature work.

The engineering blueprint attached to this repository is the source of truth. Do not invent implemented functionality, benchmarks, command outputs, or screenshots. Before editing, inspect the current repository and summarize what exists and what is missing. Do not overwrite working code without explanation.

Preferred stack: Python 3.11+, FastAPI/Pydantic v2, PostgreSQL/SQLAlchemy 2/Alembic, Redis plus ONE job queue, Next.js/React/TypeScript/Tailwind/shadcn/ui/React Flow, OpenTelemetry-compatible tracing, LangGraph checkpointer for the demo harness, pytest, Playwright, Docker Compose, GitHub Actions. Pin dependencies that are known to be compatible and document why. When an API is uncertain, verify from installed packages or official documentation, not memory.

Architecture requirements:
1. Clean domain/service/repository/API boundaries and explicit typed contracts.
2. Keep all secrets in environment variables; commit only .env.example.
3. Prefer complete vertical slices over massive empty scaffolding. No fake endpoints, nonfunctional buttons, or static demo data presented as real telemetry.
4. Default to metadata-only capture; redact secrets and sensitive payloads before persistence. Opt-in full content only.
5. Keep trace visualization, checkpoint replay, and controlled counterfactual replay conceptually and technically distinct.
6. The original execution must remain immutable; replay creates a new execution and a lineage record.
7. Replay v1 MUST use allowlisted sandbox/fixture tools. Never trigger real email, payment, deletion, or external side effects.
8. A rule-based detector with event citations produces verified findings; LLM explanations are labeled hypotheses.
9. Ground-truth task verifiers determine success/failure; never trust self-reported model success.
10. No GPU is required for CI or the first successful end-to-end demo; support SCC GPU experiments later.

Process for every milestone:
- Start with a short implementation plan and files you will touch.
- Implement the exact milestone and minimal required supporting components only.
- Add unit/integration/e2e tests appropriate to that milestone.
- Run available checks (formatter, linter, type checker, migrations, tests, frontend build), fixing failures.
- Return: changed-file summary, exact commands run, results, unresolved issues, and next milestone readiness.
- If a command cannot run in this environment, explicitly say so. Do not claim passing tests without executing them.
- Keep README and architecture decisions synchronized with actual functionality.
- Do not proceed to another milestone without my approval.

Before coding, confirm you understand the project scope, list the milestones, and inspect the repository.
```

---

## M0 - Write a defensible specification and initial repo

```text
Implement milestone M0 for Agent BlackBox only. Read the attached project blueprint first. Create a focused, high-quality README draft, docs/architecture.md, docs/replay-contract.md, docs/threat-model.md, docs/data-model.md, docs/decisions/ADR-001-core-stack.md, and a minimal repo root with .gitignore, .env.example, Makefile and LICENSE (choose and justify a suitable open source license). Produce concrete data contracts, an execution lifecycle state diagram, a screen-by-screen UX specification, and a task graph of future milestones.

Specifically document three replay levels: visualization, checkpoint replay, and controlled counterfactual, including non-determinism and side-effect isolation. Provide a user-story to acceptance-test matrix and define exact MVP boundaries. Do not generate fake services just to make the repo appear large. Run any checks available and give me a structured review checklist before M1.
```

### Gate M0

Docs align with scope; replay privacy and limitations explicit; next milestones have testable exits.

---

## M1 - Dev infrastructure and first real full-stack vertical slice

```text
Implement M1 only. Initialize a Next.js TypeScript frontend and FastAPI backend, PostgreSQL, Redis plus one background-job library, Alembic migrations, typed configuration, health/readiness endpoints, Docker Compose, CI, and stable local dev commands. Create a minimal UI that requests the FastAPI health endpoint and displays actual API connectivity, not hardcoded success.

Add project/agent/execution placeholder domain schema through real Alembic migration with foreign keys; do not implement fake replay behavior. Add backend DB integration test and frontend API smoke test. Document startup from a clean checkout and correct cleanup. Gate: a fresh setup starts, health checks work, migrations apply and tests pass.
```

### Gate M1

`docker compose up` and documented setup work; backend and frontend communicate; migrations and basic tests pass.

---

## M2 - Build the deterministic sandbox agent

```text
Implement M2 only. Build a demo customer-support inventory agent using LangGraph with typed state and a deterministic local/mock-model mode. Simulated tools: lookup_order, lookup_inventory, get_policy, draft_response and submit_resolution. No tool may send real emails, execute purchases or call uncontrolled external endpoints.

Create at least 3 versioned fixture tasks: one successful, one invalid inventory argument leading to failure, and one transient timeout/retry scenario. Build deterministic ground-truth verifiers and isolated fixture state per execution. Record tool contracts with JSON Schema/Pydantic and explicit error codes. Provide CLI `python -m agent_harness.run_demo --fixture FIXTURE_ID` or documented equivalent. Add tests showing the successful fixture passes and failing fixtures fail for the intended reason. Do not build the trace UI yet.
```

### Gate M2

3 fixtures produce expected results and repeat reliably in local stub mode.

---

## M3 - Real instrumentation SDK and ingestion service

```text
Implement M3 only. Add a small Python BlackBox SDK that captures OpenTelemetry-compatible spans/events for agent invocations, LLM calls, tool execution, state transitions, and errors. Generate correct trace IDs/span IDs, sequence numbers and timestamps. Create a versioned batch ingestion FastAPI endpoint. Persist projects, agent versions, executions, spans, events and artifact references via SQLAlchemy/Alembic.

Default content capture to OFF; add configurable redaction and payload size limits. Ingest must be idempotent on stable IDs and resilient to retries/out-of-order events. Preserve parent span relationships. Instrument the M2 agent end-to-end so runs create real DB records. Add tests for duplicate batches, missing parent event tolerance, invalid schema_version, secret redaction, and provenance. Do not write a frontend that assumes spans exist; prove them with API tests and SQL queries.
```

### Gate M3

Agent run visibly persists correct, deduplicated real trace records and redaction tests pass.

---

## M4 - A beautiful execution inspector backed by real events

```text
Implement M4 only. Build a polished responsive dark-themed Next.js dashboard for executions. Pages: Overview, Runs Explorer, and Execution Inspector. The inspector must show a clickable directed step graph (React Flow), ordered timeline, error detail, parent-child spans, token/latency metadata where available, and a safe redacted payload inspector. All data must come from the real FastAPI backend and M3 records.

Add run listing filters for status, version and time; handle loading, empty and failed network states, pagination, and keyboard navigation. Include a Seed Demo button ONLY if it calls a real development-only backend action; otherwise use a documented CLI command. Add browser test for finding and opening the real invalid-inventory-argument failure. Avoid invented screenshots/metrics.
```

### Gate M4

Open a real failed run in the UI and click the exact failing tool span; no hardcoded run data.

---

## M5 - Evidence-backed failure diagnosis

```text
Implement M5 only. Add a deterministic failure-analysis engine producing versioned findings from spans and events. Implement at least 5 detectors: invalid tool schema, repeated failed tool call loop, tool timeout, budget exhaustion, and inconsistent order/SKU identity. Each finding must carry category, severity, evidence_event_ids, detector version and explanation. Expose an authenticated/policy-checked findings endpoint and show linked findings beside the relevant graph nodes in the UI.

Create labeled evaluation fixtures and unit tests measuring detector precision and recall. Optional LLM-generated narrative can be introduced only behind an explicit feature flag and MUST be clearly labeled 'Hypothesis' while rule-based findings are evidence-backed. Do not claim the detector proves causal mechanisms. Show actual precision/recall computed from tests, not hand-written numbers.
```

### Gate M5

Findings show links to raw events; confusion matrix reproducible from labeled fixtures.

---

## M6 - Safe checkpoint replay engine (core differentiator)

```text
Implement M6 only. Build an actual checkpoint-backed replay service for the M2 LangGraph sandbox agent. Persist PRE-STEP state snapshot references, agent/code/fixture versions and hashes. Implement replay eligibility checks, fork_execution_id and parent_execution_id lineage, immutable original runs, and a Redis-backed asynchronous replay worker.

Support exactly two validated interventions initially: replace_tool_result and replace_tool_argument (field must pass tool schema validation). Interventions can target ONLY calls after a valid selected checkpoint. Replay MUST run within the simulated allowlisted tool environment; no real network or external effects. Support replay class `deterministic` for mocked calls and `controlled_stochastic` for real model calls, with explicit metadata. Capture the fork's new trace from scratch and verify task success from ground-truth final sandbox state.

Provide tests for fork immutability, checkpoint hash mismatch, invalid intervention, worker retry/idempotency, forbidden external network access, independent fork state, and known fixture failure->successful fork. Never call an operation 'replay' if it merely edits stored JSON/graphs. Return a documented, runnable CLI/API replay example.
```

### Gate M6

Real resumed execution completes on a fork; the original run is byte-for-byte unchanged at domain level; tests prove side effects remain sandboxed.

---

## M7 - Replay Studio and original-vs-fork comparison

```text
Implement M7 only. Add a Replay Studio in the UI: checkpoint selector showing only eligible points, intervention type, target tool call and validated argument/result editor, sandbox assurance, submit confirmation, asynchronous progress status, and robust error handling. Add a side-by-side comparison screen visualizing source and fork trace graphs, exact intervention record, JSON state diff, failure findings, task verifier outcome, latency, calls, tokens and estimated cost (when available).

Use real replay API endpoints with a background worker. Label mock/deterministic versus controlled-stochastic replay clearly. Add Playwright E2E test that seeds the intentional inventory failure, selects an eligible checkpoint, fixes the invalid SKU argument, launches an isolated replay and sees a verifier-confirmed successful fork. Test that unavailable checkpoints disable replay controls rather than allowing a fake click.
```

### Gate M7

Flagship browser demo works end-to-end with real backend and replay worker.

---

## M8 - Reproducible benchmarking and analysis

```text
Implement M8 only. Build a versioned 30-60 case benchmark from synthetic customer-support fixtures across success controls, invalid arguments, stale retrieval, timeout, repeat loops and incorrect identity. Preserve held-out cases. Write CLI and API to run baseline agent, no-intervention replay, allowed repair intervention and random allowed intervention baselines. Use objective task verifiers, record failure detectors and fork lineage.

Produce JSONL/CSV artifacts with outcome, case ID, seed/config, model/agent/fixture version, elapsed time, token count and cost estimates when supported. Aggregate success rate, recovery rate on failed runs, replay validity, false benefit, detector precision/recall and latency, with correct denominators and confidence intervals where meaningful. Add regression tests for metric math and reproducibility; dashboard charts must display computed outputs. Do not claim the intervention beats baselines unless results demonstrate it.
```

### Gate M8

A single documented command reconstructs benchmark artifacts and charts from scratch.

---

## M9 - BU SCC GPU inference/evaluation integration

```text
Implement M9 only. The deployment environment is Boston University's Shared Computing Cluster, which uses qsub/qrsh Grid Engine-style GPU allocations. DO NOT use Slurm-specific sbatch/srun. Inspect https://www.bu.edu/tech/support/research/software-and-programming/gpu-computing/ and related BU SCC guidance or the repo's cached documentation.

Add a `packages/evaluation` model adapter supporting both deterministic CPU tests and a configurable open-weight Qwen-style instruct model on a GPU. Provide project-local model/Hugging Face cache configuration, explicit environment checks, a qsub batch script requesting one GPU, example qsub submission instructions, and a resumable JSONL manifest with execution IDs, agent SHA, model revision, fixture version, decoding settings, random seed, torch/CUDA versions and SCC job ID.

Prefer a direct transformers batch adapter unless vLLM server usage within an approved GPU allocation is demonstrably feasible. Do not expose an insecure inference server or public dashboard from a temporary compute node. Provide an importer that brings validated JSONL runs and evaluation results into the main database for UI inspection. CI must still work with no GPU. If you cannot access SCC from your environment, generate and locally lint scripts without pretending to execute a GPU job.
```

### Gate M9

SCC eval job can be submitted on an allocated GPU and output imported reproducibly; otherwise clearly document what remains unverified on SCC.

---

## M10 - Security hardening and portfolio-grade release

```text
Implement M10 only. Audit the existing repository as if preparing an open-source v1 release. Complete project-scoped authorization, environment and secrets hygiene, input validation, ingestion rate/size controls, redaction, sandbox isolation tests, replay idempotency, database migration reliability, API docs/OpenAPI, typed builds, frontend accessibility, and CI checks.

Build polished README with truthful features, real screenshots, system architecture diagram, deployment/topology notes, command-by-command setup, copy-paste SDK example, evaluation methodology, numerical results sourced from output files, limitations, and a concise demo script for a 90-second screen recording. Add a GitHub Actions workflow that runs Python tests, lint/typecheck, frontend build and browser smoke tests where infrastructure allows. Do not add green shields, fake stars, fake benchmark numbers or claims of production readiness unsupported by test evidence. Show remaining limitations honestly.
```

### Gate M10

Fresh-clone quickstart works; CI passes; security and sandbox regression tests pass; demo script matches the live application.

---

## Rescue prompt - when the coding LLM produces broken code

```text
Stop new feature work. Act as a senior reliability engineer. Inspect the repository and reproduce the reported failure with the smallest possible command. Identify the root cause from actual stack traces and tests, not guesses. Make only the targeted fix, add a regression test, run the failing test then the relevant broader suite, and summarize root cause, files changed, and exact test output. Do not refactor unrelated modules or advance milestones. If access/dependencies are missing, identify precisely what cannot be verified.
```

## Code review prompt - use after every milestone

```text
Review this milestone as a skeptical staff engineer and security reviewer. Compare implementation against the milestone's acceptance gate and architecture contract. Search for stubbed success paths, fake data presented as real, unhandled error states, schema mismatches, unsafe replay/side effects, missing authorization, swallowed exceptions, fragile async worker behavior, test gaps, and documentation that overclaims functionality. Produce a prioritized list of issues with file locations and exact proposed fixes. Then fix critical/high issues and rerun relevant tests. Do not implement future milestones.
```

## Demo verification prompt - use before publishing GitHub

```text
Produce a fully reproducible evidence bundle for Agent BlackBox: clean setup commands, seeded known-failure run ID, original trace snapshot, checkpoint selection, single replay intervention, fork execution ID, ground-truth success verifier output, original-vs-fork comparison JSON, benchmark CSV with denominators, CI test report, and README screenshots. If any claimed feature cannot be demonstrated using running code, remove or qualify the claim. Provide a 90-second demo narration and list exactly which outputs are measured vs illustrative.
```

---

## HOW TO WORK (practical)

1. Create `agent-blackbox` and open it in your coding agent.
2. Add `Agent_BlackBox_Project1_Complete_Blueprint.md` to `docs/` and refer to it as source of truth.
3. Paste MASTER once.
4. Paste M0. Examine its diff/tests; give approval only when M0 gate passes.
5. Repeat through M10, one prompt at a time, committing after each gate.
6. Do not spend SCC GPU hours until local stub-mode tracing and checkpoint replay work.
7. Before publishing, run Code Review and Demo Verification prompts.

**Stop condition:** The repository is complete only after a viewer can watch one real failure, fork and replay it safely, see verified success, and reproduce the evaluation results.
