#!/usr/bin/env bash
# The body of a GPU benchmark job, shared by the scheduler scripts. Can also be run
# directly on a machine with a GPU:  bash infra/batch/run_eval.sh
#
# Settings (environment):
#   MODEL       Hugging Face model id            (default Qwen/Qwen2.5-3B-Instruct)
#   REVISION    model commit to pin (optional; the resolved one is recorded anyway)
#   REPEATS     runs per case with different seeds (default 3)
#   SEED        base seed (default 7)
#   OUT         results folder (default benchmark-results/benchmark_v1/<model name>)
#   EXTRA_ARGS  anything else for `python -m evaluation.benchmark run`
#   REQUIRE_GPU set to 0 to allow a CPU run (smoke tests; very slow for real models)
#
# Resumable: if the job is killed, submit it again with the same OUT; finished cases are
# skipped. Results are files only: nothing listens on a network port.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
[ -f .env ] && { set -a; # shellcheck disable=SC1091
  source .env; set +a; }
VENV="${BLACKBOX_VENV:-$REPO_ROOT/.venv}"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

export HF_HOME="${HF_HOME:-$REPO_ROOT/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"   # the model was downloaded by gpu-setup
export TOKENIZERS_PARALLELISM=false

MODEL="${MODEL:-Qwen/Qwen2.5-3B-Instruct}"
NAME="$(basename "$MODEL" | tr '[:upper:]' '[:lower:]')"
OUT="${OUT:-benchmark-results/benchmark_v1/$NAME}"
REPEATS="${REPEATS:-3}"
SEED="${SEED:-7}"

echo "job $(python -c 'from evaluation.envcheck import job_id; print(job_id())') started at $(date -Iseconds)"
if [ "${REQUIRE_GPU:-1}" = 1 ]; then
  python -m evaluation.envcheck --require-gpu
else
  python -m evaluation.envcheck   # REQUIRE_GPU=0: allow a (slow) CPU run, e.g. a smoke test
fi
REV_ARGS=()
[ -n "${REVISION:-}" ] && REV_ARGS=(--revision "$REVISION")
# shellcheck disable=SC2086
python -m evaluation.benchmark run --model "hf:$MODEL" "${REV_ARGS[@]}" \
  --repeats "$REPEATS" --seed "$SEED" --out "$OUT" --resume --traces ${EXTRA_ARGS:-}
echo "done at $(date -Iseconds). Import into the app with: make benchmark-import BENCH_OUT=$OUT"
