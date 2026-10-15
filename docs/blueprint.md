---
title: Agent BlackBox | Project 1 Engineering Blueprint
subtitle: A production-style AI Agent Flight Recorder, Debugger, and Recovery Studio
version: 1.0
updated: October 14, 2026
scope: Agent BlackBox only
---

# AGENT BLACKBOX

## Project 1: Complete Engineering Blueprint

**Mission:** Build a serious, demonstrable AI infrastructure product that instruments agent executions, explains failures with evidence, creates isolated replay branches from checkpoints, and quantifies which interventions recover failed tasks.

**Portfolio positioning:** Full-stack AI Engineer | LLM Infrastructure | Agent Observability | Evaluation Engineering | Systems Design

**Single-project scope.** This document covers only Agent BlackBox. It intentionally does not specify any second product.

---

## 1. Executive product definition

### The problem

When an agent fails, normal application logs may show an exception or final bad answer but not the causal sequence: prompt and model configuration, the tool proposed, the arguments passed, intermediate state, API/tool response, repeated attempts, and the exact decision after which recovery became impossible. Existing observability products provide tracing; this portfolio project differentiates itself by combining a **useful open instrumentation contract**, a **branchable agent execution harness**, **controlled interventions**, and **measured recovery outcomes**, rather than claiming the tracing idea itself is new.

### The product in one sentence

**Agent BlackBox is a web-based debugging lab where an AI engineer can inspect every step of an agent run, fork from a saved checkpoint, change one condition safely, replay the remainder, and compare results.**

### Primary user stories

1. As an agent developer, I can register an instrumented application and see live completed and failed runs.
2. As a developer, I can inspect a DAG/timeline of model, tool, retrieval, and state-transition events for any run.
3. As a developer, I can see evidence-backed failure flags (invalid tool args, timeouts, loops, missing evidence, unexpected state transitions).
4. As a developer, I can save/fetch pre-step checkpoints for a supported demo agent and replay from one of them.
5. As a developer, I can choose a **single explicit intervention**: substitute a tool response, change an argument, change a prompt fragment, or substitute a retrieval result.
6. As a developer, I can compare original and replay runs on task success, failure class, call count, token count, elapsed time, and model-estimated cost if pricing is configured.
7. As a developer, I can run a fixed benchmark and export evidence (JSON/CSV) that supports the README claims.

### Non-goals for v1

- Claiming universal deterministic replay for all arbitrary agent frameworks.
- Automatically fixing every agent failure.
- Running real payment, email, deletion, or other external side-effecting calls during replay.
- Multi-tenant SaaS billing, Kubernetes, complete SOC2 compliance, or unsupervised production recovery.
- Relying on the LLM to decide whether a run truly succeeded; ground truth belongs in the test environment.

### Three capability levels (must remain separate in code and UI)

| Level | Name | What it really does | Evidence |
|---|---|---|---|
| 1 | Trace visualization | Displays the recorded run | Ingested spans and event details |
| 2 | Checkpoint replay | Re-runs the agent after a saved state with isolated tools | New execution linked to parent and checkpoint |
| 3 | Controlled counterfactual | Re-runs after exactly one declared intervention, with frozen inputs whenever possible | Replayed outcome plus intervention record and environment fingerprint |

**Important:** Checkpoint replay and counterfactual replay may be nondeterministic because LLM sampling, external services, and tool data can vary. Never label all such runs deterministic. Use `deterministic`, `controlled_stochastic`, or `best_effort` replay classification.

---

## 2. Product experience and demo scenario

### Flagship demo: Inventory Customer Support Agent

Build a realistic *sandboxed* customer support agent that answers order questions using simulated tools:

- `lookup_order(order_id)` returns an order, SKU, shipping status.
- `lookup_inventory(sku)` returns availability and an inventory timestamp.
- `get_policy(policy_key)` retrieves refund/exchange rules.
- `draft_response(customer_id, text)` stores a draft in an isolated sandbox. It **does not send messages**.
- `submit_resolution(order_id, choice)` records a sandbox resolution event.

