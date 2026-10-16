# User stories → acceptance tests, and MVP boundary

## User-story matrix

| # | User story | Acceptance test(s) | Milestone | Status |
|---|---|---|---|---|
| — | Platform is up and honest about its health | `test_healthz_is_dependency_free`, `test_readyz_reports_real_failures` (503 when deps down, no secrets in body), `test_readyz_ready_when_services_up_and_migrated`, web `checkConnectivity` unit tests + live smoke through Next.js proxy | M1 | ✅ |
| — | Schema is real and migratable | `test_migration_creates_expected_tables`, `test_foreign_keys_are_enforced`, `test_execution_cannot_be_its_own_parent`, `test_downgrade_then_upgrade_is_clean` | M1 | ✅ |
| — | Background jobs actually run | `test_rq_job_round_trip` (real Redis + RQ worker) | M1 | ✅ |
| — | A real agent produces reproducible successes and failures without a GPU | `test_every_fixture_matches_its_expected_baseline`, `test_invalid_argument_fixture_fails_for_the_intended_reason`, `test_transient_timeout_is_retried_and_recovers`, `test_runs_are_deterministic_over_10_repeats`, `test_no_network_access_during_any_run`, `test_runs_do_not_mutate_fixtures_or_share_sandbox_state` | M2 | ✅ |
| 1 | Register an instrumented app and see completed/failed runs | `test_real_agent_run_is_persisted_with_correct_trace` (SQL-checked), `test_duplicate_batches_create_no_new_rows`, `test_out_of_order_batches_and_missing_parents`, `test_unknown_schema_version_is_rejected_and_nothing_stored`, `test_secrets_are_redacted_server_side_before_storage`, `test_provenance_is_recorded`, SDK `test_sdk.py` | M3 | ✅ |
| 2 | Inspect DAG/timeline of a run | Playwright `e2e/inspector.spec.ts`: filter failed runs, open the invalid-inventory run with the keyboard, click the failing `lookup_inventory` node, see `SKU_REQUIRED`, `validation_error` and the `product_name` argument; API `test_detail_timeline_and_graph`, `test_graph_order_follows_execution_order` | M4 | ✅ |
| 3 | See evidence-backed failure flags | `test_detectors.py` (every finding cites real event IDs; healthy/recovered runs produce none; thresholds), `analysis_engine.evaluation` precision/recall per category from labelled fixtures, API `test_findings_are_stored_at_ingest_and_cite_real_events`, Playwright findings visible | M5 | ✅ |
| 4 | Save/fetch pre-step checkpoints and replay | `test_checkpoint_hash_mismatch_makes_it_ineligible`, `test_plain_checkpoint_replay_reproduces_the_original`, `test_flagship_fix_recovers_the_run_and_source_stays_immutable` (row fingerprint before == after), harness `test_replay.py` | M6 | ✅ |
| 5 | Apply one explicit intervention | `test_invalid_replay_requests_are_rejected` (schema, before checkpoint, non-tool span, bad result, stochastic mode, foreign checkpoint), `test_replace_tool_result_recovers_persistent_timeout`, `test_forbidden_network_access_fails_the_replay`, `test_crashed_attempt_is_cleaned_up_and_retried`, `test_same_idempotency_key_returns_the_same_job` | M6 | ✅ |
| 6 | Compare original vs replay | Comparison asserted in `test_flagship_fix...` (intervention record, first divergence, intervened step, state diff); Playwright `e2e/replay.spec.ts` flagship flow + disabled controls without checkpoints | M7 | ✅ |
| 7 | Run a fixed benchmark and export evidence | `make benchmark` rebuilds runs.jsonl/CSV/summary/charts from scratch; `test_evaluation.py`: dataset drift, every case fails for its intended reason, Wilson interval reference values, denominators, reproducibility, resume without duplicates; API `test_evaluations_api.py`; Playwright `e2e/benchmark.spec.ts` | M8 | ✅ |
| — | Run a real model on a GPU | Job scripts (Grid Engine, Slurm) pass shellcheck; the full path (environment check, transformers model, seeds, resumable manifest with job id/model revision/versions, import with dedupe and secret rejection) ran end to end on CPU with a small model | M9 | ✅ built, GPU run pending |

## Milestone exit gates

| Milestone | Gate (must be demonstrated, not claimed) |
|---|---|
| M0 | Docs consistent with blueprint scope; replay levels, privacy and limitations explicit; every later milestone has a testable exit |
| M1 | Fresh setup (`make setup` or compose) starts; `/readyz` ready; migrations apply; `make check` passes |
| M2 ✅ | 3 fixtures (success, invalid SKU argument, transient timeout) give expected verifier results 10/10 times in stub mode — delivered with 5 fixtures; `make demo`, `make test-harness` |
| M3 ✅ | Agent run persists correct, deduplicated trace rows; redaction tests pass — `make test-api`, `make test-sdk` |
| M4 ✅ | Real failed run opened in UI; exact failing span clickable; no hardcoded data — `make test-e2e` (also verified through a web-IDE port proxy) |
| M5 ✅ | Findings link to raw events; confusion matrix reproducible from labelled fixtures — `make test-analysis`, `make eval-detectors` |
| M6 ✅ | Real resumed execution on a fork; source byte-identical at domain level; sandbox tests pass — `make test-api` (`test_replay_api.py`), harness `test_replay.py` |
| M7 ✅ | Flagship browser demo end-to-end with real worker — `make test-e2e` (`e2e/replay.spec.ts`) |
| M8 ✅ | One documented command rebuilds benchmark artifacts and charts — `make benchmark` |
| M9 | GPU job submitted and imported, or unverified parts documented — built and smoke-tested on CPU; GPU run pending (docs/benchmark.md) |
| M10 | Fresh-clone quickstart works; CI green; demo script matches the live app |

## MVP boundary

**In MVP (M0–M7):** one sandboxed customer-support agent, deterministic stub model,
3–10 fixtures, metadata-only capture with redaction, five rule detectors, checkpoint replay
with `replace_tool_argument` and `replace_tool_result`, Replay Studio + comparison view.

**Not in MVP:** real LLM inference (M9), 30–60 case benchmark and statistics (M8),
retrieval/prompt/state interventions (v1+), authentication beyond local dev (M10),
multi-tenant hosting, Kubernetes, arbitrary-framework replay, automatic fixing.
