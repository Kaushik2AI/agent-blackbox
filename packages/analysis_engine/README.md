# analysis_engine — evidence-backed failure detectors (M5)

Five deterministic detectors over one execution's recorded events. Each finding carries
`category`, `severity`, `evidence_event_ids`, `evidence_span_ids`, `detector_version`, an
explanation and caveats. They work on **metadata-only** traces (error codes, error types,
argument field names, salted identity fingerprints), never on captured values.

| Detector | Fires when | Severity |
|---|---|---|
| `tool_schema_mismatch` | a tool rejected its arguments (`error_type = validation_error`) | high |
| `retry_loop` | ≥ 4 consecutive identical failing calls (same tool, input shape, identity, error) | high |
| `tool_timeout` | a tool timed out and no later call to it succeeded | high |
| `budget_exhausted` | the tool-call budget stopped the run | high |
| `state_identity_mismatch` | a later step used a different `order_id`/`sku`/`customer_id` than earlier steps established | critical |

`python -m analysis_engine.evaluation` (or `make eval-detectors`) runs every fixture through
the real agent and SDK, applies the detectors and scores them against
`labels/v1.json`. Findings are observations, not proofs of root cause. Optional
model-written "hypothesis" narratives are **not implemented**; the `kind` field reserves
the slot.