A run deliberately fails because it passes `product_name` rather than the required `sku` to `lookup_inventory`. The agent retries badly and exceeds its tool budget.

**User-visible path:** Runs list -> Failed run -> Node graph and event timeline -> Inspect invalid arguments -> Select checkpoint before lookup -> Replace lookup argument with an allowed SKU -> Replay in sandbox -> Side-by-side diff -> Success verification.

### Additional failure fixtures

- **Transient tool outage:** simulate a timeout followed by a retry policy that either recovers or loops.
- **Stale retrieval:** policy retriever returns an outdated snippet; override one retrieval result and measure if the final answer changes.
- **State corruption:** deliberately introduce a wrong order ID into a known state snapshot; replay from the clean checkpoint.
- **Model variability:** run identical tests across multiple seeds and record outcome variance rather than asserting reproducibility from `temperature=0` alone.

### Screens

1. **Overview:** total runs, success rate, common failure types, median latency, estimated token spend; filters by agent version, date, outcome, model.
2. **Runs explorer:** searchable table with status, task, run ID, version, duration, cost estimate, failure tags.
3. **Execution inspector:** node graph, left timeline, right event inspector, raw arguments (redacted), stack trace, timestamps, parent-child relationships.
4. **Replay studio:** select eligible checkpoint and one intervention, see isolation mode and explicit confirmation, run background replay job, show progress.
5. **Comparison view:** synchronized original/fork graphs, JSON state/argument diff, outcomes and metrics.
6. **Evaluation lab:** benchmark selection, run list, baseline-vs-intervention results, error bars/intervals, export buttons.
7. **Agent integration page:** copyable SDK setup, demo instrumentation, API key display only at creation.

### UI requirements that distinguish this from an academic project

- Working live states, not mock stats hardcoded in components.
- Keyboard-accessible, responsive layout; beautiful dark UI allowed but clarity comes first.
- Zoomable graph with stable event IDs and clickable edges.
- Loading/error/empty states and failure traces with human-readable explanations.
- Safe replay button disabled when the selected run lacks a checkpoint or isolation support.
- Raw event payload visible by default only if explicit safe-capture settings allow it.

---

## 3. Concrete technology choices

| Area | Recommended choice | Why |
|---|---|---|
| UI | Next.js + React + TypeScript + Tailwind + shadcn/ui + React Flow | Modern product UI, reliable developer experience and execution DAG |
| Charts | Recharts | KPI/evaluation views |
| API | FastAPI + Pydantic v2 | Typed service contracts, Python integration with agents |
| Database | PostgreSQL + SQLAlchemy 2 + Alembic | Durable runs, events, relations, migrations |
| Background tasks | Redis + RQ or Dramatiq (choose one) | Replay/evaluation jobs must not block HTTP |
| Agent framework | LangGraph + persistent checkpointer **for demo harness only** | Explicit state, saved checkpoints and branching |
| Instrumentation | Custom Python SDK wrapping OpenTelemetry | Vendor-neutral spans with a few application-specific fields |
| Model adapter | OpenAI-compatible interface + local mock model | CPU-first functional tests; SCC later for actual open-weight models |
| Object storage | Local filesystem in dev, S3-compatible object storage optional | Larger redacted artifacts and benchmark outputs |
| Testing | pytest, pytest-asyncio, httpx, Playwright, Vitest | Backend, full-stack and UI coverage |
| Packaging | uv or pip + lock file, Docker Compose | Reproducibility |
| CI | GitHub Actions | Unit tests, lint, typed builds, no GPU needed |

**Use pinned releases after checking compatibility.** Do not ask a coding LLM to invent library APIs or install unbounded `latest` dependencies.

### Standards

Map agent/model/tool spans onto OpenTelemetry's published GenAI semantic conventions wherever feasible. Their GenAI conventions are still evolving; version or document your adapter, do not blindly hard-code one field schema forever. Content capture is opt-in.

---

## 4. Architecture and data flow

