# Benchmark method

The benchmark asks one question: **when FlightPath suggests a change for a failed run, does
the run then succeed more often than it would with a random change, or with no change?**

## Dataset (`benchmark_v1`)

52 synthetic customer-support tickets, generated from a fixed seed by
`packages/evaluation/evaluation/dataset.py` and committed as
`packages/agent_harness/agent_harness/benchmarks/benchmark_v1.jsonl`. A test regenerates the
file and fails on any drift. Every case has its own world: three customers and orders, four
products with their own codes and stock (three are decoys), and the store policies.

| Family | Cases | What the scripted agent does | Expected findings |
|---|---|---|---|
| control_exchange | 8 | Item in stock; arranges an exchange (passes) | none |
| control_refund | 6 | Item out of stock; refunds (passes) | none |
| control_recovered_timeout | 6 | Stock check times out once; retry works (passes) | none |
| invalid_argument | 8 | Sends the product name instead of the code, repeats it | wrong input, loop, out of steps |
| repeat_loop | 6 | Writes the order id in lower case, repeats it | wrong input, loop, out of steps |
| persistent_timeout | 6 | Stock system never answers; gives up | timeout |
| stale_retrieval | 6 | A month-old cached record says "out of stock"; refunds instead of exchanging | stale data |
| wrong_identity | 6 | Looks up one order, closes the ticket on another customer's | order mix-up |

A tool result can carry an `as_of` snapshot timestamp. The recorder emits it, with the
logical "now" the agent read it at, as event metadata (never the retrieved values), so the
stale-data detector can tell the agent acted on an out-of-date snapshot. The freshness
window is 30 days; the fixtures' fresh snapshots are dated 2026-10-01 and the stale one
2026-08-12, so the split is deterministic and independent of wall-clock time.

The last two cases of each family (16) are the **held-out** split. Nothing was tuned on
them: the repair rules and detectors predate the benchmark and were written against the
hand-made demo fixtures.

## Arms

Each case runs through the real agent harness and the real recording SDK.

| Arm | What runs |
|---|---|
| baseline | The agent from scratch |
| no_change | Restart from the saved step before the repair target (or the first failing step) with nothing changed |
| repair | Restart from the failing step with the change FlightPath suggests, built only from what the run recorded |
| random | Restart from a random recorded step with a random valid change: a valid input or a valid answer for that tool, drawn from the same world (5 draws per failed case) |

Repair and random run only on failed baselines. When no repair rule applies, the run is
recorded as "no change proposed" and counts as **not recovered**.

## Metrics

All rates come with 95% Wilson score intervals and explicit numerators and denominators.

