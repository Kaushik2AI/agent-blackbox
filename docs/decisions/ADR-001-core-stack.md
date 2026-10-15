# ADR-001: Core stack, job queue, dev environment and license

- **Status:** Accepted (M0/M1, 2026-10-14)
- **Source of truth:** [`docs/blueprint.md`](../blueprint.md) §3, §12

## Context

Agent BlackBox needs a typed Python API close to agent frameworks, a durable relational
store for runs/spans/events/lineage, a background queue so replay never blocks HTTP, and a
graph-heavy web UI. The primary developer works on **BU SCC through OnDemand**, where there
is **no Docker and no root**, compute nodes are **shared with other users**, and sessions
end when the scheduler allocation ends.

## Decisions

| Area | Choice (pinned) | Why | Rejected |
|---|---|---|---|
| API | FastAPI 0.143.1, Pydantic 2.14 (via pydantic-settings 2.16) | Typed contracts, OpenAPI for free, same language as agent harness | Django (heavier ORM coupling), Flask (no typed validation) |
| DB | PostgreSQL 16, SQLAlchemy 2.1.4, Alembic 1.20.0, psycopg 3.3.6 | FK/lineage integrity, JSONB for attributes later, real migrations | SQLite (no concurrent worker writes, weaker JSON/indexing) |
| Queue | **Redis (6.2 local wheel, 7 in Docker/CI) + RQ 2.12.0** | Plain functions as jobs; `SimpleWorker` runs in-process in tests; one dependency | Dramatiq (more middleware config, nothing we need yet), Celery (heavy) |
| Web | Next.js 16.4.1, React 19.3.1, TypeScript 5.9.3, Tailwind 4.3.3 | App router, server-side proxy via rewrites, ecosystem for React Flow (M4) | Vite SPA (would need a separate proxy for SCC) |
| Frontend tests | Vitest 5.0.4 (Playwright added in M4) | Fast unit + live smoke tests | Jest (slower ESM story) |
| Python tooling | pytest 9.1.1, ruff 0.17.0, mypy 2.4.0 (strict) | Lint + format + types in one gate | — |
| Agent harness | LangGraph with persistent checkpointer (from M2) | Explicit state + checkpoints for replay | Hand-rolled state machine |

Versions were resolved together on 2026-10-14 and installed cleanly on Python 3.11–3.13
and Node 22. They are **exact pins**; upgrades are deliberate and go through CI.

### Dev environment: Docker optional, plain Python venv first-class

- `infra/scc/setup_scc.sh` builds a project-local **Python venv** and pip-installs
  PostgreSQL 16.2 (`pgserver` wheel), Redis 6.2 (`redislite` wheel) and Node 22
  (`nodejs-wheel`) into it — no conda, root or Docker required. (Conda was the first
  approach; dropped at the developer's request to keep one toolchain: Python + pip.)
- `infra/scc/services.sh` runs Postgres/Redis **on 127.0.0.1 only, password-protected**
  (random passwords in a `0600` `.env`), on **per-user ports** derived from the UID so two
  users on one shared compute node do not collide.
- `docker-compose.yml` remains for laptops; it only runs Postgres/Redis. The app itself
  always runs natively via `make dev`, so both paths exercise the same code.
- The browser reaches only the Next.js port; `/backend/*` is proxied server-side to
  FastAPI. One port to forward is what makes OnDemand access practical.

### License: Apache-2.0

Permissive (usable by employers/recruiters reviewing a portfolio and by other researchers),
with an explicit patent grant and contribution terms that MIT lacks. Compatible with every
dependency above (MIT/BSD/Apache).

## Consequences

- SCC GPU work (M9) stays a separate `qsub` batch path; the web stack never depends on a
  GPU allocation.
- Postgres/Redis processes die with the OnDemand session; data persists on disk.
  `make dev` restarts them. Documented in `docs/developer-runbook.md`.
- Choosing RQ means jobs must be importable functions with serialisable args; the replay
  worker (M6) is designed around that.

### Addendum (2026-10-14): Webpack + WASM SWC instead of Turbopack

BU SCC compute nodes ship glibc older than 2.30, which Next.js 16's native SWC binary
(`@next/swc-linux-x64-gnu`) requires; Turbopack cannot run without it. The web app
therefore runs `next dev --webpack` / `next build --webpack` and pins
`@next/swc-wasm-nodejs` so the WASM compiler is installed by `npm ci` (instead of being
downloaded into `$HOME` at runtime). All other native modules (Tailwind oxide,
lightningcss) need only glibc 2.14–2.16. Cost: slower dev rebuilds; acceptable for M1–M7.
