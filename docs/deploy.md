# Deploying FlightPath

Two ways, depending on what you need.

| | Static showcase (GitHub Pages) | Full app (one Docker container) |
|---|---|---|
| Cost | Free | Whatever the host costs |
| What visitors can do | Browse recorded runs, diagnoses and the benchmark; play the scripted scenarios back step by step; open the pre-recorded fix for every failed run | Everything, including Live AI and re-running with your own change in Replay Studio |
| Server | None (plain files) | One container: Postgres, Redis, API, replay worker, web app, optional local Qwen |
| Updates | Automatic on every push to `main` that passes CI | Rebuild the image |

## 1. Free static showcase on GitHub Pages

The showcase is the same web app, built as static files that read a snapshot of a real
FlightPath stack instead of calling the API. Nothing in it is mocked: the GitHub Actions
workflow (`.github/workflows/pages.yml`) starts the real stack, records the demo runs,
plays every scripted scenario, applies FlightPath's suggested fix to every failed run,
freezes all of that into JSON (`infra/showcase/snapshot.py`), exports the web app with
`NEXT_PUBLIC_SHOWCASE=1` and checks the result in a browser before publishing.

**One-time setup:** on GitHub, open the repository's **Settings → Pages → Build and
deployment → Source** and choose **GitHub Actions**. After the next push to `main` (once CI
passes), the site is at `https://<your-user>.github.io/<repo>/`. To publish without a new
push: **Actions → Showcase (GitHub Pages) → Run workflow**.

What works without a server, and how:

| Feature | In the showcase |
|---|---|
| Runs list, filters, run pages, evidence, Replay Studio view | Snapshot files; filters and paging run in the browser |
| Live demo with the scripted agent | The recorded run plays back step by step |
| "Try the fix" | Opens the re-run that was recorded with exactly that change |
| Benchmark page and CSV download | Snapshot files |
| Live AI, re-running with your own change | Not available; the page explains how to run FlightPath locally |

Build and check it on your own machine (with `make dev` running in another terminal):

```bash
make showcase        # snapshot of the running stack + static export to apps/web/out
make test-showcase   # serves apps/web/out under /agent-blackbox and runs the browser checks
```

`make showcase` plays scenarios and applies fixes, so it adds those runs to your local
database. The export goes to `apps/web/out`, separate from `make dev`'s `.next`.

## 2. Full app in one Docker container

`infra/space/Dockerfile` builds an image that runs everything in one container, in public
mode (`PUBLIC_DEMO=true`): ingesting runs needs a token that only the container has, and
Live AI runs are rate limited per visitor and per day. Every start creates a fresh
database with the demo runs and benchmark results, so a public demo resets itself.

```bash
docker build -f infra/space/Dockerfile -t flightpath .
docker run --rm -p 7860:7860 flightpath          # http://127.0.0.1:7860
docker build -f infra/space/Dockerfile --build-arg WITH_QWEN=0 -t flightpath .   # no Live AI, smaller
```

With Live AI on (the default), a small Qwen model (`Qwen/Qwen2.5-0.5B-Instruct`, override
with `--build-arg QWEN_MODEL=...`) runs on the container's CPU, so no GPU or API key is
needed. To use a hosted OpenAI-compatible API instead, pass `LLM_BASE_URL`,
`LLM_API_KEY`, `LLM_MODEL` and `LLM_LABEL` as environment variables.

Only port 7860 is published. The API, Postgres and Redis listen on 127.0.0.1 inside the
container. There is still no user authentication, so treat a public instance as a demo
with demo data only.

The image runs on any Docker host (a VPS, a cloud container service). It also runs as a
Hugging Face Docker Space (`infra/space/push.py` publishes the repository to one), but
since mid-2026 new Docker Spaces on Hugging Face's free CPU tier need a PRO subscription.
