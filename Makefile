# Agent BlackBox developer commands. Run `make help`.
# Works the same on BU SCC (Python venv from infra/scc/setup_scc.sh) and on a laptop with
# Docker (docker-compose.yml for Postgres/Redis + .venv with Python 3.11/3.12 and Node 22).

SHELL := /bin/bash
.DEFAULT_GOAL := help

-include .env
export

# Python venv used by every target. Default: .venv in the repo. To use a named venv
# elsewhere (e.g. .../venvs/agent-blackbox), set BLACKBOX_VENV in .env.
VENV ?= $(or $(BLACKBOX_VENV),$(CURDIR)/.venv)
ifneq ($(wildcard $(VENV)/bin),)
export PATH := $(VENV)/bin:$(PATH)
endif

API := apps/api
WEB := apps/web
HARNESS := packages/agent_harness
SDK := packages/blackbox_sdk
ANALYSIS := packages/analysis_engine
# Playwright browsers live in the repo (not $HOME) so they count against project quota.
export PLAYWRIGHT_BROWSERS_PATH ?= $(CURDIR)/.cache/ms-playwright

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
.PHONY: setup-scc
setup-scc: ## One-time setup on BU SCC / any Linux without Docker
	bash infra/scc/setup_scc.sh

.PHONY: install
install: ## Install deps into the CURRENT Python/Node (Docker/laptop path)
	python -m pip install -e "$(API)[dev]" -e "$(HARNESS)[dev]" -e "$(SDK)[dev]" -e "$(ANALYSIS)[dev]"
	cd $(WEB) && npm ci --no-audit --no-fund

# ---------------------------------------------------------------- services
.PHONY: services-up services-down services-status
services-up: ## Start local Postgres + Redis (no Docker)
	bash infra/scc/services.sh start
services-down: ## Stop local Postgres + Redis (data is kept)
	bash infra/scc/services.sh stop
services-status: ## Show local Postgres + Redis status
	bash infra/scc/services.sh status

.PHONY: compose-up compose-down
compose-up: ## (Docker only) start Postgres + Redis containers
	docker compose up -d --wait
compose-down: ## (Docker only) stop containers (add -v manually to delete data)
	docker compose down

# ---------------------------------------------------------------- live AI (Qwen)
.PHONY: qwen-setup qwen qwen-status
qwen-setup: ## One-time: install PyTorch + Qwen for the live demo (runs on this node)
	bash infra/scc/qwen_setup.sh
qwen: ## Run only the local Qwen server in this terminal (make dev already starts it)
	python infra/scc/qwen_server.py
qwen-status: ## Is the local Qwen server loading / ready?
	@curl -fsS "http://127.0.0.1:$${QWEN_PORT:-8001}/health" && echo || echo "Qwen server is not running (start it with make dev)"

# ---------------------------------------------------------------- run
.PHONY: migrate
migrate: ## Apply database migrations
	cd $(API) && python -m alembic upgrade head

.PHONY: dev
dev: ## Run API + worker + web together (Ctrl+C to stop)
	bash scripts/dev.sh

.PHONY: seed-demo
seed-demo: ## Record every fixture through the SDK into the running API (make dev must be up)
	python -m blackbox_sdk.seed_demo --capture-content

.PHONY: demo demo-fail
demo: ## Run every demo-agent fixture 10x and compare with expected baselines
	python -m agent_harness.run_demo --all --repeat 10
demo-fail: ## Show the flagship failing run (invalid inventory argument)
	-python -m agent_harness.run_demo --fixture invalid_inventory_argument

# ---------------------------------------------------------------- quality
.PHONY: lint
lint: ## Ruff + mypy + TypeScript
	cd $(API) && python -m ruff check . && python -m ruff format --check . && python -m mypy app
	cd $(HARNESS) && python -m ruff check . && python -m ruff format --check . && python -m mypy agent_harness
	cd $(SDK) && python -m ruff check . && python -m ruff format --check . && python -m mypy blackbox_sdk
	cd $(ANALYSIS) && python -m ruff check . && python -m ruff format --check . && python -m mypy analysis_engine
	cd $(WEB) && npx tsc --noEmit

.PHONY: test test-api test-harness test-sdk test-analysis test-web test-web-smoke test-e2e e2e-install eval-detectors
test: test-harness test-sdk test-analysis test-api test-web ## All tests that don't need the web server running

test-analysis: ## Failure detectors: behaviour, metric math, labelled evaluation
	cd $(ANALYSIS) && python -m pytest -v

eval-detectors: ## Precision/recall of the detectors on labelled fixtures -> artifacts/analysis/
	mkdir -p artifacts/analysis
	python -m analysis_engine.evaluation --out artifacts/analysis/detector_eval.json

test-sdk: ## SDK: span tree, redaction, exporters (no services needed)
	cd $(SDK) && python -m pytest -v

test-harness: ## Demo agent: tools, fixtures, verifiers, determinism (no services needed)
	cd $(HARNESS) && python -m pytest -v

test-api: ## API unit + integration tests (needs Postgres + Redis up)
	cd $(API) && python -m pytest -v

test-web: ## Frontend unit tests
	cd $(WEB) && npx vitest run

test-web-smoke: ## Live smoke test through the Next.js proxy (run while `make dev` is up)
	cd $(WEB) && SMOKE_BASE_URL=http://127.0.0.1:$${WEB_PORT:-3000}/backend npx vitest run

e2e-install: ## One-time: download the headless Chromium used by browser tests
	cd $(WEB) && npx playwright install chromium

test-e2e: ## Browser tests (run while `make dev` is up): seeds real runs, then Playwright
	python -m blackbox_sdk.seed_demo --capture-content --fixtures invalid_inventory_argument,exchange_success
	python -m blackbox_sdk.seed_demo --fixtures invalid_inventory_argument
	cd $(WEB) && E2E_BASE_URL=http://127.0.0.1:$${WEB_PORT:-3000}/ npx playwright test

.PHONY: build-web
build-web: ## Production build of the web app
	cd $(WEB) && npm run build

.PHONY: check
check: lint test build-web ## Everything CI runs

# ---------------------------------------------------------------- cleanup
.PHONY: clean
clean: ## Remove build/test caches (keeps data, deps and .env)
	rm -rf $(WEB)/.next $(WEB)/tsconfig.tsbuildinfo
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +

.PHONY: reset-data
reset-data: ## DANGER: stop services and DELETE local database/redis data
	@read -p "Delete $${BLACKBOX_DATA_DIR:-.local-data}? Type yes: " ans && [ "$$ans" = yes ]
	-bash infra/scc/services.sh stop
	rm -rf "$${BLACKBOX_DATA_DIR:-$(CURDIR)/.local-data}"
	@echo "Data deleted. Run 'make setup-scc' to recreate the database."
