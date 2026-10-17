# FlightPath, the full app, in one container: any Docker host, or a Hugging Face Docker
# Space (since mid-2026 those need a PRO subscription on the CPU tier; the free option is
# the static showcase on GitHub Pages, see docs/deploy.md).
#
# One container runs the whole app: Postgres and Redis (from pip wheels, as in `make setup`),
# the API, the replay worker, the web app on port 7860 and a small Qwen model on the CPU for
# Live AI. Nothing persists: every start creates a fresh database with the demo runs and
# the benchmark results, so the public demo resets itself.
#
# infra/space/push.py copies this file to the root of a Space. Local build:
#   docker build -f infra/space/Dockerfile -t flightpath .
#   docker run --rm -p 7860:7860 flightpath          # then open http://127.0.0.1:7860
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3.12 python3.12-venv ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000; ubuntu:24.04 already has a user with that id.
RUN (userdel -r ubuntu 2>/dev/null || true) && useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    VENV=/home/user/venv \
    HF_HOME=/home/user/hf
ENV PATH=/home/user/venv/bin:$PATH \
    BLACKBOX_VENV=/home/user/venv
WORKDIR /home/user/app

RUN python3.12 -m venv "$VENV" && pip install --upgrade pip

# Live AI: CPU PyTorch + a small Qwen model, baked into the image so a cold start does not
# download anything. WITH_QWEN=0 builds a scripted-only image (smaller, faster to build).
ARG WITH_QWEN=1
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG QWEN_MODEL=Qwen/Qwen2.5-0.5B-Instruct
ENV QWEN_MODEL=$QWEN_MODEL
RUN if [ "$WITH_QWEN" = 1 ]; then \
      pip install --index-url "$TORCH_INDEX_URL" 'torch>=2.6' \
      && pip install 'transformers>=4.56' 'accelerate>=1.0' 'huggingface_hub>=0.34' \
      && python -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['QWEN_MODEL'])"; \
    fi

COPY --chown=user . .
RUN pip install -e apps/api -e packages/agent_harness -e packages/blackbox_sdk \
      -e packages/analysis_engine -e packages/evaluation \
      -r infra/local/requirements-local-services.txt \
    && PG_BIN="$(python -c 'import pathlib, pgserver; print(pathlib.Path(pgserver.__file__).parent / "pginstall" / "bin")')" \
    && for bin in initdb pg_ctl postgres psql createdb pg_isready; do ln -sf "$PG_BIN/$bin" "$VENV/bin/$bin"; done

# The web app proxies /backend/* to the API inside the container (fixed internal port).
RUN cd apps/web \
    && npm ci --no-audit --no-fund \
    && API_INTERNAL_URL=http://127.0.0.1:8000 npm run build \
    && npm prune --omit=dev --no-audit --no-fund

EXPOSE 7860
CMD ["bash", "infra/space/start.sh"]
