#!/usr/bin/env bash
# One-time setup for the live demo's real AI on this machine: installs PyTorch + transformers into
# the project venv, downloads a Qwen model into the repo (project space), points .env at
# the local Qwen server and runs a one-question self-test.
#
#   make qwen-setup                                   # model chosen automatically
#   QWEN_MODEL=Qwen/Qwen2.5-3B-Instruct make qwen-setup   # or pick one
#
# Afterwards `make dev` starts the Qwen server together with everything else.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

ENV_FILE="$REPO_ROOT/.env"
[ -f "$ENV_FILE" ] || die "No .env yet. Run 'make setup' first."
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a
VENV="${BLACKBOX_VENV:-$REPO_ROOT/.venv}"
PY="$VENV/bin/python"
[ -x "$PY" ] || die "venv not found at $VENV. Run 'make setup' first."

set_env() {  # set_env KEY VALUE  (replace the line or append it)
  local key=$1 value=$2
  if grep -q "^$key=" "$ENV_FILE"; then
    "$PY" - "$ENV_FILE" "$key" "$value" <<'PY'
import sys
path, key, value = sys.argv[1:]
lines = open(path).read().splitlines()
lines = [f"{key}={value}" if l.startswith(key + "=") else l for l in lines]
open(path, "w").write("\n".join(lines) + "\n")
PY
  else
    echo "$key=$value" >> "$ENV_FILE"
  fi
}

# Everything big stays inside the repo (project space), not in $HOME (10 GB quota).
export PIP_CACHE_DIR="$REPO_ROOT/.cache/pip"
HF_HOME_DIR="$REPO_ROOT/.cache/huggingface"
mkdir -p "$PIP_CACHE_DIR" "$HF_HOME_DIR"

# PyTorch build: CPU-only (small) on a node without a GPU; on a GPU node, a CUDA 12.6
# build, which runs on most current drivers (the default PyPI build needs CUDA 13 drivers).
# Override with TORCH_INDEX_URL=... (e.g. https://download.pytorch.org/whl/cu128).
if [ -z "${TORCH_INDEX_URL:-}" ]; then
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126
    say "GPU found: installing PyTorch for CUDA 12.6 (about 3 GB, a few minutes)"
  else
    TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
    say "No GPU on this node: installing CPU PyTorch (about 300 MB)"
    echo "   (To use a GPU later: start a GPU session and run 'make qwen-setup' again.)"
  fi
fi
"$PY" -m pip install --upgrade --index-url "$TORCH_INDEX_URL" 'torch>=2.6' >/dev/null \
  || die "PyTorch install failed (re-run to see the error)"
say "Installing transformers"
"$PY" -m pip install --upgrade 'transformers>=4.56' 'accelerate>=1.0' 'huggingface_hub>=0.34' \
  >/dev/null || die "pip install failed (re-run to see the error)"
"$PY" - <<'PY'
import torch
gpu = torch.cuda.is_available()
print(f"   torch {torch.__version__}, GPU: {torch.cuda.get_device_name(0) if gpu else 'none (CPU mode)'}")
PY

say "Writing the model settings into .env"
QWEN_PORT="${QWEN_PORT:-$(( ${WEB_PORT:-8003} + 1 ))}"
if [ "${LLM_BASE_URL:-}" != "http://127.0.0.1:$QWEN_PORT/v1" ] || [ -z "${LLM_API_KEY:-}" ]; then
  LLM_API_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi
set_env QWEN_LOCAL 1
set_env QWEN_PORT "$QWEN_PORT"
set_env QWEN_MODEL "${QWEN_MODEL:-auto}"
set_env HF_HOME "$HF_HOME_DIR"
# Also pin the hub cache: a leftover HF_HUB_CACHE / TRANSFORMERS_CACHE in ~/.bashrc (e.g.
# a class's shared folder) would otherwise override HF_HOME and point at a folder you
# cannot write to.
set_env HF_HUB_CACHE "$HF_HOME_DIR/hub"
set_env TRANSFORMERS_CACHE "$HF_HOME_DIR/hub"
set_env LLM_BASE_URL "http://127.0.0.1:$QWEN_PORT/v1"
set_env LLM_API_KEY "$LLM_API_KEY"
set_env LLM_MODEL local-qwen
set_env LLM_LABEL Qwen  # the running server reports the full name; no spaces (.env is read by bash and make)
set_env LLM_TIMEOUT_S 240
set_env LLM_MAX_TOKENS 220
chmod 600 "$ENV_FILE"
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a

say "Downloading the model and running a one-question test (first time: a few minutes)"
LOG="${BLACKBOX_DATA_DIR:-$REPO_ROOT/.local-data}/qwen.log"
mkdir -p "$(dirname "$LOG")"
if curl -fsS "http://127.0.0.1:$QWEN_PORT/health" >/dev/null 2>&1; then
  die "Something already runs on port $QWEN_PORT (is 'make dev' running?). Stop it and re-run."
fi
"$PY" infra/local/qwen_server.py >"$LOG" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

status=""
for _ in $(seq 1 900); do  # up to 30 min for the first download on a slow link
  status="$(curl -fsS "http://127.0.0.1:$QWEN_PORT/health" 2>/dev/null \
    | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["status"])' 2>/dev/null || true)"
  [ "$status" = ready ] || [ "$status" = error ] && break
  kill -0 $SERVER 2>/dev/null || break
  sleep 2
done
if [ "$status" != ready ]; then
  tail -20 "$LOG" >&2 || true
  die "Qwen did not start (log: $LOG)"
fi
curl -fsS "http://127.0.0.1:$QWEN_PORT/health"; echo

"$PY" - <<'PY'
import os, time, httpx
url = os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
t = time.time()
r = httpx.post(url, timeout=300, headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
    json={"messages": [{"role": "system", "content": "Answer with one JSON object."},
                       {"role": "user", "content": 'Say hello as {"reply": "..."}'}],
          "temperature": 0, "max_tokens": 40})
r.raise_for_status()
print(f"   Qwen answered in {time.time() - t:.1f}s: {r.json()['choices'][0]['message']['content']!r}")
PY

say "Done. Run 'make dev' and pick 'Live AI' on the home page."
