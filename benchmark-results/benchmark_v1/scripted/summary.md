# FlightPath benchmark results: benchmark_v1

Agent: `stub-planner-v1` (stub). Agent harness 0.3.1. Seed 7.
52 cases, 296 runs. Generated from `runs.jsonl` by `python -m evaluation.benchmark`.

| Metric | All cases | Dev | Held-out |
|---|---|---|---|
| Baseline success | 38% (20/52; 95% CI 26-52%) | 39% (14/36; 95% CI 25-55%) | 38% (6/16; 95% CI 18-61%) |
| Recovery with FlightPath's change | 81% (26/32; 95% CI 65-91%) | 82% (18/22; 95% CI 61-93%) | 80% (8/10; 95% CI 49-94%) |
| Recovery with a random valid change | 22% (35/160; 95% CI 16-29%) | 20% (22/110; 95% CI 14-28%) | 26% (13/50; 95% CI 16-40%) |
| Recovery when restarting with no change | 0% (0/32; 95% CI 0-11%) | 0% (0/22; 95% CI 0-15%) | 0% (0/10; 95% CI 0-28%) |
| Repair coverage (a change was proposed) | 81% (26/32; 95% CI 65-91%) | 82% (18/22; 95% CI 61-93%) | 80% (8/10; 95% CI 49-94%) |
| Replay validity (no-change replay reproduces) | 100% (52/52; 95% CI 93-100%) | 100% (36/36; 95% CI 90-100%) | 100% (16/16; 95% CI 81-100%) |
| False benefit (recovered without the change) | 0% (0/26; 95% CI 0-13%) | 0% (0/18; 95% CI 0-18%) | 0% (0/8; 95% CI 0-32%) |

## By family

| Family | Cases | Baseline success | Recovery (FlightPath) | Recovery (random) |
|---|---|---|---|---|
| control_exchange | 8 | 100% (8/8; 95% CI 68-100%) | n/a (0 runs) | n/a (0 runs) |
| control_recovered_timeout | 6 | 100% (6/6; 95% CI 61-100%) | n/a (0 runs) | n/a (0 runs) |
| control_refund | 6 | 100% (6/6; 95% CI 61-100%) | n/a (0 runs) | n/a (0 runs) |
| invalid_argument | 8 | 0% (0/8; 95% CI 0-32%) | 100% (8/8; 95% CI 68-100%) | 32% (13/40; 95% CI 20-48%) |
| persistent_timeout | 6 | 0% (0/6; 95% CI 0-39%) | 100% (6/6; 95% CI 61-100%) | 40% (12/30; 95% CI 25-58%) |
| repeat_loop | 6 | 0% (0/6; 95% CI 0-39%) | 100% (6/6; 95% CI 61-100%) | 17% (5/30; 95% CI 7-34%) |
| stale_retrieval | 6 | 0% (0/6; 95% CI 0-39%) | 0% (0/6; 95% CI 0-39%) | 17% (5/30; 95% CI 7-34%) |
| wrong_identity | 6 | 0% (0/6; 95% CI 0-39%) | 100% (6/6; 95% CI 61-100%) | 0% (0/30; 95% CI 0-11%) |

## Detectors (baseline runs, against case labels)

| Category | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| tool_schema_mismatch | 14 | 0 | 0 | 100% (14/14; 95% CI 78-100%) | 100% (14/14; 95% CI 78-100%) |
| retry_loop | 14 | 0 | 0 | 100% (14/14; 95% CI 78-100%) | 100% (14/14; 95% CI 78-100%) |
| tool_timeout | 6 | 0 | 0 | 100% (6/6; 95% CI 61-100%) | 100% (6/6; 95% CI 61-100%) |
| budget_exhausted | 14 | 0 | 0 | 100% (14/14; 95% CI 78-100%) | 100% (14/14; 95% CI 78-100%) |
| state_identity_mismatch | 6 | 0 | 0 | 100% (6/6; 95% CI 61-100%) | 100% (6/6; 95% CI 61-100%) |
| repeated_action | 0 | 0 | 0 | n/a (0 runs) | n/a (0 runs) |

Failed runs where at least one detector fired: 81% (26/32; 95% CI 65-91%).
Passed runs where a detector fired anyway: 0% (0/20; 95% CI 0-16%).

Failed runs by most likely cause: tool_schema_mismatch 14, none 6, state_identity_mismatch 6, tool_timeout 6.

## Latency per run

| Arm | Median | p95 | Mean tokens |
|---|---|---|---|
| baseline | 9.02 ms | 13.31 ms | 0.0 |
| no_change | 7.19 ms | 10.92 ms | 0.0 |
| repair | 7.19 ms | 8.24 ms | 0.0 |
| random | 6.83 ms | 9.26 ms | 0.0 |

## How to read this

- Intervals are 95% Wilson score intervals. Random-change runs are several draws per
  case, so their interval is narrower than the number of cases justifies.
- With the scripted agent every run is deterministic: one run per case and arm is the
  whole distribution. Real-model runs (GPU) repeat each case with different seeds.
- The repair rules and detectors were written against the hand-made demo fixtures,
  not these cases; the held-out split is reported separately anyway.
- Recovery shows that a change was followed by success, compared against the two
  controls (no change, random change). It is not by itself proof of the root cause.

## Definitions

```
Benchmark metrics from run records. Every number states its denominator.

Definitions (also printed in the report):
  success rate        baseline runs that passed the outcome check / baseline runs
  repair coverage     failed baseline runs for which a repair rule produced a change /
                      failed baseline runs
  recovery (repair)   failed baseline runs that passed after the repair /
                      failed baseline runs        (no change produced = not recovered)
  recovery (random)   random-change runs that passed / random-change runs on failed cases
  replay validity     no-change replays whose outcome, ending and saved effects match
                      the baseline / no-change replays
  false benefit       repair recoveries where the no-change replay from the same step
                      ALSO passed (so the change was not needed) / repair recoveries
  detector P/R        per category, over baseline runs, against the case labels
```