```text
INSTRUMENTED DEMO AGENT                    BLACKBOX PLATFORM
----------------------------------          -----------------------------------
LangGraph state machine                     Web UI (Next.js / React Flow)
    |                                                |
BlackBox SDK / OpenTelemetry                FastAPI REST + WebSocket/SSE
    |                                                |
OTLP / JSON event adapter  ---------------->  Ingest + Validate + Redact
                                                     |
                                              Postgres run/span/event store
                                                     |
                               ----------------------+-----------------
                               |                                        |
                        Analyzer service                         Replay service
                      (rule-based + optional LLM)                   |
                               |                              Redis job queue
                         Failure reports                              |
                                                                    Worker
                                                                      |
                                                   restore checkpoint + intervention
                                                                      |
                                                   sandboxed agent/tool harness
                                                                      |
                                                   new trace, verifier and diff
```

### Request flow

1. A demo agent starts `execution_id=UUID`, `agent_version` and immutable `environment_fingerprint`.
2. SDK instruments model/tool/state operations using trace IDs and span IDs; ingestion is asynchronous and resilient to transient network issues.
3. API validates project ownership, input size, schema, redacts secrets, and stores records idempotently.
4. UI loads run graph and timeline through paginated/filterable APIs.
5. Analyzer attaches evidence-backed failure flags; an optional LLM writes a *hypothesis* but cannot overwrite verified facts.
6. Replay request validates the checkpoint's availability, intervention schema, and sandbox policy, then enqueues job.
7. Worker clones the selected snapshot into a new run, freezes fixture/tool data where supported, applies exactly the requested change and re-executes the suffix.
8. Verifier checks expected outcome and persisted state. API stores parent/child lineage and a structured comparison.
9. UI shows original and forked paths with clearly labeled uncertainty and replay mode.

### Boundary rules

- Next.js never connects directly to PostgreSQL.
- Ingest API never executes untrusted agent code.
- Agent sandbox jobs may execute only allowlisted simulated tools in v1.
- Analyzer's explanations are untrusted text; never turn them into privileged code execution.
- Long GPU tasks go to SCC scheduler, not web requests.

---

## 5. Detailed repository layout

```text
agent-blackbox/
  README.md
  LICENSE
  .env.example
  .gitignore
  Makefile
  docker-compose.yml
  docs/
    architecture.md
    decisions/ADR-001-core-stack.md
    data-model.md
    threat-model.md
    replay-contract.md
    benchmark-methodology.md
    developer-runbook.md
    demo-script.md
  apps/
    web/                     # Next.js application
    api/                     # FastAPI routers, services, migrations
  packages/
    blackbox_sdk/            # tracing + event emitter + redaction hooks
    contracts/               # shared JSON Schemas, OpenAPI exports
    agent_harness/           # stateful sandbox demo agent
    replay_engine/           # checkpoint fork, mocks, intervention system
    analysis_engine/         # rule-based detectors and optional hypotheses
    evaluation/              # dataset, verifiers, aggregation/reporting
  infra/
    otel/                    # optional collector config
    db/                      # initialization + seed fixtures
    scc/                     # qsub scripts; batch eval adapter
  tests/
    fixtures/
    integration/
    security/
    e2e/
  scripts/
    seed_demo.py
    generate_fixtures.py
    run_local_demo.sh
  .github/workflows/
    ci.yml
```

**Avoid empty scaffolding:** a directory does not count as done until it contains tested behavior. Don't create lots of dummy modules marked TODO just to make the tree look sophisticated.

---

## 6. Data model and versioned event contract

### Required database tables

