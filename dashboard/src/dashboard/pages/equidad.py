"""Página Equidad (ruta `/equidad`); la lógica está en `dashboard.views.equidad`."""

import dash

from dashboard.views.equidad import layout

dash.register_page(
    __name__,
    path="/equidad",
    name="Equidad",
    title="Equidad · Prioriza",
    layout=layout,
)
