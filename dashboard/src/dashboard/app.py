"""Aplicación Dash de Prioriza.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

`create_app(settings)` arma la app con `use_pages=True` (páginas en `pages/`, lógica en `views/`).
Los callbacks se registran al importar `shell` y `views`, por eso la app es única por proceso:
una segunda llamada solo actualiza los ajustes y devuelve la misma app. `server` es el servidor
Flask para gunicorn (`dashboard.app:server`).
"""

from __future__ import annotations

import logging
from pathlib import Path

from dash import Dash
from flask import Response
from shared.disclaimer import DISCLAIMER
from shared.logging import install_redaction

from dashboard import runtime, shell, theme
from dashboard.config import DashboardSettings
from dashboard.views import equidad, lista, programacion, resumen, simulacion

__all__ = ["DISCLAIMER", "app", "create_app", "server"]

PACKAGE_DIR = Path(__file__).parent

INDEX_STRING = """<!DOCTYPE html>
<html lang="es">
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>
"""

_app: Dash | None = None

# Los módulos de `views` se importan por sus callbacks; esta lista evita que linters los den
# por no usados.
_VIEWS = (resumen, lista, programacion, simulacion, equidad, shell)


def security_headers(response: Response, settings: DashboardSettings) -> Response:
    """Cabeceras defensivas del panel; `Cache-Control: no-store` salvo en los assets estáticos."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if settings.content_security_policy:
        response.headers.setdefault("Content-Security-Policy", settings.content_security_policy)
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


def create_app(settings: DashboardSettings | None = None) -> Dash:
    """Crea (una vez) la app del panel y fija los ajustes que usan los callbacks."""
    global _app
    runtime.configure(settings or DashboardSettings())
    if _app is not None:
        return _app
    install_redaction()
    # La clave de API viaja en cabeceras; httpx no las registra, y a nivel INFO tampoco hay que
    # llenar el log con cada petición.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # El access log de werkzeug incluye rutas y parámetros de consulta: queda a nivel WARNING
    # (la redacción de `shared.logging` cubre además lo que llegue a registrarse).
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app = Dash(
        __name__,
        use_pages=True,
        pages_folder=str(PACKAGE_DIR / "pages"),
        assets_folder=str(PACKAGE_DIR / "assets"),
        external_stylesheets=[theme.FONT_URL],
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
        title="Prioriza",
        update_title="",
        suppress_callback_exceptions=True,
    )
    app.index_string = INDEX_STRING
    app.layout = shell.root_layout()

    @app.server.route("/healthz")  # type: ignore[untyped-decorator]
    def healthz() -> tuple[str, int]:
        """Sonda de salud para Docker y orquestadores."""
        return "ok", 200

    @app.server.after_request  # type: ignore[untyped-decorator]
    def add_security_headers(response: Response) -> Response:
        return security_headers(response, runtime.get_settings())

    _app = app
    return app


app = create_app()
server = app.server
