# Developer runbook

## A. Any Linux machine, no Docker (laptop, workstation, shared server)

### First time

```bash
git clone https://github.com/Kaushik2AI/agent-blackbox.git && cd agent-blackbox
make setup        # ~5-10 min the first time; safe to re-run
```

`make setup` uses **only Python + pip** (no conda, Docker or root). It creates a venv,
pip-installs the API plus PostgreSQL 16, Redis 6.2 and Node 22 (they ship as Python
wheels: `pgserver`, `redislite`, `nodejs-wheel`), installs the web app, writes `.env` with
random passwords and per-user ports (so several users on one server don't collide),
initialises the database and applies migrations. About 1 GB on disk.

If it says it needs Python 3.11 or 3.12, install one (on clusters with environment
modules: `module avail python3`, then `module load python3/3.12...`) and re-run.

**Keep big files off a small home directory.** Clone into project storage if your
`$HOME` quota is small. The venv can live elsewhere too:

```bash
BLACKBOX_VENV=/path/to/venvs/flightpath make setup
source /path/to/venvs/flightpath/bin/activate
```

The path is saved in `.env`, so every later `make` command uses that venv.
Model downloads and pip caches go to `.cache/` inside the repo. If an old setting in your
shell points Hugging Face somewhere you can't write (`HF_HOME`, `HF_HUB_CACHE`), the
values in `.env` written by `make qwen-setup` override it for FlightPath.

### Every session

```bash
cd agent-blackbox
make dev          # starts Postgres+Redis if needed, migrates, runs API + worker + web
```

It prints the web URL, e.g. `http://127.0.0.1:43213` (your port comes from `.env`).

### Opening the web UI on a remote machine

Only the web port has to reach your browser (the API sits behind the web server's
`/backend` proxy).

- **SSH:** `ssh -L 3000:127.0.0.1:<WEB_PORT> you@server`, then open `http://localhost:3000`.
- **Remote desktop on the server:** open the printed URL in its browser.
- **Browser-based VS Code (code-server) with a port proxy:** `make dev` detects the IDE's
  port from its process and builds the app for the proxy path. Open the URL it prints,
  using the host from your IDE tab. If your gateway's proxy path is different, set
  `PROXY_PATH_TEMPLATE` (default `/rnode/{host}/{ide_port}/proxy/{web_port}`); if
  detection fails, run `VSCODE_PORT=<port from your IDE tab URL> make dev`. In this mode
  the web app is a production build: after changing frontend code, restart `make dev`.

### Live AI (real Qwen model)

```bash
make qwen-setup      # once per venv; re-run on a GPU machine to switch to GPU PyTorch
make dev             # starts infra/local/qwen_server.py too; log: .local-data/qwen.log
make qwen-status     # {"status": "loading" | "ready" | "error", "model": ..., "device": ...}
```

- `qwen_server.py` is a small OpenAI-compatible server (transformers) bound to 127.0.0.1
  with a random bearer token from `.env`. The app treats it like any hosted API.
- While the model loads, the home page shows "Warming up" and enables **Live AI** when it
  is ready. If the server is down, Live AI is disabled; the scripted agent still works.
- Runs record the real model id (e.g. `llm:Qwen/Qwen2.5-1.5B-Instruct`). Replays of such
  a run make fresh AI decisions and are refused if a different model is loaded.
- To use a hosted API instead, set `QWEN_LOCAL=0` and `LLM_BASE_URL` / `LLM_API_KEY` /
  `LLM_MODEL` in `.env`.

### Tests and checks

```bash
make test             # agent, SDK, detectors, benchmark, API (real Postgres/Redis), web unit
make lint             # ruff, mypy --strict, tsc
make build-web        # production Next.js build
make check            # all of the above
# with `make dev` running in another terminal:
make e2e-install      # once: headless Chromium into .cache/ (~150 MB)
make test-e2e         # 7 Playwright browser tests
make test-web-smoke   # browser path -> Next.js proxy -> FastAPI -> Postgres/Redis
```

If Chromium will not start, set `E2E_CHROMIUM_PATH=/path/to/chrome`.

### Benchmark

```bash
make benchmark            # CPU, ~10 s -> benchmark-results/benchmark_v1/scripted/
make benchmark-import     # needs Postgres up (make services-up or make dev)
make gpu-setup            # GPU runs: see infra/batch/README.md
```

### Stopping / cleanup

| Command | Effect |
|---|---|
| `Ctrl+C` in the `make dev` terminal | Stops API, worker, web and the model server (Postgres/Redis keep running) |
| `make services-down` | Stops Postgres and Redis. **Data is kept.** |
| `make services-status` | Shows whether they're running |
| `make clean` | Deletes build/test caches only |
| `make reset-data` | **Deletes** the local database and Redis data (asks first) |

When a session ends, its processes die; data stays on disk. Next session: `make dev`.
If Postgres refuses to start after a killed session, `make dev` already clears the stale
pid file; if it still fails, read `.local-data/postgres.log`.

## B. Laptop with Docker

```bash
cp .env.example .env          # edit the two passwords (and the URLs to match)
python3.12 -m venv .venv && source .venv/bin/activate
make install                  # pip + npm ci (Node 22 required)
make compose-up               # Postgres + Redis in Docker
make dev
```

Open http://127.0.0.1:3000. `make compose-down` stops the containers.

## Recording runs

```bash
make seed-demo                # record every demo fixture through the SDK -> ingest API
python examples/record_your_agent.py http://127.0.0.1:$API_PORT   # a run from "your" agent
```

`make seed-demo` records with content capture, so its runs can be restarted. Runs
recorded **metadata-only** (the SDK default) cannot be restarted: their saved state was
never captured. Saved states live in `.local-data/artifacts/` (override with
`BLACKBOX_ARTIFACT_DIR`); deleting it makes old runs non-restartable, nothing else.

API reference: `http://127.0.0.1:$API_PORT/docs` (from the machine itself).
