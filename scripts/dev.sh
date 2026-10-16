#!/usr/bin/env bash
# Runs the whole dev stack in one terminal: services (if managed locally), migrations,
# FastAPI, the RQ worker and Next.js. Ctrl+C stops the app processes; Postgres/Redis keep
# running until `make services-down` (or the end of your OnDemand session).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
[ -f .env ] || { echo "No .env. SCC: bash infra/scc/setup_scc.sh   Docker: cp .env.example .env" >&2; exit 1; }
set -a; # shellcheck disable=SC1091
source .env; set +a

VENV="${BLACKBOX_VENV:-$REPO_ROOT/.venv}"
[ -d "$VENV/bin" ] && export PATH="$VENV/bin:$PATH"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
export API_INTERNAL_URL="${API_INTERNAL_URL:-http://127.0.0.1:$API_PORT}"
export WEB_PORT
export NEXT_TELEMETRY_DISABLED=1

# Local (no-Docker) services are managed by services.sh; Docker users run compose instead.
if [ -d "${BLACKBOX_DATA_DIR:-$REPO_ROOT/.local-data}/postgres" ]; then
  bash infra/scc/services.sh start
fi

(cd apps/api && python -m alembic upgrade head)

pids=()
# npx/uvicorn --reload spawn children (e.g. next-server); kill whole trees so nothing
# keeps holding the ports after Ctrl+C.
kill_tree() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null || true
}
cleanup() {
  trap - EXIT INT TERM
  echo; echo "Stopping app processes..."
  for pid in "${pids[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd apps/api && exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload) &
pids+=($!)
(cd apps/api && exec python -m rq.cli worker --url "$REDIS_URL" "${RQ_QUEUE_NAME:-blackbox-default}") &
pids+=($!)
# Real AI for the live demo (Qwen on this node), if `make qwen-setup` was run.
QWEN_LINE="Live AI: off (scripted agent only; run 'make qwen-setup' to add Qwen)"
if [ "${QWEN_LOCAL:-0}" = 1 ]; then
  QWEN_LOG="${BLACKBOX_DATA_DIR:-$REPO_ROOT/.local-data}/qwen.log"
  if curl -fsS "http://127.0.0.1:${QWEN_PORT}/health" >/dev/null 2>&1; then
    QWEN_LINE="Live AI: Qwen already running on port $QWEN_PORT"
  else
    # If the server dies (bad model id, out of memory) keep the rest of the stack up.
    (python infra/scc/qwen_server.py; echo "Qwen server stopped"; exec sleep infinity) \
      >"$QWEN_LOG" 2>&1 &
    pids+=($!)
    QWEN_LINE="Live AI: Qwen loading in the background (1-2 min; log: $QWEN_LOG)"
  fi
elif [ -n "${LLM_API_KEY:-}" ]; then
  QWEN_LINE="Live AI: ${LLM_LABEL:-$LLM_MODEL} via $LLM_BASE_URL"
fi
# ---- web: direct access (Desktop/Firefox, laptop) vs. SCC OnDemand VS Code proxy ----
# The VS Code proxy URL looks like https://<ondemand>/rnode/<host>/<vscode-port>/proxy/<web-port>/
# and strips that prefix before forwarding, so the app must emit prefixed asset/API URLs.
# The VS Code (code-server) port is detected from its process; override with VSCODE_PORT=...
# or disable with NO_VSCODE_PROXY=1.
if [ -z "${VSCODE_PORT:-}" ] && [ "${NO_VSCODE_PROXY:-0}" != 1 ]; then
  VSCODE_PORT="$(ps -u "$(id -u)" -o args= 2>/dev/null | grep -E 'code-server' \
    | grep -oE -- '--bind-addr[= ][^ ]*:[0-9]+' | grep -oE '[0-9]+$' | head -1 || true)"
fi
if [ -n "${VSCODE_PORT:-}" ]; then
  export PUBLIC_PATH_PREFIX="/rnode/$(hostname -s)/$VSCODE_PORT/proxy/$WEB_PORT"
  # Behind the proxy the dev server's hot-reload socket is unreliable, so serve a
  # production build instead (to see frontend changes: Ctrl+C and `make dev` again).
  echo "Building web app for the VS Code proxy (prefix $PUBLIC_PATH_PREFIX)..."
  (cd apps/web && npx next build --webpack >/dev/null) \
    || { echo "web build failed; run 'make build-web' to see why" >&2; exit 1; }
  (cd apps/web && exec npx next start --hostname 127.0.0.1 --port "$WEB_PORT") &
  WEB_URL="https://<same host as your VS Code tab>$PUBLIC_PATH_PREFIX/"
else
  (cd apps/web && exec npx next dev --webpack --hostname 127.0.0.1 --port "$WEB_PORT") &
  WEB_URL="http://127.0.0.1:$WEB_PORT"
fi
pids+=($!)

cat <<EOF

  Agent BlackBox dev stack
  ------------------------
  Web UI : $WEB_URL
  API    : http://127.0.0.1:$API_PORT/docs  (from this node only)
  $QWEN_LINE
  Press Ctrl+C to stop.

EOF
wait -n
