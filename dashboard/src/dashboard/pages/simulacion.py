"""Página Simulación (ruta `/simulacion`); la lógica está en `dashboard.views.simulacion`."""

import dash

from dashboard.views.simulacion import layout

dash.register_page(
    __name__,
    path="/simulacion",
    name="Simulación",
    title="Simulación · Prioriza",
    layout=layout,
)
