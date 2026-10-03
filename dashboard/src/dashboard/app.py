"""Aplicación Dash mínima con el aviso obligatorio visible."""

import dash_bootstrap_components as dbc
from dash import Dash, html

DISCLAIMER = (
    "Herramienta de investigación con datos sintéticos. "
    "No usar para decisiones clínicas ni de gestión real sin validación institucional."
)

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title="Prioriza")
app.layout = dbc.Container(
    [
        html.H1("Prioriza", className="mt-3"),
        dbc.Alert(DISCLAIMER, color="warning", id="disclaimer"),
    ],
    fluid=True,
)

server = app.server


@server.route("/healthz")
def healthz() -> tuple[str, int]:
    """Sonda de salud para Docker y orquestadores."""
    return "ok", 200