| Table | Key fields | Notes |
|---|---|---|
| `projects` | id, name, owner_id, created_at | tenant/project isolation |
| `agents` | id, project_id, name | logical agent definition |
| `agent_versions` | id, agent_id, git_sha, config_hash, model_name | immutable build metadata |
| `executions` | id, project_id, agent_version_id, parent_execution_id, status, task_id, started_at, ended_at | original and fork runs |
| `spans` | id, execution_id, trace_id, span_id, parent_span_id, kind, name, status, start_ms, end_ms, attributes_json | chronology and graph |
| `events` | id, execution_id, span_id, event_type, timestamp, payload_json, dedupe_key | argument/result/errors/state transitions |
| `checkpoints` | id, execution_id, step_index, node_id, state_artifact_uri, state_hash, replay_capability | snapshot before re-run |
| `artifacts` | id, project_id, uri, sha256, type, byte_size, capture_policy | larger redacted outputs |
| `replay_jobs` | id, source_execution_id, checkpoint_id, fork_execution_id, intervention_json, sandbox_config_json, status, replay_mode, requested_at | complete provenance |
| `analysis_findings` | id, execution_id, category, severity, evidence_event_ids, explanation, detector_version | verified observations vs hypotheses |
| `evaluation_cases` | id, dataset_name, input_json, expected_json, verifier_id, fixture_version | immutable benchmark fixtures |
| `evaluation_results` | id, case_id, execution_id, ground_truth_success, metrics_json | score, cost, latency |

Use consistent UUID or ULID keys, foreign keys and indexes. Index `(project_id, started_at)`, `(execution_id, timestamp)`, `(trace_id, span_id)` and `replay_jobs.source_execution_id`. Support `schema_version` and explicitly reject unknown future versions.

### Minimal structured event example

```json
{
  "schema_version": "1.0",
  "event_id": "bfa5c42a-44f0-468c-8394-4e87291123e2",
  "execution_id": "cec2c497-2fde-4d54-8c09-6b07d5369520",
  "trace_id": "d4e9a5d6573d4a2da60189197321ad11",
  "span_id": "54a63a4cf908c33f",
  "parent_span_id": "8dfe331c0fc927a1",
  "sequence_no": 6,
  "timestamp": "2026-10-14T20:00:00Z",
  "event_type": "tool_call_end",
  "operation": "execute_tool",
  "tool_name": "lookup_inventory",
  "status": "error",
  "attributes": {"error_type": "validation_error", "elapsed_ms": 18},
  "payload": {"input_redacted": {"product_name": "red backpack"}, "error_code": "SKU_REQUIRED"}
}
```

Use monotonic sequence numbers for intra-run ordering; wall-clock timestamps alone do not guarantee total ordering across processes. Event reingestion should not duplicate rows (`event_id`/dedupe key).

### Data privacy defaults

- Capture metadata by default, not raw prompts or private tool outputs.
- Prompt/output capture is explicitly opt-in per project and per environment.
- Regex/allowlist redaction and configurable forbidden fields; never persist API keys, authorization headers, cookies, or student/customer personal data in demo traces.
- Restrict artifact access and document retention and deletion.
- A SHA-256 fingerprint can establish artifact identity without exposing content.

---

## 7. API contract, jobs, and real-time updates

### Core endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/projects` | Create project |
| POST | `/api/v1/agents` | Register agent/version |
| POST | `/api/v1/events:batch` | Idempotent event ingest |
| GET | `/api/v1/executions` | Filtered/paginated run listing |
| GET | `/api/v1/executions/{id}` | Run details and aggregate metrics |
| GET | `/api/v1/executions/{id}/timeline` | Events and spans |
| GET | `/api/v1/executions/{id}/graph` | DAG nodes and edges |
| GET | `/api/v1/executions/{id}/checkpoints` | Eligible restore points |
| GET | `/api/v1/executions/{id}/findings` | Failure diagnoses with evidence |
| POST | `/api/v1/replays` | Validate + enqueue replay |
| GET | `/api/v1/replays/{id}` | Replay job status/results |
| GET | `/api/v1/replays/{id}/comparison` | Original/fork metrics and structured diff |
| POST | `/api/v1/evaluations` | Create benchmark job |
| GET | `/api/v1/evaluations/{id}` | Progress and aggregate outcomes |
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Database/Redis readiness |

### Replay request schema (conceptual)

```json
{
  "source_execution_id": "cec2c497-2fde-4d54-8c09-6b07d5369520",
  "checkpoint_id": "valid-checkpoint-uuid",
  "mode": "controlled_stochastic",
  "sandbox": "fixture_only",
  "intervention": {
    "type": "replace_tool_argument",
    "target_span_id": "54a63a4cf908c33f",
    "field": "sku",
    "value": "SKU-RED-004"
  },
  "freeze": ["task_input", "tool_fixtures", "agent_version"]
}
```

