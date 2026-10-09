"""Configuración y cliente compartidos por los callbacks.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Los callbacks se registran al importar los módulos de `views/`, antes de que exista la app, así
que obtienen el cliente por aquí. Los tests lo reemplazan con `set_client`.
"""

from __future__ import annotations

from dashboard.api_client import ApiClient
from dashboard.config import DashboardSettings

_settings: DashboardSettings | None = None
_client: ApiClient | None = None


def configure(settings: DashboardSettings) -> None:
    """Fija los ajustes y descarta el cliente anterior."""
    global _settings, _client
    _settings = settings
    if _client is not None:
        _client.close()
    _client = None


def get_settings() -> DashboardSettings:
    """Ajustes vigentes (por entorno si nadie los fijó)."""
    global _settings
    if _settings is None:
        _settings = DashboardSettings()
    return _settings


def get_client() -> ApiClient:
    """Cliente de la API, creado la primera vez que se necesita."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = ApiClient(settings.api_url, timeout_s=settings.timeout_s)
    return _client


def set_client(client: ApiClient | None) -> None:
    """Reemplaza el cliente (tests)."""
    global _client
    _client = client
