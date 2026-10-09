"""Ajustes de la API, leídos de variables de entorno con prefijo `PRIORIZA_API_`.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Ubicación de usuarios, datos, modelos y resultados, y tipo de almacenamiento de planes."""

    model_config = SettingsConfigDict(env_prefix="PRIORIZA_API_", extra="ignore")

    # Archivo JSON `{api_key: {"user": ..., "role": ...}}`. Sin archivo no hay usuarios y toda
    # ruta protegida responde 401 (nunca hay claves por defecto).
    users_file: Path | None = None
    # `memory` se pierde al reiniciar; `sql` guarda en PostgreSQL (requiere `make migrate`).
    store: Literal["memory", "sql"] = "memory"
    # Corrida sintética: explícita (`run_dir`) o buscada por semilla, tamaño y escenario.
    run_dir: Path | None = None
    data_dir: Path = Path("data/synthetic")
    seed: int = 42
    size: int = 100_000
    scenario: str = "baseline"
    models_dir: Path = Path("models/noshow")
    results_dir: Path = Path("results")
    # Trabajos de programación: viven en memoria (se pierden al reiniciar, aunque `store=sql`).
    max_active_jobs_per_user: int = Field(default=2, ge=1)
    max_active_jobs: int = Field(default=8, ge=1)
    job_ttl_hours: float = Field(default=24.0, gt=0.0)

    @field_validator("users_file", "run_dir", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Una variable de entorno vacía (p. ej. desde compose) equivale a no definirla."""
        return None if value == "" else value
