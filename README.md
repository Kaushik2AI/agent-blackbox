# Agent BlackBox

**A flight recorder, debugger and recovery studio for AI agents.**
Inspect every step of an agent run, fork from a saved checkpoint, change one condition
safely, replay the rest in a sandbox, and compare the outcome against a ground-truth
verifier.

> **Project status: M1 of 11 (early).** What works today is the foundation: a typed
> FastAPI service with real health/readiness checks, a PostgreSQL schema under Alembic
> migrations, a Redis/RQ job queue, and a Next.js status page that shows live
> connectivity. Tracing, the trace inspector, failure analysis and replay are
> **specified but not built yet** — see the roadmap below. Nothing in this README
> describes a feature that does not run.

## Why this exists

When an agent fails, ordinary logs show an exception or a bad final answer, but not the
sequence that led there: which tool was proposed, with what arguments, what came back, how
many retries, and where recovery became impossible. Tracing alone is not new. Agent
BlackBox combines an open instrumentation contract, a **branchable** agent harness,
**controlled single-change interventions**, and **measured** recovery against objective
verifiers.

## Roadmap

| Milestone | What it delivers | Status |
|---|---|---|
| M0 | Specification: architecture, replay contract, data model, threat model, acceptance matrix | ✅ |
| M1 | Postgres + Redis + RQ, FastAPI `/healthz` `/readyz`, Alembic schema, Next.js status page, CI, SCC/no-Docker setup | ✅ |
| M2 | Sandboxed customer-support agent (LangGraph, stub model) with 3 fixtures and verifiers | ⏳ next |
| M3 | Python SDK (OTel-compatible) + idempotent, redacting event ingestion | ⏳ |
| M4 | Execution inspector: runs list, React Flow graph, timeline, event inspector | ⏳ |
| M5 | Rule-based failure detectors with evidence links and measured precision/recall | ⏳ |
| M6 | Checkpoint replay engine: isolated forks, one validated intervention | ⏳ |
| M7 | Replay Studio + original-vs-fork comparison (MVP complete) | ⏳ |
| M8 | Reproducible 30–60 case benchmark with baselines and CIs | ⏳ |
| M9 | BU SCC GPU batch evaluation (qsub) with an open-weight model | ⏳ |
| M10 | Hardening, auth, docs, demo | ⏳ |

## Quickstart

### On BU SCC (OnDemand VS Code / Desktop session — only Python + pip, no Docker/conda)

```bash
git clone https://github.com/<you>/agent-blackbox.git && cd agent-blackbox
make setup-scc     # Python venv + pip-installed Postgres/Redis/Node, random-password .env, migrations
make dev           # API + worker + web; prints the URL to open
```

### On a laptop with Docker

```bash
cp .env.example .env   # set passwords
python3.11 -m venv .venv && source .venv/bin/activate
make install && make compose-up && make dev
```

Then open the printed URL. You should see **All systems ready** with live Postgres and
Redis latencies. Stop Redis (`make services-down` or `docker compose stop redis`) and the
page turns amber with the real error within 5 seconds.

Full instructions, cleanup and troubleshooting: [`docs/developer-runbook.md`](docs/developer-runbook.md).

## Checks

```bash
make check            # ruff + mypy --strict + tsc, API tests, web tests, production build
make test-web-smoke   # with `make dev` running: browser path -> Next.js -> FastAPI -> deps
```

M1 test inventory: 10 API tests (health, readiness failure reporting without secret
leakage, migrations up/down, foreign keys, fork self-parent check, real RQ job round
trip, config parsing) and 5 web tests (4 unit, 1 live smoke).

## Architecture

```
Browser ──► Next.js (only exposed port) ──/backend/*──► FastAPI ──► PostgreSQL
                                                          └──────► Redis ◄── RQ worker
```

Design documents:

- [Architecture, lifecycle, UX spec, task graph](docs/architecture.md)
- [Replay contract: visualization vs checkpoint replay vs counterfactual](docs/replay-contract.md)
- [Data model and event contract v1.0](docs/data-model.md)
- [Threat model](docs/threat-model.md)
- [User stories → acceptance tests, MVP boundary](docs/acceptance-matrix.md)
- [ADR-001: stack, queue, SCC environment, license](docs/decisions/ADR-001-core-stack.md)
- [Original blueprint](docs/blueprint.md)

## Safety principles (binding on all later milestones)

- Metadata-only capture by default; secrets redacted before anything is stored.
- Replays create **new** executions; the original run is never modified.
- Replays use only simulated, allowlisted tools; no real email, payment or network calls.
- Success is decided by ground-truth verifiers, never by the model's own claim.
- Rule-based findings are evidence; LLM explanations are labelled *hypothesis*.
- Every number in this README will come from a runnable script.

## License

[Apache-2.0](LICENSE) — rationale in ADR-001.
