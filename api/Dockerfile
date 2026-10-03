# syntax=docker/dockerfile:1
# Construir desde la raíz del repo: docker build -f api/Dockerfile .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 1) Solo dependencias (cacheable): requiere lock, pyproject raíz y pyprojects de TODOS los miembros.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY ingestion/pyproject.toml ingestion/
COPY synthetic/pyproject.toml synthetic/
COPY priority/pyproject.toml priority/
COPY noshow/pyproject.toml noshow/
COPY scheduler/pyproject.toml scheduler/
COPY simulation/pyproject.toml simulation/
COPY api/pyproject.toml api/
COPY dashboard/pyproject.toml dashboard/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package api

# 2) Código de los miembros, instalado de forma no editable dentro del venv.
COPY shared/ shared/
COPY api/ api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package api

FROM python:3.12-slim-bookworm AS final
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
