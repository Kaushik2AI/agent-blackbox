# GPU batch jobs

Run the FlightPath benchmark with a real open-weight model on a GPU, as a scheduler job.

| File | Purpose |
|---|---|
| `gpu_setup.sh` | Once, with internet: CUDA PyTorch + transformers into the project venv, model download into `.cache/huggingface` (`make gpu-setup`, `MODEL=...` to choose) |
| `run_eval.sh` | The job body: environment check, then `python -m evaluation.benchmark run --model hf:$MODEL --resume --traces` |
| `sge_eval.sh` | Grid Engine wrapper (`qsub`) |
| `slurm_eval.sh` | Slurm wrapper (`sbatch`) |

```bash
make gpu-setup
qsub infra/batch/sge_eval.sh                                   # Grid Engine
sbatch infra/batch/slurm_eval.sh                               # Slurm
qsub -v MODEL=Qwen/Qwen2.5-7B-Instruct,REPEATS=5 infra/batch/sge_eval.sh
tail -f benchmark-results/logs/*.log
make benchmark-import BENCH_OUT=benchmark-results/benchmark_v1/qwen2.5-3b-instruct
```

GPU request syntax is different on every cluster (`-l gpus=1`, `-l gpu=1`, a GPU queue,
`--gres=gpu:1`, a partition). Edit the resource lines at the top of the wrapper for yours.
If your cluster uses environment modules, pass them: `qsub -v MODULES="python3/3.12 cuda/12.6" ...`.

Jobs run offline (`HF_HUB_OFFLINE=1`) because many GPU nodes have no internet; that is why
`gpu-setup` downloads the model first. Results are files only; nothing listens on a port.

Settings (environment variables): `MODEL`, `REVISION`, `REPEATS` (default 3), `SEED`,
`OUT`, `EXTRA_ARGS` (e.g. `--split heldout --draws 3`), `REQUIRE_GPU=0` for a CPU smoke test.

Quick smoke test without a GPU (slow, small model):

```bash
MODEL=Qwen/Qwen2.5-0.5B-Instruct REQUIRE_GPU=0 EXTRA_ARGS="--limit 2 --draws 1" make gpu-benchmark
```
