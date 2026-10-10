"""Ajustes de la API, leídos de variables de entorno con prefijo `PRIORIZA_API_`.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # --- Entorno y exposición. En `production` no hay documentación interactiva por defecto y
    # el archivo de usuarios es obligatorio y debe ser privado (permisos 600 o más estrictos).
    environment: Literal["development", "production"] = "development"
    # `None`: /docs, /redoc y /openapi.json solo en desarrollo; `true`/`false` lo fuerza.
    docs_enabled: bool | None = None
    # Sin CORS por defecto. Lista blanca explícita (separada por comas o lista JSON).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Valores válidos de la cabecera Host (el panel llega como `api` dentro de compose).
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "api"]
    )

    # --- Límites de entrada (todos devuelven un error 4xx antes de hacer trabajo costoso).
    # Tamaño máximo del cuerpo de una petición (413).
    max_body_bytes: int = Field(default=64 * 1024, ge=1)
    # Largo máximo de identificadores en la ruta o la consulta, y de las notas de revisión (422).
    max_id_length: int = Field(default=64, ge=1)
    max_note_length: int = Field(default=1_000, ge=1)
    max_export_rows: int = Field(default=50_000, ge=1)
    # Tope de la programación pedida (422).
    max_horizon_weeks: int = Field(default=12, ge=1)
    max_time_limit_s: float = Field(default=600.0, gt=0.0)
    # Peticiones por clave y minuto, ventana deslizante (429 con `Retry-After`).
    rate_limit_per_minute: int = Field(default=120, ge=1)
    # Un trabajo que lleva más de `time_limit_s * job_timeout_factor` se marca `failed`. El hilo
    # no se puede matar: sigue hasta que CP-SAT termine (el plan resultante se descarta del
    # trabajo pero, si llega a guardarse, queda `pending` y exige revisión humana).
    job_timeout_factor: float = Field(default=2.0, ge=1.0)
    job_timeout_grace_s: float = Field(default=30.0, ge=0.0)

    @property
    def docs_active(self) -> bool:
        """Si se exponen /docs, /redoc y /openapi.json."""
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.environment != "production"

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Acepta `a,b` además de una lista JSON."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("users_file", "run_dir", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Una variable de entorno vacía (p. ej. desde compose) equivale a no definirla."""
        return None if value == "" else value
