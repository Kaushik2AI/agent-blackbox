#!/usr/bin/env bash
# Start/stop/status for the local Postgres + Redis used in development (no Docker).
#
#   bash infra/local/services.sh start | stop | status
#
# Both services listen on 127.0.0.1 only and require a password from .env, because
# a server may be shared with other users. Data lives in $BLACKBOX_DATA_DIR and
# survives the end of a login session; the processes do not, so run `start` again
# in each new session (`make dev` does this for you).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
[ -f "$ENV_FILE" ] || { echo "No .env found. Run: bash infra/local/setup.sh" >&2; exit 1; }
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a

VENV="${BLACKBOX_VENV:-$REPO_ROOT/.venv}"
[ -d "$VENV/bin" ] && export PATH="$VENV/bin:$PATH"

DATA_DIR="${BLACKBOX_DATA_DIR:-$REPO_ROOT/.local-data}"
PG_DATA="$DATA_DIR/postgres"
PG_SOCKET_DIR="$DATA_DIR/pg-socket"
REDIS_DIR="$DATA_DIR/redis"
REDIS_CONF="$REDIS_DIR/redis.conf"
REDIS_PID="$REDIS_DIR/redis.pid"

pg_running() { pg_ctl -D "$PG_DATA" status >/dev/null 2>&1; }
redis_running() { redis-cli -h 127.0.0.1 -p "$REDIS_PORT" --no-auth-warning -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG; }

start_pg() {
  [ -f "$PG_DATA/PG_VERSION" ] || { echo "Postgres not initialised. Run: bash infra/local/setup.sh" >&2; exit 1; }
  if pg_running; then echo "postgres: already running on 127.0.0.1:$PG_PORT"; return; fi
  mkdir -p "$PG_SOCKET_DIR"; chmod 700 "$PG_SOCKET_DIR"
  # A stale pid file from a killed session would block startup; pg_ctl status
  # already said it isn't running, so it's safe to remove.
  rm -f "$PG_DATA/postmaster.pid"
  pg_ctl -D "$PG_DATA" -l "$DATA_DIR/postgres.log" -w -t 30 \
    -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -k $PG_SOCKET_DIR" start >/dev/null
  echo "postgres: started on 127.0.0.1:$PG_PORT (log: $DATA_DIR/postgres.log)"
}

start_redis() {
  if redis_running; then echo "redis: already running on 127.0.0.1:$REDIS_PORT"; return; fi
  mkdir -p "$REDIS_DIR"; chmod 700 "$REDIS_DIR"
  # Password goes in a 0600 config file, not on the command line (visible in `ps`).
  ( umask 077; cat > "$REDIS_CONF" <<EOF
bind 127.0.0.1
protected-mode yes
port $REDIS_PORT
requirepass $REDIS_PASSWORD
dir $REDIS_DIR
pidfile $REDIS_PID
logfile $DATA_DIR/redis.log
daemonize yes
appendonly yes
EOF
  )
  redis-server "$REDIS_CONF"
  for _ in $(seq 1 30); do redis_running && break; sleep 0.2; done
  redis_running || { echo "redis: failed to start, see $DATA_DIR/redis.log" >&2; exit 1; }
  echo "redis: started on 127.0.0.1:$REDIS_PORT"
}

stop_all() {
  if pg_running; then pg_ctl -D "$PG_DATA" -m fast -w stop >/dev/null; echo "postgres: stopped"; else echo "postgres: not running"; fi
  if redis_running; then
    redis-cli -h 127.0.0.1 -p "$REDIS_PORT" --no-auth-warning -a "$REDIS_PASSWORD" shutdown >/dev/null 2>&1 || true
    echo "redis: stopped"
  else
    echo "redis: not running"
  fi
}

status() {
  if pg_running; then echo "postgres: running on 127.0.0.1:$PG_PORT"; else echo "postgres: stopped"; fi
  if redis_running; then echo "redis: running on 127.0.0.1:$REDIS_PORT"; else echo "redis: stopped"; fi
}

case "${1:-}" in
  start) start_pg; start_redis ;;
  stop) stop_all ;;
  status) status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
