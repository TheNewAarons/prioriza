"""Tablas: simples (HTML) y de Dash con el estilo del diseño.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dash import dash_table, html
from dash.development.base_component import Component

from dashboard import theme


def simple_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    numeric: Sequence[int] = (),
    caption: str | None = None,
) -> html.Div:
    """Tabla HTML accesible; las columnas en `numeric` van a la derecha."""
    num = set(numeric)
    head = html.Tr(
        [
            html.Th(h, scope="col", className="num" if i in num else None)
            for i, h in enumerate(headers)
        ]
    )
    body = [
        html.Tr(
            [html.Td(cell, className="num" if i in num else None) for i, cell in enumerate(row)]
        )
        for row in rows
    ]
    table = html.Table(
        [
            *([html.Caption(caption, className="note")] if caption else []),
            html.Thead(head),
            html.Tbody(body),
        ],
        className="table-simple",
    )
    return html.Div(table, className="table-wrap")


def server_table(
    table_id: str,
    columns: Sequence[dict[str, Any]],
    *,
    page_size: int,
    selectable: bool = False,
    right_aligned: Sequence[str] = (),
    extra_styles: Sequence[dict[str, Any]] = (),
) -> Component:
    """`DataTable` con paginación del servidor (`page_action="custom"`) y estilo del diseño."""
    conditional: list[dict[str, Any]] = [
        {"if": {"column_id": c}, "textAlign": "right"} for c in right_aligned
    ]
    conditional.append(
        {
            "if": {"state": "selected"},
            "backgroundColor": theme.SCRUB_TINT,
            "border": f"1px solid {theme.SCRUB}",
        }
    )
    conditional.append({"if": {"column_id": "score_bar"}, "color": theme.SCRUB})
    conditional.extend(extra_styles)
    return dash_table.DataTable(  # type: ignore[attr-defined,no-any-return]
        id=table_id,
        columns=list(columns),
        data=[],
        page_action="custom",
        page_current=0,
        page_size=page_size,
        page_count=1,
        sort_action="none",
        filter_action="none",
        row_selectable="single" if selectable else False,
        selected_rows=[],
        style_as_list_view=True,
        style_table={"overflowX": "auto", "border": f"1px solid {theme.RULE}"},
        style_header={
            "backgroundColor": theme.SURFACE,
            "color": theme.INK,
            "fontWeight": 600,
            "border": "none",
            "borderBottom": f"1px solid {theme.RULE}",
            "fontFamily": theme.FONT_FAMILY,
            "fontSize": f"{theme.T_SMALL}px",
        },
        style_cell={
            "backgroundColor": theme.SURFACE,
            "color": theme.INK,
            "fontFamily": theme.FONT_FAMILY,
            "fontSize": f"{theme.T_BODY}px",
            "padding": f"{theme.S2}px {theme.S3}px",
            "textAlign": "left",
            "border": "none",
            "borderBottom": f"1px solid {theme.RULE}",
            "whiteSpace": "normal",
            "height": "auto",
            "minWidth": "64px",
            "maxWidth": "420px",
        },
        style_data_conditional=conditional,
    )
