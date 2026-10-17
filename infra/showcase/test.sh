#!/usr/bin/env bash
# Serve the built static showcase (apps/web/out) the way GitHub Pages does, under its base
# path, and run the showcase browser tests against it.
#
#   PAGES_BASE_PATH=/agent-blackbox bash infra/showcase/test.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$REPO_ROOT/apps/web/out"
BASE="${PAGES_BASE_PATH:-/agent-blackbox}"
PORT="${SHOWCASE_PORT:-8471}"
[ -f "$OUT/index.html" ] || { echo "No static build in $OUT. Run: make showcase" >&2; exit 1; }

SITE="$(mktemp -d)"
mkdir -p "$SITE$(dirname "$BASE")"
ln -s "$OUT" "$SITE$BASE"
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SITE" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true; rm -rf "$SITE"' EXIT
for _ in $(seq 1 50); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT$BASE/" 2>/dev/null && break
  sleep 0.2
done

cd "$REPO_ROOT/apps/web"
E2E_SHOWCASE=1 E2E_BASE_URL="http://127.0.0.1:$PORT$BASE/" npx playwright test e2e/showcase.spec.ts
