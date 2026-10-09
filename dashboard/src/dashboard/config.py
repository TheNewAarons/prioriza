"""Ajustes del panel, leídos de variables de entorno con prefijo `PRIORIZA_DASHBOARD_`.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardSettings(BaseSettings):
    """Dónde está la API y dónde escucha el panel."""

    model_config = SettingsConfigDict(env_prefix="PRIORIZA_DASHBOARD_", extra="ignore")

    # Dirección de la API. El panel solo la consume por HTTP; no importa su dominio.
    api_url: str = "http://127.0.0.1:8000"
    host: str = "127.0.0.1"
    port: int = Field(default=8050, ge=1, le=65535)
    # La primera petición a la API carga la corrida completa y puede tardar.
    timeout_s: float = Field(default=60.0, gt=0.0)
    debug: bool = False
