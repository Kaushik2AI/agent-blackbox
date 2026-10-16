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
| stale_retrieval | 6 | A month-old cached record says "out of stock"; refunds instead of exchanging | none (no detector exists) |
| wrong_identity | 6 | Looks up one order, closes the ticket on another customer's | order mix-up |

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
- `--repeats N` runs every case N times with different seeds; the seed of every model
  decision is derived from the run's seed, so a rerun reproduces it where the hardware
  allows.
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

What is verified: the full GPU code path ran end to end on a CPU with a small model (job
script, environment check, model loading, generation, resume, import). What is not yet
verified: a real GPU allocation and real-model numbers.

## What the scripted results do and don't show

- They show the method works and the controls behave: restarting with no change
  reproduces every run (100%), never fixes one (0/32), and random changes fix about one in
  five.
- They don't show how often FlightPath finds the right change for a real model's own
  mistakes. That is what the GPU runs are for.
