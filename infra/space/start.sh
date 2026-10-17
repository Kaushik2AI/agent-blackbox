#!/usr/bin/env bash
# Container entrypoint for the public demo (Hugging Face Space or any Docker host).
#
# Every start is a clean slate: new random passwords, a new database, the demo runs
# recorded again and the benchmark results imported. The app runs in public mode
# (PUBLIC_DEMO=true): ingesting runs needs a token nobody outside the container has, and
# Live AI runs are rate limited per visitor and per day.
#
# Settings (Space "Variables and secrets", all optional):
#   LIVE_AI=0                 turn the local Qwen model off (scripted agent only)
#   QWEN_MODEL=...            another model id (downloaded at start if not baked in)
#   LLM_BASE_URL/LLM_API_KEY/LLM_MODEL/LLM_LABEL
#                             use a hosted OpenAI-compatible API instead of local Qwen

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
DATA="${BLACKBOX_DATA_DIR:-$HOME/data}"
WEB_PORT="${PORT:-7860}"
API_PORT=8000
PG_PORT=5433
REDIS_PORT=6380
QWEN_PORT=8001

say() { printf '\n==> %s\n' "$*"; }
rand() { python -c 'import secrets; print(secrets.token_urlsafe(24))'; }

rm -rf "$DATA"
mkdir -p "$DATA"
chmod 700 "$DATA"
PG_PASSWORD="$(rand)"
REDIS_PASSWORD="$(rand)"

LIVE="${LIVE_AI:-1}"
if [ "$LIVE" = 1 ] && [ -z "${LLM_API_KEY:-}" ] && python -c 'import torch, transformers' 2>/dev/null; then
  MODE=local
elif [ -n "${LLM_API_KEY:-}" ] && [ "$LIVE" = 1 ]; then
  MODE=hosted
else
  MODE=off
fi

umask 077
cat > .env <<EOF
# Written by infra/space/start.sh at $(date -Iseconds); recreated on every start.
ENVIRONMENT=production
BLACKBOX_DATA_DIR=$DATA
BLACKBOX_VENV=${BLACKBOX_VENV:-$REPO_ROOT/.venv}
BLACKBOX_ARTIFACT_DIR=$DATA/artifacts
PG_PORT=$PG_PORT
PG_USER=blackbox
PG_PASSWORD=$PG_PASSWORD
PG_DATABASE=blackbox
REDIS_PORT=$REDIS_PORT
REDIS_PASSWORD=$REDIS_PASSWORD
API_PORT=$API_PORT
WEB_PORT=$WEB_PORT
DATABASE_URL=postgresql+psycopg://blackbox:$PG_PASSWORD@127.0.0.1:$PG_PORT/blackbox
REDIS_URL=redis://:$REDIS_PASSWORD@127.0.0.1:$REDIS_PORT/0
API_INTERNAL_URL=http://127.0.0.1:$API_PORT
CORS_ORIGINS=http://127.0.0.1:$WEB_PORT
PUBLIC_DEMO=true
INGEST_TOKEN=$(rand)
EOF
if [ "$MODE" = local ]; then
  cat >> .env <<EOF
QWEN_LOCAL=1
QWEN_PORT=$QWEN_PORT
QWEN_MODEL=${QWEN_MODEL:-auto}
LLM_BASE_URL=http://127.0.0.1:$QWEN_PORT/v1
LLM_API_KEY=$(rand)
LLM_MODEL=local-qwen
LLM_LABEL=Qwen
LLM_TIMEOUT_S=240
LLM_MAX_TOKENS=220
EOF
fi
umask 022
set -a # shellcheck disable=SC1091
source .env
set +a

say "Starting Postgres and Redis"
PWFILE="$(mktemp)"
printf '%s\n' "$PG_PASSWORD" > "$PWFILE"
initdb -D "$DATA/postgres" -U "$PG_USER" --auth=scram-sha-256 --pwfile="$PWFILE" \
  --encoding=UTF8 --no-locale >/dev/null
rm -f "$PWFILE"
bash infra/local/services.sh start
PGPASSWORD="$PG_PASSWORD" createdb -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" "$PG_DATABASE"
(cd apps/api && python -m alembic upgrade head)

pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  bash infra/local/services.sh stop >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

say "Starting API and replay worker"
(cd apps/api && exec python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
  --no-access-log) &
pids+=($!)
(cd apps/api && exec python -m rq.cli worker --url "$REDIS_URL" "${RQ_QUEUE_NAME:-blackbox-default}") &
pids+=($!)
if [ "$MODE" = local ]; then
  say "Loading Qwen in the background (${QWEN_MODEL}); Live AI turns on when it is ready"
  # If the model server dies (e.g. out of memory) the rest of the app stays up; the home
  # page then shows Live AI as unavailable.
  (python infra/local/qwen_server.py >"$DATA/qwen.log" 2>&1
   echo "Qwen server stopped (see $DATA/qwen.log)"; exec sleep infinity) &
  pids+=($!)
fi

for _ in $(seq 1 120); do
  curl -fsS "http://127.0.0.1:$API_PORT/readyz" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$API_PORT/readyz" >/dev/null || { echo "API did not become ready" >&2; exit 1; }

say "Recording the demo runs and importing the benchmark"
python -m blackbox_sdk.seed_demo --capture-content >/dev/null
# One run recorded the privacy-default way (metadata only): it can be inspected but not
# re-run, which the app explains.
python -m blackbox_sdk.seed_demo --fixtures invalid_inventory_argument >/dev/null
python -m evaluation.benchmark run --out "$DATA/bench/scripted" --traces >/dev/null
(cd apps/api && python -m app.eval_import "$DATA/bench/scripted")
for folder in benchmark-results/benchmark_v1/*/; do
  case "$folder" in */scripted/) continue ;; esac
  [ -f "$folder/runs.jsonl" ] && (cd apps/api && python -m app.eval_import "$REPO_ROOT/$folder")
done

say "Starting the web app on port $WEB_PORT"
(cd apps/web && exec npx next start --hostname 0.0.0.0 --port "$WEB_PORT") &
pids+=($!)

cat <<EOF

  FlightPath is up on port $WEB_PORT.
  Live AI: $MODE
EOF
# If any process dies, exit so the platform restarts the container.
wait -n
