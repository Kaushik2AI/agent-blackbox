# Replay contract

> Implemented in M6/M7 (`packages/agent_harness` resume + interventions,
> `apps/api/app/services/replay.py` orchestration, Replay Studio UI). Notes on what the
> implementation does are marked **Implemented:**.

This document defines what Agent BlackBox means by "replay". Anything that does not meet
these rules must not be labelled replay in code, API or UI.

## 1. Three capability levels (kept separate in code and UI)

| Level | Name | What actually happens | Code that does it | Produces |
|---|---|---|---|---|
| 1 | **Trace visualization** | Displays recorded spans/events. Nothing is re-executed. | `apps/web` inspector (M4) | Nothing new; read-only |
| 2 | **Checkpoint replay** | Restores a saved pre-step state into a **new** execution and re-runs the remaining steps with sandbox tools, **no intervention**. | `packages/replay_engine` (M6) | New execution + lineage |
| 3 | **Controlled counterfactual** | Same as level 2 but applies **exactly one** declared, schema-validated intervention before the suffix runs. | `packages/replay_engine` (M6) | New execution + lineage + intervention record + environment fingerprint |

Editing stored JSON, re-drawing a graph, or computing a hypothetical diff is **level 1**,
never "replay".

## 2. Replay classification (every fork records one)

| Class | Meaning | When |
|---|---|---|
| `deterministic` | Every model output and tool response is controlled (scripted stub model / recorded outputs + frozen fixtures). Same inputs → same trace. | Stub model mode (MVP) |
| `controlled_stochastic` | Code, fixtures, task input frozen; **fresh model inference**. Seed, decoding params, model revision recorded. Outcomes may vary. | Real model (M9) |
| `best_effort` | Some time-dependent or external component remains. Limitations shown in UI. | Not used in v1 sandbox |

`temperature=0` alone does **not** qualify a run as `deterministic`.

## 3. Lifecycle of a replay job (M6)

1. **Capture** (during the source run): pre-step state snapshot per supported node, stored
   as an artifact with SHA-256 `state_hash`, linked to agent version, fixture version and
   execution.
2. **Eligibility check** at request time — all must pass, else `422` with reason:
   - checkpoint exists, belongs to the source execution, artifact hash matches;
   - agent code version and fixture version for the checkpoint are available;
   - every tool the suffix may call is in the sandbox allowlist;
   - intervention target span occurs **after** the checkpoint (`sequence_no` order).
3. **Fork:** create `fork_execution_id` with `parent_execution_id = source`. Source row,
   spans and events are never updated.
4. **Restore** into a fresh isolated context; reset the per-fork sandbox side-effect store.
5. **Freeze:** task input, tool fixtures, agent version (and model settings where possible).
6. **Apply intervention** (level 3 only).
7. **Execute suffix**; the SDK records a brand-new trace for the fork.
8. **Verify** with the deterministic task verifier on final sandbox state.
9. **Compare** source vs fork: path diff, verifier outcome, calls, latency, tokens/cost.
10. **Persist** lineage, intervention record, artifact checksums, replay class.

## 4. Request shape (API: `POST /api/v1/replays` → `202 Accepted {job_id}`)

```json
{
  "source_execution_id": "uuid",
  "checkpoint_id": "uuid",
  "mode": "deterministic",
  "sandbox": "fixture_only",
  "intervention": {
    "type": "replace_tool_argument",
    "target_span_id": "16-hex span id",
    "field": "sku",
    "value": "SKU-RED-004"
  },
  "freeze": ["task_input", "tool_fixtures", "agent_version"],
  "idempotency_key": "client-generated string"
}
```

- Same `idempotency_key` → same job, never a second fork.
- Worker crash → job retried; the fork execution is created once (keyed on job id); a
  retried job resumes or marks the fork `aborted`, never creates an unnoticed duplicate.

## 5. Interventions (build order)

| Stage | Type | Rule |
|---|---|---|
| MVP (M6) | `replace_tool_result` | Swap one tool call's frozen fixture response; must match the tool's result schema |
| MVP (M6) | `replace_tool_argument` | Change one argument field; the full argument object must pass the tool's input schema |
| v1 | `replace_retrieval_context` | Frozen corpus version + item IDs |
| v1 | `inject_tool_exception` | Synthetic, reproducible timeout/validation error |
| v1.1 | `replace_prompt_fragment` | Prompt hash recorded; variability measured |
| v2 | `patch_agent_state` | Schema-validated state change with before/after diff |

Exactly **one** intervention per fork. Multiple changes = multiple forks.

**Implemented:** `replace_tool_argument` accepts either the full `arguments` object or a
`field`/`value` edit (with optional `remove_fields`) applied to the recorded arguments; the
resolved arguments must validate against the tool's input contract (`extra` fields
forbidden). `replace_tool_result` must validate against the output contract. The target
must be a tool span at or after the checkpoint's call. `controlled_stochastic` requests are
rejected with an explanation until a real model adapter exists (M9). Fork traces contain
only the re-executed suffix plus a `replay_start` event; the comparison marks earlier steps
as inherited.

## 6. Side-effect isolation

- Replay workers can call only allowlisted **simulated** tools (`lookup_order`,
  `lookup_inventory`, `get_policy`, `draft_response`, `submit_resolution`). The last two
  write to a per-fork sandbox store; nothing is sent anywhere.
- Outbound network from the replay context is blocked at the socket level in tests (M6
  test: any connection attempt fails the job and is counted as an isolation incident).
- Target for isolation incidents: **0**, enforced by tests, reported in benchmarks.

## 7. Non-determinism and honest claims

- A recovered fork shows that *this* intervention was followed by success *in this run*.
  It does not prove causation. Causal-sounding claims need controls: no-intervention
  replay and random-allowed-intervention baselines, plus repeats across seeds (M8).
- UI must show the replay class next to every fork outcome.
