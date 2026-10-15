# Data model and contracts

Keys are UUIDs (v4) everywhere except OpenTelemetry `trace_id` (32 hex) and `span_id`
(16 hex), which keep OTel formats. All timestamps are `timestamptz` (UTC).

## 1. Tables

| Table | Status | Key columns | Constraints / indexes |
|---|---|---|---|
| `projects` | ✅ M1 | id, name, owner_id, created_at | `name` unique |
| `agents` | ✅ M1 | id, project_id → projects, name | unique (project_id, name); FK cascade |
| `agent_versions` | ✅ M1 | id, agent_id → agents, git_sha, config_hash, model_name | unique (agent_id, git_sha, config_hash) — immutable builds |
| `executions` | ✅ M1 | id, project_id, agent_version_id, parent_execution_id → executions, status (enum), task_id, started_at, ended_at | index (project_id, started_at); FK RESTRICT on version and parent; CHECK not own parent |
| `spans` | ✅ M3 | id, execution_id, trace_id, span_id, parent_span_id, kind, name, status, start_ms, end_ms, attributes_json | unique (trace_id, span_id); parent may be missing (out-of-order tolerated) |
| `events` | ✅ M3 | id, execution_id, span_id, sequence_no, event_type, timestamp, payload_json, dedupe_key | unique dedupe_key (= event_id); index (execution_id, sequence_no) |
| `checkpoints` | 🚧 M6 | id, execution_id, step_index, node_id, state_artifact_uri, state_hash, replay_capability | unique (execution_id, step_index) |
| `artifacts` | ✅ M3/M6 | id, project_id, uri, sha256, type, byte_size, capture_policy | sha256 verified on read |
| `replay_jobs` | 🚧 M6 | id, source_execution_id, checkpoint_id, fork_execution_id, intervention_json, sandbox_config_json, status, replay_mode, idempotency_key, requested_at | unique idempotency_key; index source_execution_id |
| `analysis_findings` | 🚧 M5 | id, execution_id, category, severity, evidence_event_ids, explanation, detector_version, kind (`verified`/`hypothesis`) | index execution_id |
| `evaluation_cases` | 🚧 M8 | id, dataset_name, input_json, expected_json, verifier_id, fixture_version, split | immutable |
| `evaluation_results` | 🚧 M8 | id, case_id, execution_id, ground_truth_success, metrics_json | — |

Tables are added by the milestone that writes to them, through Alembic migrations.
`apps/api/migrations/versions/0001_m1_base_schema.py` creates the ✅ rows above and is
tested for upgrade → downgrade → upgrade.

## 2. Event contract v1.0 (ingest, M3 ✅)

One request = one execution: `{schema_version, resource{project, agent, agent_version{git_sha,
config_hash, model_name}, sdk}, execution{execution_id, task_id, status, started_at,
ended_at, attributes}, spans[], events[], artifacts[]}`. Implemented in
`apps/api/app/contracts.py`; projects, agents and agent versions are created on first sight
(no auth yet — local development only). Limits: 2 MB per request (`413`), 32 KB per stored
payload/attribute map (larger ones become `{_truncated, original_bytes, sha256}`), 10,000
events and 5,000 spans per batch. Each event:

```json
{
  "schema_version": "1.0",
  "event_id": "uuid — idempotency key",
  "execution_id": "uuid",
  "trace_id": "32 lowercase hex",
  "span_id": "16 lowercase hex",
  "parent_span_id": "16 hex | null",
  "sequence_no": 6,
  "timestamp": "RFC 3339 UTC",
  "event_type": "agent_start | agent_end | llm_call_start | llm_call_end | tool_call_start | tool_call_end | state_transition | checkpoint_saved | error",
  "operation": "execute_tool | chat | invoke_agent | ...",
  "tool_name": "string | null",
  "status": "ok | error",
  "attributes": {"elapsed_ms": 18, "error_type": "validation_error"},
  "payload": {"input_redacted": {}, "error_code": "SKU_REQUIRED"}
}
```

Rules:

- **Unknown `schema_version` is rejected** (`422`), including future versions.
- Ordering inside a run uses `sequence_no` (monotonic per execution), not wall clock.
- Re-sending a batch is safe: rows dedupe on `event_id`.
- Events may arrive before their parent span; the span is linked when it arrives.
- `payload` is **redacted before persistence**. Default capture = metadata only.
- Batch size and per-event payload size are bounded (limits defined in M3, enforced with
  `413`).
- `operation` / attribute names follow the OpenTelemetry GenAI semantic conventions where a
  mapping exists; the adapter is versioned because those conventions are still evolving.

## 3. Tool contracts (M2 ✅)

Each simulated tool has a Pydantic input and output model exported as JSON Schema in
[`packages/contracts/tools.v1.json`](../packages/contracts/tools.v1.json) (a test fails if
code and file drift), plus explicit error codes. Example: `lookup_inventory(sku: str /^SKU-[A-Z0-9-]+$/)` →
`{sku, available, quantity, as_of}` or error `SKU_REQUIRED | SKU_NOT_FOUND | TIMEOUT`.

## 4. Privacy defaults

- Metadata only by default. Raw prompts/tool payloads are opt-in per project **and**
  per environment.
- Never stored, even when capture is on: API keys, `Authorization` headers, cookies,
  passwords, tokens, and fields on the project's forbidden list.
- Artifacts are addressed by SHA-256 so identity can be checked without exposing content.
