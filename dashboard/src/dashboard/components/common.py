"""Piezas de interfaz compartidas: secciones, indicadores, avisos y figuras con tabla.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import plotly.graph_objects as go
from dash import dcc, html
from dash.development.base_component import Component

from dashboard.components.attrs import aria
from dashboard.components.tables import simple_table
from dashboard.theme import GRAPH_CONFIG

Children = Component | str | Sequence[Component | str]


def section(title: str, *children: Component | str | None, step: int | None = None) -> html.Section:
    """Sección con título `h2` y aire (sin tarjetas)."""
    heading = html.H2([html.Span(f"{step}.", className="step-num"), title] if step else title)
    return html.Section([heading, *[c for c in children if c is not None]], className="section")


def note(text: Children, *, ink: bool = False) -> html.P:
    """Nota pequeña (`--t-small`)."""
    return html.P(text, className="note note--ink" if ink else "note")


def empty_state(text: str) -> html.P:
    """Vacío como invitación o aviso corto."""
    return html.P(text, className="empty")


def error_panel(message: str) -> html.Div:
    """Mensaje de error que dice qué pasó y qué hacer."""
    return html.Div(message, className="alert alert--error", role="alert")


def ok_panel(message: str) -> html.Div:
    """Mensaje de acción lograda."""
    return html.Div(message, className="alert alert--ok", role="status")


def kpi(value: str, label: str, state: str | None = None) -> html.Div:
    """Indicador: cifra y rótulo, con filete superior de color si tiene estado."""
    cls = "kpi" + (f" kpi--{state}" if state else "")
    return html.Div(
        [html.Div(value, className="kpi-value"), html.Div(label, className="kpi-label")],
        className=cls,
    )


def field(
    label: str, control: Component, *, control_id: str, error_id: str | None = None
) -> html.Div:
    """Campo con `label` asociado y, si se pide, lugar para el mensaje de error."""
    children: list[Component] = [html.Label(label, htmlFor=control_id), control]
    if error_id:
        children.append(html.Div(id=error_id, className="field-error", role="alert"))
    return html.Div(children, className="field")


def figure_block(
    figure: go.Figure,
    *,
    aria_label: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    graph_id: str | dict[str, Any] | None = None,
) -> html.Div:
    """Gráfico con `aria-label` que resume la conclusión y tabla equivalente en "Ver datos"."""
    extra: dict[str, Any] = {} if graph_id is None else {"id": graph_id}
    graph = dcc.Graph(figure=figure, config=GRAPH_CONFIG, style={"width": "100%"}, **extra)
    return html.Div(
        [
            html.Div(graph, role="img", **aria({"aria-label": aria_label})),
            html.Details(
                [html.Summary("Ver datos"), simple_table(headers, rows)],
            ),
        ],
        className="figure",
    )
