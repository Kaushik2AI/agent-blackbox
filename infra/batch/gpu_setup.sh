#!/usr/bin/env bash
# One-time: install PyTorch + transformers into the project venv and download the model,
# so batch jobs never need the internet (many GPU nodes have none).
#
#   make gpu-setup                                    # Qwen2.5-3B-Instruct
#   MODEL=Qwen/Qwen2.5-7B-Instruct make gpu-setup
#
# Run it on a machine with internet access (a login node is fine: nothing heavy runs).

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f .env ] && { set -a; # shellcheck disable=SC1091
  source .env; set +a; }
VENV="${BLACKBOX_VENV:-$REPO_ROOT/.venv}"
PY="$VENV/bin/python"
[ -x "$PY" ] || die "venv not found at $VENV. Run 'make setup' first."
MODEL="${MODEL:-Qwen/Qwen2.5-3B-Instruct}"

# Keep big downloads in the repo's folder (project storage), not in $HOME.
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$REPO_ROOT/.cache/pip}"
export HF_HOME="${HF_HOME:-$REPO_ROOT/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
mkdir -p "$PIP_CACHE_DIR" "$HF_HUB_CACHE"

# The CUDA 12.6 build runs on most current drivers; override with TORCH_INDEX_URL.
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
say "Installing PyTorch from $TORCH_INDEX_URL (about 3 GB)"
"$PY" -m pip install --upgrade --index-url "$TORCH_INDEX_URL" 'torch>=2.6' >/dev/null \
  || die "PyTorch install failed (re-run to see the error)"
say "Installing transformers"
"$PY" -m pip install --upgrade -e "packages/evaluation[gpu]" >/dev/null || die "pip install failed"

say "Downloading $MODEL into $HF_HUB_CACHE"
"$PY" -m evaluation.prefetch "$MODEL"

say "Done. Submit a job with: qsub infra/batch/sge_eval.sh   or   sbatch infra/batch/slurm_eval.sh"