Validate that the intervention target occurs *after* the selected checkpoint. Do not silently mutate the source run. Return `202 Accepted` plus `job_id` and process asynchronously. Make replay submission idempotent with an idempotency key. A worker crash should mark/retry safely, never create unnoticed duplicates or perform unsafe side effects.

Use server-sent events for execution/replay progress if simpler than WebSockets; tests must cover reconnection and terminal state.

---

## 8. Checkpointing, replay, and interventions

### Exact flow

1. **Capture:** save state *before* supported agent steps and associate snapshot with immutable agent version, tool fixture version, and execution metadata.
2. **Eligibility check:** verify checkpoint integrity, matching schema, available code version, and sandbox-only tool adapters.
3. **Fork:** create `fork_execution_id`, record `parent_execution_id` and original checkpoint. Never edit the original run.
4. **Restore:** load the checkpoint in a new isolated worker/context. Reset sandbox side-effect store for that branch.
5. **Freeze controls:** fix task input, fixture data, agent code version, and model settings where possible. Record inference model digest/adapter/config.
6. **Apply intervention:** modify one target using an explicit validated strategy.
7. **Execute suffix:** run subsequent nodes; record all new spans/events, model outputs, and tool outcomes.
8. **Verify:** run deterministic task-specific verifier over final sandbox state and expected result.
9. **Compare:** compute step/path differences, success, latency, tool invocations, token/cost estimates; mark replay reproducibility caveat.
10. **Persist:** save lineage and artifact checksums; provide exportable report.

### Intervention types in sensible build order

| Stage | Intervention | Implementation requirement |
|---|---|---|
| MVP | `replace_tool_result` | Frozen fixture response swapped for one tool call |
| MVP | `replace_tool_argument` | Must pass tool schema validation; executed only in sandbox |
| v1 | `replace_retrieval_context` | Frozen retriever corpus/version and retrieved item IDs |
| v1 | `inject_tool_exception` | Synthetic, reproducible timeout/validation error |
| v1.1 | `replace_prompt_fragment` | Record exact prompt hash and model variability |
| v2 | `patch_agent_state` | Controlled schema-validated state change and before/after diff |

### Replay classification

- **Deterministic:** every step and fixture response explicitly controlled (e.g., scripted agent or recorded model outputs).
- **Controlled stochastic:** controlled data and code, fresh model inference; seeds and decoding settings recorded.
- **Best effort:** external time-dependent components remain; make limitations visible.

**Critical implementation warning:** LangGraph checkpoint replay re-executes nodes after the checkpoint. It can re-trigger LLM calls, APIs and interrupts. A production side-effecting tool must be mocked/sandboxed or require a carefully reviewed safe re-execution mechanism. `temperature=0` does not by itself guarantee identical results.

### Minimal accepted replay demo

- Source run fails with a known tool-argument validation error.
- Source execution remains immutable.
- Intervention changes one explicit argument.
- Fork execution has a distinct ID and parent link.
- Replay uses sandboxed tools and returns a measured verified outcome.
- Comparison page shows original failure and fork success, **including which condition was changed**.
- Tests prove tool side effects cannot reach real external destinations.

---

## 9. Evidence-backed failure diagnosis

Start with deterministic detectors; add an LLM summary only after evidence IDs and rules exist.

| Detector | Input evidence | Output |
|---|---|---|
| Invalid tool arguments | Schema validation event with errors | `tool_schema_mismatch` |
| Repeated failed calls | Same tool+args+error pattern N times | `retry_loop` |
| Timeout propagation | Parent timeout, child timeout, incomplete path | `tool_timeout` |
| Budget exhaustion | Max steps/tokens/time threshold reached | `budget_exhausted` |
| Missing retrieval evidence | No grounding documents when required by task | `missing_retrieval` |
| Diverging identity | State key changes inconsistently between nodes | `state_identity_mismatch` |
| Stale fixture | Data timestamp precedes configured freshness window | `stale_data` |

