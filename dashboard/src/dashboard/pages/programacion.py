"""Página Programación (ruta `/programacion`); la lógica está en `dashboard.views.programacion`."""

import dash

from dashboard.views.programacion import layout

dash.register_page(
    __name__,
    path="/programacion",
    name="Programación",
    title="Programación · Prioriza",
    layout=layout,
)
