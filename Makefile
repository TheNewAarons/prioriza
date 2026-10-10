.PHONY: api up down migrate ingest synth train-noshow schedule bench-scheduler simulate demo report dashboard test lint typecheck format sync hooks audit help

up:
	@[ -f .env ] || cp .env.example .env
	docker compose up -d --build --wait

down:
	docker compose down

migrate:
	uv run alembic upgrade head

ingest:
	uv run --package ingestion prioriza-ingest all

SIZE ?= 100000
SEED ?= 42
SYNTH_ARGS ?=

synth:
	uv run --package synthetic prioriza-synth generate --size $(SIZE) --seed $(SEED) --load $(SYNTH_ARGS)

SCENARIO ?= baseline

train-noshow:
	uv run --package noshow prioriza-noshow train --seed $(SEED) --size $(SIZE) --scenario $(SCENARIO)

WEEKS ?= 4
SCHEDULE_ARGS ?=

schedule:
	uv run --package scheduler prioriza-schedule --weeks $(WEEKS) --seed $(SEED) --size $(SIZE) --scenario $(SCENARIO) $(SCHEDULE_ARGS)

BENCH_ARGS ?=

bench-scheduler:
	uv run --package scheduler prioriza-schedule-bench $(BENCH_ARGS)

SIM_ARGS ?=

simulate:
	uv run --package simulation prioriza-simulate $(SIM_ARGS)

DEMO_ARGS ?=

demo:
	scripts/demo.sh $(DEMO_ARGS)

REPORT_ARGS ?=

report:
	uv run --package reports prioriza-report $(REPORT_ARGS)

PRIORIZA_API_USERS_FILE ?= api/config/users.json
API_PORT ?= 8000

api:
	PRIORIZA_API_USERS_FILE=$(PRIORIZA_API_USERS_FILE) uv run --package api uvicorn --factory api.main:create_app --host 127.0.0.1 --port $(API_PORT)

dashboard:
	PRIORIZA_API_USERS_FILE=$(PRIORIZA_API_USERS_FILE) uv run --package dashboard prioriza-dashboard --with-api

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

format:
	uv run ruff format . && uv run ruff check --fix .

sync:
	uv sync --all-packages

hooks:
	uv run pre-commit install

audit:
	@tmp=$$(mktemp) && trap 'rm -f "$$tmp"' EXIT && \
	uv export --all-packages --no-hashes --no-emit-workspace --format requirements-txt --quiet > "$$tmp" && \
	uv run pip-audit -r "$$tmp" --disable-pip --no-deps --progress-spinner off

help:
	@echo "Prioriza - Sistema de gestión de listas de espera hospitalarias"
	@echo ""
	@echo "Targets disponibles:"
	@echo "  up                 Levanta postgres + api + dashboard"
	@echo "  down               Detiene los servicios"
	@echo "  migrate            Ejecuta migraciones de Alembic"
	@echo "  ingest             Descarga datos públicos agregados"
	@echo "  synth              Genera población sintética calibrada"
	@echo "  train-noshow       Entrena y calibra el modelo de inasistencias"
	@echo "  schedule           Corre el programador CP-SAT"
	@echo "  bench-scheduler    Benchmark del programador CP-SAT"
	@echo "  simulate           Compara políticas con SimPy"
	@echo "  demo               Demo de punta a punta (sin Docker ni PostgreSQL)"
	@echo "  report             Genera docs/results.md y .html"
	@echo "  api                Levanta la API FastAPI (puerto 8000)"
	@echo "  dashboard          Levanta el panel Dash (y la API si no responde)"
	@echo "  test               Corre pytest"
	@echo "  lint               Verifica ruff (check y format)"
	@echo "  typecheck          Corre mypy"
	@echo "  format             Formatea código con ruff"
	@echo "  sync               Sincroniza dependencias de uv"
	@echo "  hooks              Instala los hooks de git (pre-commit y pre-push)"
	@echo "  audit              Audita dependencias con pip-audit"
	@echo "  help               Muestra esta ayuda"