Every finding must store detector version, triggering event IDs, severity, and caveats. The optional model-produced analysis should be labeled **hypothesis**, linked to evidence, and never replace facts. Never claim causal attribution merely because one intervention correlated with a recovered run; stronger claims need controls/repeats.

---

## 10. Evaluation plan and defensible claims

### Benchmark dataset

Build 30-60 scripted customer-support agent tasks with immutable fixtures, spanning correct completion, missing arguments, stale context, timeout, loop, and mismatched IDs. Include known-failure fixtures and successful controls. Start with 10 cases to bring up the pipeline; expand after the replay engine is reliable. Hold out at least 20% of tasks from prompt tuning or detector rule revisions.

### Metrics

- **Task success rate:** task verifier successful / evaluated tasks.
- **Recovery rate on failing baselines:** failed original tasks converted to verifier-confirmed success / replay attempts on failed originals.
- **False intervention benefit rate:** interventions reported helpful when no ground-truth success improvement exists.
- **Failure detector precision/recall/F1:** against manually labeled fixture categories.
- **Replay validity:** eligible attempted branches that complete and preserve source run immutability.
- **Latency:** p50/p95 end-to-end and model/tool stage breakdowns.
- **Cost:** tokens and any cost *estimate*, showing where the price table came from and what is omitted.
- **Isolation incidents:** count of forbidden external side effects; target zero, enforced by tests.

Report denominators, model versions, fixture versions, seed counts, and bootstrap confidence intervals when sample sizes permit. Compare against **no-intervention replay** and **random allowed intervention** baselines to avoid overstating improvement.

### Proposed experiments

- E1: 10 fixtures, deterministic stub, prove end-to-end integrity and branch lineage.
- E2: 30-60 fixtures, OpenAI-compatible model, baseline vs repair, compare task success.
- E3: same tasks across multiple decoding seeds/configurations, report variance.
- E4: remove evidence-based detectors or checkpoint controls and observe whether diagnosis/recovery degrades.
- E5: fault injection (timeouts, bad schema, stale responses), measure diagnosis precision and recovery rate.

All numbers in the README must be generated from runnable evaluation scripts. Never invent impressive improvement percentages.

---

## 11. Work plan: 11 sequential milestones (M0-M10)

**Hard rule:** finish each milestone with a running demo, passing tests, updated docs, and a commit. Do not request all milestones from the coding LLM at once.

| Milestone | Deliverable | Exit gate |
|---|---|---|
| M0 Spec & repo decisions | README, ADR, requirements, architecture, threat model, schemas | All major choices documented; app starts cleanly |
| M1 Infrastructure & contracts | Compose Postgres/Redis, FastAPI health, Next.js shell, migrations | `make dev` works and tests pass |
| M2 Demo agent | Stateful support agent, stub model, sandbox tools, 3 fixtures | Successful and failing runs reproducible without GPU |
| M3 Instrumentation & ingestion | Python SDK, OTel-compatible spans, event batch ingest | Real end-to-end events in DB and idempotency tests pass |
| M4 Trace UI | Runs list, detail timeline, graph and event inspector | Click a real failed run and see the exact invalid step |
| M5 Failure analyzer | 5+ rule detectors and evidence links | Precision/recall tests on labeled fixtures |
| M6 Replay core | Checkpoints, isolated forks, one argument/result intervention | Source immutable; branch replay changes result safely |
| M7 Replay UI & comparison | Replay form, worker progress, before/after diff | Full flagship demo works from browser |
| M8 Evaluation | Fixed benchmark, verifier, metric exports | Reproduce baseline and recovery CSV/JSON |
| M9 SCC & model experiment | `qsub` evaluation, Qwen adapter, artifact import | SCC batch output reproducibly feeds same dashboard |
| M10 Product polish & release | Auth, redaction, CI, e2e, docs, demo video and screenshots | New user can run documented demo end-to-end |

**Effort guidance:** schedule 2-3 weeks for a credible MVP if working intensively, and additional time for model evaluation, robustness, and showcase polish. The milestone **exit gates**, not calendar dates, determine when you move on.