| Metric | Numerator / denominator |
|---|---|
| Success rate | baseline runs that passed / baseline runs |
| Repair coverage | failed runs with a proposed change / failed runs |
| Recovery (repair) | failed runs that passed after the suggested change / failed runs |
| Recovery (random) | random-change runs that passed / random-change runs on failed cases |
| Recovery (no change) | no-change replays of failed runs that passed / those replays |
| Replay validity | no-change replays matching the baseline's outcome, ending and saved effects / no-change replays |
| False benefit | repair recoveries where the no-change replay from the same step also passed / repair recoveries |
| Detector precision, recall | per category over baseline runs, against each case's expected findings |
| Failure causes | failed baseline runs grouped by their most likely cause (the app's ranking), or "nothing detected"; needs no labels |
| Latency | median and p95 per arm (wall clock) |
| Tokens and cost | per arm; cost only when prices are given (`--price-in`, `--price-out`) |

Random-change draws are several per case, so their interval is narrower than the number of
independent cases justifies; read it as a lower bound on uncertainty.

## Reproducing

```bash
make benchmark                 # CPU, ~10 s: checks the dataset, rebuilds every artifact
make benchmark-report          # recompute summary and charts from runs.jsonl only
make benchmark-import          # load into the app (Benchmark page)
```

Outputs in `benchmark-results/benchmark_v1/<name>/`: `runs.jsonl` (the source of truth, one
record per run), `runs.csv`, `summary.json`, `summary.md`, `charts/*.svg`,
`run_config.json`, and `traces.jsonl` (recorded runs for import; not committed).

## Real models on a GPU

```bash
make gpu-setup                                      # once: CUDA PyTorch, transformers, model download
qsub infra/batch/sge_eval.sh                        # or: sbatch infra/batch/slurm_eval.sh
qsub -v MODEL=Qwen/Qwen2.5-7B-Instruct,REPEATS=5 infra/batch/sge_eval.sh
```

- The model runs in-process with transformers (`packages/evaluation/evaluation/hf.py`):
  same prompt, JSON action format and parsing as the app's hosted-API adapter. Generation
  stops at the first complete JSON object.
- Decoding defaults to temperature 0.2 (the app's Live AI setting), top-p 0.9, at most
  256 new tokens. The prompt version (`agent_harness.llm.PROMPT_VERSION`) is recorded with
  the decoding settings. Version 2 tells the model after the reply draft and after the
  resolution that the work is saved; without that, Qwen2.5-3B repeated the reply and the
  resolution in 3 of 4 smoke-test runs.
- Case labels describe the fault planted for the scripted agent. A real model makes its
  own mistakes (for example closing the ticket twice), so for real-model runs read
  "failure causes" rather than the per-category precision and recall.
- `--repeats N` runs every case N times with different seeds. The seed of each model
  decision is the run's seed plus the conversation's length, so a run restarted from a
  saved step draws the same samples the original drew from there on. That is what lets a
  no-change replay of a sampling model reproduce the run, and it makes the repair, random
  and no-change arms differ only by their change (same seed for all three).
- The job writes after every case, so a killed job resumes with `--resume` and the same
  output folder; finished cases are skipped and nothing is duplicated (tested).
- Every record carries the model id and resolved revision, decoding settings, seed, agent
  and fixture versions, Python/torch/CUDA versions, GPU name and scheduler job id (no host
  names, so results can be shared).
- `python -m evaluation.envcheck --require-gpu` checks packages, GPU visibility and a
  writable model cache before any work starts.
- Nothing listens on a network port; results are files. `make benchmark-import` validates
  every record, rejects anything secret-shaped, dedupes on `run_key`, and ingests the
  recorded runs so each one opens in the app.

## Real-model results: Qwen2.5-3B-Instruct

One GPU, bf16, temperature 0.2, prompt version 2, 3 seeds per case, 462 runs, 23 minutes.
Full tables: [`summary.md`](../benchmark-results/benchmark_v1/qwen2.5-3b-instruct/summary.md).

| Family | Baseline success | Fixed by FlightPath | Fixed by random change |
|---|---|---|---|
| control_exchange | 100% (24/24) | – | – |
| control_refund | 78% (14/18) | 0% (0/4) | 10% (1/10) |
| control_recovered_timeout | 83% (15/18) | 0% (0/3) | 80% (4/5) |
| invalid_argument | 100% (24/24) | – | – |
| repeat_loop | 100% (18/18) | – | – |
| persistent_timeout | 61% (11/18) | **100% (7/7)** | 26% (9/35) |
| stale_retrieval | 6% (1/18) | 0% (0/17) | 18% (14/80) |
| wrong_identity | 94% (17/18) | 0% (0/1) | – |
| **All** | 79% (124/156) | 22% (7/32) | 22% (28/130) |

No-change replays reproduced the original run in 150 of 150 cases and never fixed one
(0/26). Failed runs by most likely cause: nothing detected 24, timeout 7, repeated
action 1.

Findings:

1. The real model doesn't make the scripted agent's planted mistakes (wrong input, loops,
   order mix-ups), so those families pass and the per-category detector table, which is
   scored against the planted labels, is not meaningful for this run.
2. Where FlightPath proposed a change it worked every time (7/7, all timeouts). Coverage
   is the problem: stale data (17 failures) and 7 other failures had no detector fire.
3. Two harness problems surfaced on the first GPU smoke run and were fixed before this run:
   the model repeated the reply and the resolution (fixed in prompt version 2, and now
   detected as `repeated_action`), and replays drew different samples than the original
   (fixed with per-decision seeds, see above).

## What the scripted results do and don't show

- They show the method works and the controls behave: restarting with no change
  reproduces every run (100%), never fixes one (0/32), and random changes fix about one in
  five.
- They don't show how often FlightPath finds the right change for a real model's own
  mistakes. The Qwen run above does: rarely, because its mistakes are mostly ones no
  detector covers yet.
