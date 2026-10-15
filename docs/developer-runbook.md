# Developer runbook

## A. BU SCC (OnDemand) — no Docker needed

### First time

1. Open **SCC OnDemand** → start a **VS Code** (or **Desktop**) interactive session.
   A normal CPU session is enough (2–4 cores, a few hours). No GPU until M9.
2. In that session's terminal (it runs on a compute node, not a login node):

   ```bash
   # Optional: if your home quota is small (10 GB), put the repo under project space.
   cd /projectnb/<your-project>/$USER            # or stay in $HOME
   module load python3/3.12.4                     # any 3.11.x or 3.12.x; see `module avail python3`

   git clone https://github.com/<you>/agent-blackbox.git
   cd agent-blackbox
   make setup-scc        # ~5-10 min the first time
   ```

   `make setup-scc` uses **only Python + pip** (no conda, Docker or root). It creates
   `.venv/`, pip-installs the API plus PostgreSQL 16, Redis 6.2 and Node 22 (they ship as
   Python wheels: `pgserver`, `redislite`, `nodejs-wheel`), writes `.env` with random
   passwords and per-user ports, initialises the database and applies migrations.
   Re-running it is safe. About 1 GB on disk.

   If it says it needs Python 3.11 or 3.12, run `module avail python3`, load a 3.11.x or
   3.12.x version, and re-run `make setup-scc`.

### Every session

```bash
cd agent-blackbox
make dev          # starts Postgres+Redis if needed, migrates, runs API + worker + web
```

It prints the web URL, e.g. `http://127.0.0.1:43213` (your port comes from `.env`).

### Opening the web UI

- **Desktop session (most reliable):** open Firefox inside the OnDemand Desktop and go to
  the printed `http://127.0.0.1:<WEB_PORT>` URL.
- **VS Code session:** `make dev` detects the VS Code server and builds the web app for
  its proxy. Open the URL it prints, replacing the host with the one in your VS Code
  tab, e.g. `https://scc-ondemand2.bu.edu/rnode/scc-pe6/63555/proxy/58253/`
  (`scc-pe6` = your node, `63555` = VS Code's port from your VS Code tab URL, `58253` =
  `WEB_PORT`). If detection fails, run `VSCODE_PORT=63555 make dev` with the number from
  your VS Code tab URL. In this mode the web app is a production build: after changing
  frontend code, stop with Ctrl+C and run `make dev` again.
  Only the web port is needed — the API is reached through the web server's `/backend`
  proxy.
- If neither works for you, everything except viewing the page can still be checked from
  the terminal: `curl http://127.0.0.1:$WEB_PORT/backend/readyz`.

### Tests and checks

```bash
make test             # API unit + integration (real Postgres/Redis) + web unit tests
make lint             # ruff, mypy --strict, tsc
make build-web        # production Next.js build
make check            # all of the above
# with `make dev` running in another terminal:
make test-web-smoke   # browser path -> Next.js proxy -> FastAPI -> Postgres/Redis
```

### Stopping / cleanup

| Command | Effect |
|---|---|
| `Ctrl+C` in the `make dev` terminal | Stops API, worker, web (Postgres/Redis keep running) |
| `make services-down` | Stops Postgres and Redis. **Data is kept.** |
| `make services-status` | Shows whether they're running |
| `make clean` | Deletes build/test caches only |
| `make reset-data` | **Deletes** the local database and Redis data (asks first) |

Ending the OnDemand session kills all processes; data stays on disk. Next session:
`make dev` again. If Postgres refuses to start after a session was killed, `make dev`
already clears the stale pid file; if it still fails, read `.local-data/postgres.log`.

## B. Laptop with Docker

```bash
cp .env.example .env          # edit the two passwords (and the URLs to match)
python3.11 -m venv .venv && source .venv/bin/activate
make install                  # pip + npm ci (Node 22 required)
make compose-up               # Postgres + Redis in Docker
make dev
```

Open http://127.0.0.1:3000. `make compose-down` stops the containers.

## Getting code onto GitHub

```bash
git init && git add . && git commit -m "M0+M1: spec, infra, health slice"
git branch -M main
git remote add origin https://github.com/<you>/agent-blackbox.git
git push -u origin main
```

`.env`, `.venv/`, `.local-data/` and `node_modules/` are git-ignored.

## Using a named venv (e.g. `agent-blackbox`) outside the repo

```bash
BLACKBOX_VENV=/projectnb/<project>/<you>/venvs/agent-blackbox make setup-scc
source /projectnb/<project>/<you>/venvs/agent-blackbox/bin/activate   # prompt shows (agent-blackbox)
```

The path is saved in `.env` (`BLACKBOX_VENV=...`), so every later `make` command and
`make dev` use that venv automatically. Database data in `.local-data/` is unaffected.

## Recording runs and browser tests (M3/M4)

```bash
make dev                      # terminal 1
make seed-demo                # terminal 2: record all fixtures through the SDK -> ingest API
make e2e-install              # once: download headless Chromium into .cache/ (~150 MB)
make test-e2e                 # Playwright: open the failing run, click the failing span
```

`make test-e2e` targets `http://127.0.0.1:$WEB_PORT` on the same node, so it works in both
direct and VS Code proxy modes. If Chromium will not start on SCC, set
`E2E_CHROMIUM_PATH=/path/to/chrome` to use another Chromium build.

## Findings and replay (M5–M7)

- Findings are computed automatically when a finished run is ingested; see them at the top
  of the run page. `make eval-detectors` prints precision/recall on the labelled fixtures.
- Replays need the RQ worker, which `make dev` starts. Runs recorded **metadata-only**
  cannot be replayed (their checkpoint state was never captured); `make seed-demo` records
  with content capture so its runs are replayable.
- Checkpoint states are stored in `.local-data/artifacts/` (override with
  `BLACKBOX_ARTIFACT_DIR`). Deleting that folder makes old runs non-replayable, nothing else.
- API: `GET /api/v1/executions/{id}/checkpoints`, `POST /api/v1/replays`,
  `GET /api/v1/replays/{job}`, `GET /api/v1/replays/{job}/comparison`. Example:

  ```bash
  curl -s -X POST http://127.0.0.1:$API_PORT/api/v1/replays -H 'content-type: application/json' -d '{
    "source_execution_id": "<run id>", "checkpoint_id": "<checkpoint before call #1>",
    "intervention": {"type": "replace_tool_argument", "target_span_id": "<that call span>",
                     "field": "sku", "value": "SKU-RED-004", "remove_fields": ["product_name"]}}'
  ```
