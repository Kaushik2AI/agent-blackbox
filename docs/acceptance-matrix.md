# User stories → acceptance tests, and MVP boundary

## User-story matrix

| # | User story (blueprint §1) | Acceptance test(s) | Milestone | Status |
|---|---|---|---|---|
| — | Platform is up and honest about its health | `test_healthz_is_dependency_free`, `test_readyz_reports_real_failures` (503 when deps down, no secrets in body), `test_readyz_ready_when_services_up_and_migrated`, web `checkConnectivity` unit tests + live smoke through Next.js proxy | M1 | ✅ |
| — | Schema is real and migratable | `test_migration_creates_expected_tables`, `test_foreign_keys_are_enforced`, `test_execution_cannot_be_its_own_parent`, `test_downgrade_then_upgrade_is_clean` | M1 | ✅ |
| — | Background jobs actually run | `test_rq_job_round_trip` (real Redis + RQ worker) | M1 | ✅ |
| — | A real agent produces reproducible successes and failures without a GPU | `test_every_fixture_matches_its_expected_baseline`, `test_invalid_argument_fixture_fails_for_the_intended_reason`, `test_transient_timeout_is_retried_and_recovers`, `test_runs_are_deterministic_over_10_repeats`, `test_no_network_access_during_any_run`, `test_runs_do_not_mutate_fixtures_or_share_sandbox_state` | M2 | ✅ |
| 1 | Register an instrumented app and see completed/failed runs | `test_real_agent_run_is_persisted_with_correct_trace` (SQL-checked), `test_duplicate_batches_create_no_new_rows`, `test_out_of_order_batches_and_missing_parents`, `test_unknown_schema_version_is_rejected_and_nothing_stored`, `test_secrets_are_redacted_server_side_before_storage`, `test_provenance_is_recorded`, SDK `test_sdk.py` | M3 | ✅ |
| 2 | Inspect DAG/timeline of a run | Playwright `e2e/inspector.spec.ts`: filter failed runs, open the invalid-inventory run with the keyboard, click the failing `lookup_inventory` node, see `SKU_REQUIRED`, `validation_error` and the `product_name` argument; API `test_detail_timeline_and_graph`, `test_graph_order_follows_execution_order` | M4 | ✅ |
| 3 | See evidence-backed failure flags | Each detector fires on its labelled fixture with correct `evidence_event_ids`; precision/recall computed from labelled set | M5 | 🚧 |
| 4 | Save/fetch pre-step checkpoints and replay | Checkpoint hash mismatch → ineligible; replay creates new execution with parent link; source unchanged | M6 | 🚧 |
| 5 | Apply one explicit intervention | Invalid intervention (schema fail / target before checkpoint) → 422; valid `replace_tool_argument` on SKU → verifier-confirmed success | M6 | 🚧 |
| 6 | Compare original vs replay | Comparison API returns intervention record, path diff, verifier outcomes, calls/latency; Playwright flagship flow passes | M7 | 🚧 |
| 7 | Run a fixed benchmark and export evidence | One command regenerates JSONL/CSV + charts; metric-math regression tests | M8 | 🚧 |
| — | Run real model on SCC GPU | `qsub` script lints; manifest has job ID/model revision/seed; importer dedupes | M9 | 🚧 |

## Milestone exit gates

| Milestone | Gate (must be demonstrated, not claimed) |
|---|---|
| M0 | Docs consistent with blueprint scope; replay levels, privacy and limitations explicit; every later milestone has a testable exit |
| M1 | Fresh setup (`make setup-scc` or compose) starts; `/readyz` ready; migrations apply; `make check` passes |
| M2 ✅ | 3 fixtures (success, invalid SKU argument, transient timeout) give expected verifier results 10/10 times in stub mode — delivered with 5 fixtures; `make demo`, `make test-harness` |
| M3 ✅ | Agent run persists correct, deduplicated trace rows; redaction tests pass — `make test-api`, `make test-sdk` |
| M4 ✅ | Real failed run opened in UI; exact failing span clickable; no hardcoded data — `make test-e2e` (also verified through the SCC VS Code proxy path) |
| M5 | Findings link to raw events; confusion matrix reproducible from labelled fixtures |
| M6 | Real resumed execution on a fork; source byte-identical at domain level; sandbox tests pass |
| M7 | Flagship browser demo end-to-end with real worker |
| M8 | One documented command rebuilds benchmark artifacts and charts |
| M9 | SCC job submitted on a GPU and imported, or unverified parts documented |
| M10 | Fresh-clone quickstart works; CI green; demo script matches the live app |

## MVP boundary

**In MVP (M0–M7):** one sandboxed customer-support agent, deterministic stub model,
3–10 fixtures, metadata-only capture with redaction, five rule detectors, checkpoint replay
with `replace_tool_argument` and `replace_tool_result`, Replay Studio + comparison view.

**Not in MVP:** real LLM inference (M9), 30–60 case benchmark and statistics (M8),
retrieval/prompt/state interventions (v1+), authentication beyond local dev (M10),
multi-tenant hosting, Kubernetes, arbitrary-framework replay, automatic fixing.
