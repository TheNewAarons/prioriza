"""Página Lista priorizada (ruta `/lista`); la lógica está en `dashboard.views.lista`."""

import dash

from dashboard.views.lista import layout

dash.register_page(
    __name__,
    path="/lista",
    name="Lista",
    title="Lista · Prioriza",
    layout=layout,
)