### Recommended MVP boundary

Deliver M0-M7 with 3-10 demo cases and a deterministic stub first. This should already be an impressive working GitHub project. Then grow the evaluation suite and SCC experiments; don't make GPU a prerequisite for the platform to function.

---

## 12. Boston University SCC integration

### Strategy

Develop, test, and demonstrate FastAPI/Next.js/Postgres on your laptop or an authorized standard development host. Use SCC to run **model inference/evaluation batch jobs** and transfer result artifacts to the platform. This avoids depending on a temporary GPU allocation for a publicly available web service.

**SCC note:** BU's Shared Computing Cluster uses `qsub` and `qrsh` with GPU requests in Grid Engine style, **not default Slurm `sbatch`/`srun` commands**. GPU nodes are allocated through the scheduler; don't try to log into GPU nodes directly. See BU documentation linked below.

### Verify access and capacity

```bash
# Commands to run after logging into SCC
pwd
git --version
qgpus
qstat -u "$USER"
```

Use a writable project path; for example a directory under your authorized `/projectnb/...` location. Store Hugging Face/model caches in an authorized project/scratch location with enough quota. Do not assume you may expose arbitrary network ports from compute nodes.

### GPU interactive allocation

```bash
# Request 1 GPU using BU SCC scheduler. Add -P YOUR_PROJECT if required.
qrsh -l gpus=1 -pe omp 4

# Once scheduled on a GPU compute node:
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
```

### Example batch file: `infra/scc/eval_gpu.qsub`

```bash
#!/bin/bash -l
#$ -cwd
#$ -pe omp 4
#$ -l gpus=1
#$ -l h_rt=04:00:00
#$ -j y

set -euo pipefail
cd "$BLACKBOX_WORKDIR"
source .venv/bin/activate
export HF_HOME="$BLACKBOX_CACHE"
python -m evaluation.run_batch \
  --dataset evaluation/datasets/benchmark_v1.jsonl \
  --model "$BLACKBOX_MODEL" \
  --output artifacts/scc/benchmark_v1.jsonl
```

This is a **template**, not an immediately runnable script: the repo's evaluation CLI, Python environment, and variables must first be implemented/configured; use `qsub -P YOUR_PROJECT` if your allocation requires it. Record job ID and model/device details in experiment metadata. If SCC runtime/container restrictions prevent a live OpenAI-compatible server, use direct model inference in the batch worker rather than exposing a network endpoint.

### Compute design

- Local stub model: functional tests and CI, CPU-only.
- Qwen-class 7B/8B open-weight instruct model: GPU experiments, subject to model compatibility and VRAM requirements.
- vLLM (optional): OpenAI-compatible inference **within authorized allocation**; use direct `transformers` adapter if simpler.
- Data handoff: `JSONL` completed run artifacts + manifest with model SHA/revision, prompt version, seed/config, time, Git SHA, SCC job ID.
- Importer: validate schema, dedupe by run ID, link benchmark cases; never import secrets/HF tokens or private data.

---

## 13. Testing, security and reliability

### Test pyramid

**Unit:** schema parsing, redaction, tool mock behavior, replay eligibility, state clone, intervention validation, failure detector accuracy, metric math.

**Integration:** DB migrations, batch-ingest idempotency, queue+worker flow, checkpoint retrieval, immutable original run, artifact integrity, auth isolation.

**End-to-end:** (1) launch failing demo, (2) inspect exact failed tool event, (3) select checkpoint, (4) replay with one argument change, (5) see verified success, (6) export comparison.

**Negative/safety:** unknown event versions, cross-project IDs, oversized payloads, malicious tool arguments, replay without checkpoint, external HTTP forbidden in sandbox, worker crash, duplicate replay requests, inaccessible artifacts, redacted secrets.

### Security checklist

