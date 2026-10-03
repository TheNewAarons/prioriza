.PHONY: up down migrate ingest synth train-noshow schedule simulate report dashboard test lint typecheck format sync help

up:
	@[ -f .env ] || cp .env.example .env
	docker compose up -d --build --wait

down:
	docker compose down

migrate:
	uv run alembic upgrade head

ingest:
	uv run --package ingestion prioriza-ingest all

synth:
	@echo "synth: pendiente"

train-noshow:
	@echo "train-noshow: pendiente"

schedule:
	@echo "schedule: pendiente"

simulate:
	@echo "simulate: pendiente"

report:
	@echo "report: pendiente"

dashboard:
	@echo "dashboard: pendiente"

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
	@echo "  simulate           Compara políticas con SimPy"
	@echo "  report             Genera docs/results.md y .html"
	@echo "  dashboard          Levanta el panel Dash"
	@echo "  test               Corre pytest"
	@echo "  lint               Verifica ruff (check y format)"
	@echo "  typecheck          Corre mypy"
	@echo "  format             Formatea código con ruff"
	@echo "  sync               Sincroniza dependencias de uv"
	@echo "  help               Muestra esta ayuda"
