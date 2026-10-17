# FlightPath benchmark results: benchmark_v1

Agent: `Qwen/Qwen2.5-3B-Instruct` (hf:Qwen/Qwen2.5-3B-Instruct). Agent harness 0.3.1. Seed 7.
52 cases, 462 runs. Generated from `runs.jsonl` by `python -m evaluation.benchmark`.

| Metric | All cases | Dev | Held-out |
|---|---|---|---|
| Baseline success | 79% (124/156; 95% CI 72-85%) | 82% (89/108; 95% CI 74-88%) | 73% (35/48; 95% CI 59-83%) |
| Recovery with FlightPath's change | 22% (7/32; 95% CI 11-39%) | 21% (4/19; 95% CI 9-43%) | 23% (3/13; 95% CI 8-50%) |
| Recovery with a random valid change | 22% (28/130; 95% CI 15-29%) | 20% (17/85; 95% CI 13-30%) | 24% (11/45; 95% CI 14-39%) |
| Recovery when restarting with no change | 0% (0/26; 95% CI 0-13%) | 0% (0/17; 95% CI 0-18%) | 0% (0/9; 95% CI 0-30%) |
| Repair coverage (a change was proposed) | 22% (7/32; 95% CI 11-39%) | 21% (4/19; 95% CI 9-43%) | 23% (3/13; 95% CI 8-50%) |
| Replay validity (no-change replay reproduces) | 100% (150/150; 95% CI 98-100%) | 100% (106/106; 95% CI 96-100%) | 100% (44/44; 95% CI 92-100%) |
| False benefit (recovered without the change) | 0% (0/7; 95% CI 0-35%) | 0% (0/4; 95% CI 0-49%) | 0% (0/3; 95% CI 0-56%) |

## By family

| Family | Cases | Baseline success | Recovery (FlightPath) | Recovery (random) |
|---|---|---|---|---|
| control_exchange | 8 | 100% (24/24; 95% CI 86-100%) | n/a (0 runs) | n/a (0 runs) |
| control_recovered_timeout | 6 | 83% (15/18; 95% CI 61-94%) | 0% (0/3; 95% CI 0-56%) | 80% (4/5; 95% CI 38-96%) |
| control_refund | 6 | 78% (14/18; 95% CI 55-91%) | 0% (0/4; 95% CI 0-49%) | 10% (1/10; 95% CI 2-40%) |
| invalid_argument | 8 | 100% (24/24; 95% CI 86-100%) | n/a (0 runs) | n/a (0 runs) |
| persistent_timeout | 6 | 61% (11/18; 95% CI 39-80%) | 100% (7/7; 95% CI 65-100%) | 26% (9/35; 95% CI 14-42%) |
| repeat_loop | 6 | 100% (18/18; 95% CI 82-100%) | n/a (0 runs) | n/a (0 runs) |
| stale_retrieval | 6 | 6% (1/18; 95% CI 1-26%) | 0% (0/17; 95% CI 0-18%) | 18% (14/80; 95% CI 11-27%) |
| wrong_identity | 6 | 94% (17/18; 95% CI 74-99%) | 0% (0/1; 95% CI 0-79%) | n/a (0 runs) |

## Detectors (baseline runs, against case labels)

| Category | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| tool_schema_mismatch | 0 | 0 | 42 | n/a (0 runs) | 0% (0/42; 95% CI 0-8%) |
| retry_loop | 0 | 0 | 42 | n/a (0 runs) | 0% (0/42; 95% CI 0-8%) |
| tool_timeout | 18 | 7 | 0 | 72% (18/25; 95% CI 52-86%) | 100% (18/18; 95% CI 82-100%) |
| budget_exhausted | 0 | 0 | 42 | n/a (0 runs) | 0% (0/42; 95% CI 0-8%) |
| state_identity_mismatch | 0 | 0 | 18 | n/a (0 runs) | 0% (0/18; 95% CI 0-18%) |
| repeated_action | 0 | 2 | 0 | 0% (0/2; 95% CI 0-66%) | n/a (0 runs) |

Failed runs where at least one detector fired: 25% (8/32; 95% CI 13-42%).
Passed runs where a detector fired anyway: 15% (18/124; 95% CI 9-22%).

Failed runs by most likely cause: none 24, tool_timeout 7, repeated_action 1.

## Latency per run

| Arm | Median | p95 | Mean tokens |
|---|---|---|---|
| baseline | 4035.44 ms | 4806.32 ms | 4238.6 |
| no_change | 2946.69 ms | 3686.97 ms | 3425.6 |
| repair | 2977.41 ms | 3290.32 ms | 3268.4 |
| random | 2518.7 ms | 3880.41 ms | 2619.2 |

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