- Local dev with clearly labeled test credentials; before public deployment, implement session/JWT auth and project ownership authorization.
- Rate limits and input-size bounds on ingestion/replay APIs.
- Proper SQL parameterization; no shell execution from raw user-controlled strings.
- Store only required data; redact tokens and sensitive payloads before storage.
- Background jobs run with limited file/network access; explicit allowlist of fixture tools.
- Enforce **no network side effects** during controlled replay unless a domain-scoped, audited development fixture service has been intentionally configured.
- Validate checkpoint artifact hashes and signed metadata where feasible.
- Display model-derived hypotheses as untrusted text; no generated script execution.
- Keep `.env`, service account tokens, private traces, and dataset secrets out of Git history.

### Operational readiness

- Database migrations apply forward from fresh volume.
- Readiness endpoint confirms database and queue dependency.
- Background replay retries do not create duplicate state mutations.
- CI installs cleanly and executes lint/typecheck/tests without GPU.
- Logging is structured and excludes sensitive content.
- Logs/metrics help debug missing spans and asynchronous failures.

---

## 14. GitHub, resume and demonstration strategy

### README structure

1. Banner/clear tagline and short working demo GIF/video.
2. Three-sentence problem and why Agent BlackBox is distinctive.
3. Features with badges **only if implemented and tested**.
4. Screenshot of real run graph, replay studio, and comparison view.
5. One-minute quickstart (`cp .env.example .env`, `docker compose up`, seed demo).
6. Architectural diagram plus decision points.
7. Dataset, methodology, metrics and reproducibility commands.
8. Replay limitations and privacy/safety model.
9. API reference and SDK integration example.
10. Development, test, contribution and license notes.

### Suggested 90-second demo video

- 0:00-0:12: show failing support-agent task.
- 0:12-0:28: open trace, inspect tool validation failure.
- 0:28-0:45: choose checkpoint and one argument intervention.
- 0:45-1:03: run safe replay; show new fork trace being recorded.
- 1:03-1:20: compare original and replay with verified outcome.
- 1:20-1:30: display benchmark metrics and architecture.

### Resume bullet template (fill with measured numbers)

> Built Agent BlackBox, a full-stack agent observability and checkpoint replay platform using FastAPI, Next.js, PostgreSQL, OpenTelemetry, and LangGraph; implemented evidence-linked failure diagnostics, sandboxed counterfactual forks, and reproducible evaluation across [N] tasks, achieving [verified metric].

Avoid claiming it is production-deployed, framework-universal, or causally proven until the implementation and evaluation truly support those words.

---

## 15. Definition of done

The project is **not done** merely when the dashboard loads or the LLM generates a repository. Mark it portfolio-ready only after:

- [ ] One agent produces real success/failure runs without GPU.
- [ ] Run-level trace topology, latency, tool arguments (safe/redacted), and errors are correctly persisted.
- [ ] Failure findings link to source events.
- [ ] One pre-step checkpoint can be restored to a *new* isolated run.
- [ ] Exactly one declared intervention can be applied and audited.
- [ ] Original run is immutable, and no external side effects happen in replay tests.
- [ ] Ground-truth verifier evaluates outcomes, not just an LLM's opinion.
- [ ] API, replay, security, and browser E2E tests pass.
- [ ] Benchmarks generate actual files and reproducible plots/numbers.
- [ ] SCC experiments have model/version/job provenance if included.
- [ ] README screenshots, setup steps, demo video and architecture match the actual product.

---

## 16. References and implementation notes

- OpenTelemetry GenAI semantic conventions (evolving): https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OpenTelemetry OTLP exporter specification: https://opentelemetry.io/docs/specs/otel/protocol/exporter/
- LangGraph persistence and checkpoints: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph time travel / checkpointers: https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/checkpointers.mdx
- BU SCC GPU allocation: https://www.bu.edu/tech/support/research/software-and-programming/gpu-computing/
- BU interactive jobs: https://www.bu.edu/tech/support/research/system-usage/running-jobs/interactive-jobs/
- BU sample batch scripts: https://www.bu.edu/tech/support/research/system-usage/running-jobs/batch-script-examples/

**Execution companion:** Use the separate `Agent_BlackBox_Project1_Codex_Prompts.md` prompt pack. Paste its master instructions first; then complete prompts M0 through M10 in order, checking actual output after each milestone.
