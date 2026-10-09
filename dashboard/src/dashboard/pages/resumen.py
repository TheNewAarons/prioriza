"""Página Resumen (ruta `/`); la lógica está en `dashboard.views.resumen`."""

import dash

from dashboard.views.resumen import layout

dash.register_page(
    __name__,
    path="/",
    name="Resumen",
    title="Resumen · Prioriza",
    layout=layout,
)
