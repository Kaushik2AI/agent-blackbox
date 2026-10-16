# evaluation: the FlightPath benchmark

```bash
python -m evaluation.dataset --check                  # committed cases match the generator
python -m evaluation.benchmark run --out DIR          # 52 cases x 4 arms, CPU, ~10 s
python -m evaluation.benchmark run --model hf:Qwen/Qwen2.5-3B-Instruct --repeats 3 --resume --traces --out DIR
python -m evaluation.benchmark report --out DIR       # recompute summary + charts from runs.jsonl
python -m evaluation.envcheck --require-gpu           # before a GPU run
```

| Module | What it does |
|---|---|
| `dataset.py` | Generates the versioned cases (8 families, held-out split) from a fixed seed |
| `repair.py` | FlightPath's suggested change (from what the run recorded) and the random-change baseline |
| `arms.py` | Runs a case through baseline, no-change replay, repair and random arms with the real SDK |
| `metrics.py`, `stats.py` | Rates with Wilson intervals and explicit denominators, detector precision/recall |
| `report.py` | runs.jsonl, runs.csv, summary.json, summary.md, SVG charts |
| `hf.py` | In-process transformers model with the agent's prompt and JSON action format (GPU or CPU) |
| `envcheck.py`, `prefetch.py` | Environment checks and model download for batch jobs |

Method and definitions: [docs/benchmark.md](../../docs/benchmark.md).
