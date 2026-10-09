"""Gráficos Plotly del panel: intervalos por política, puntos por grupo y mapa del calendario.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Todo gráfico lleva un título que dice lo que muestra, el aviso de investigación al pie (también
queda en la imagen descargada) y nunca usa solo color: cada política tiene marcador y línea
propios y el mapa del calendario escribe el número en cada celda.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shared.disclaimer import DISCLAIMER

from dashboard import fmt, theme


def _wrap(text: str, width: int = 56) -> str:
    """Parte el texto en líneas con `<br>` para que quepa al pie de la figura."""
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    lines.append(current)
    return "<br>".join(lines)


def with_disclaimer(
    fig: go.Figure,
    *,
    title: str | None,
    height: int,
    axis_room: int = 40,
    top: int | None = None,
    wrap: int = 56,
) -> go.Figure:
    """Fija título, alto y una nota al pie con el aviso de investigación.

    `axis_room` son los píxeles bajo el área de dibujo que ocupan las marcas y el título del eje
    x; la nota va justo debajo (los márgenes son explícitos, no automáticos). `wrap` es el largo
    de línea del aviso: las figuras angostas (panel de detalle) usan uno menor para que el aviso
    se lea completo.
    """
    note = _wrap(DISCLAIMER, wrap)
    lines = note.count("<br>") + 1
    fig.update_layout(
        template=theme.TEMPLATE_NAME,
        height=height + 16 * max(lines - 3, 0),
        title={"text": title} if title else None,
        margin={
            "l": 16,
            "r": 32,
            "t": top if top is not None else (64 if title else 28),
            "b": axis_room + 12 + 16 * lines,
        },
    )
    fig.update_xaxes(automargin=False)
    fig.add_annotation(
        text=note,
        xref="paper",
        yref="paper",
        x=0,
        y=0,
        xanchor="left",
        yanchor="top",
        yshift=-axis_room,
        showarrow=False,
        align="left",
        font={"family": theme.FONT_FAMILY, "size": 11, "color": theme.INK_MUTED},
    )
    return fig


def interval_chart(
    *,
    title: str,
    rows: Sequence[dict[str, Any]],
    unit_decimals: int = 0,
    percent: bool = False,
    x_title: str = "",
) -> go.Figure:
    """Punto con barra de IC 95 % por política.

    `rows`: `{"policy", "mean", "low", "high"}`. Cada política: color, marcador y línea propios
    (la barra del intervalo usa su tipo de línea) y el valor rotulado.
    """
    fig = go.Figure()

    def fmt_value(v: float) -> str:
        return fmt.pct(v, 1) if percent else fmt.num(v, unit_decimals)

    for row in rows:
        style = theme.SERIES[row["policy"]]
        label = style.label
        fig.add_trace(
            go.Scatter(
                x=[row["low"], row["mean"], row["high"]],
                y=[label] * 3,
                name=label,
                mode="lines+markers+text",
                line={"color": style.color, "dash": style.dash, "width": 3},
                marker={
                    "color": style.color,
                    "size": [10, 14, 10],
                    "symbol": ["line-ns", style.marker, "line-ns"],
                    "line": {"color": style.color, "width": 2},
                },
                text=["", fmt_value(row["mean"]), ""],
                textposition="top center",
                textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
                hovertemplate=(
                    f"{label}<br>media {fmt_value(row['mean'])}"
                    f"<br>IC 95 % {fmt_value(row['low'])} a {fmt_value(row['high'])}<extra></extra>"
                ),
            )
        )
    fig.update_yaxes(autorange="reversed", showgrid=True, gridcolor=theme.RULE, title_text="")
    fig.update_xaxes(title_text=x_title, showgrid=False, tickformat=".0%" if percent else None)
    return with_disclaimer(fig, title=title, height=170 + 62 * max(len(rows), 1), axis_room=70)


def group_dot_chart(
    *,
    title: str,
    panels: Sequence[dict[str, Any]],
    labels: Sequence[str],
) -> go.Figure:
    """Puntos por grupo con rango mín-máx entre réplicas, una columna por métrica.

    `panels`: `{"title", "percent", "decimals", "values": [{"mean","min","max"}...], "reference",
    "flags": [bool...]}`; `values`, `flags` y `labels` van alineados. Un solo color (`INK`); la
    referencia (total) es una línea vertical punteada `INK_MUTED`.
    """
    n = len(panels)
    fig = make_subplots(
        rows=1,
        cols=n,
        shared_yaxes=True,
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.04,
    )
    y_labels = [
        ("▲ " if any_flag else "") + label
        for label, any_flag in zip(labels, _flags(panels), strict=True)
    ]
    for i, panel in enumerate(panels, start=1):
        pct_mode = panel["percent"]
        decimals = panel.get("decimals", 0)

        def value(v: float, pct_mode: bool = pct_mode, decimals: int = decimals) -> str:
            return fmt.pct(v, 1) if pct_mode else fmt.num(v, decimals)

        means = [v["mean"] for v in panel["values"]]
        fig.add_trace(
            go.Scatter(
                x=means,
                y=y_labels,
                mode="markers+text",
                marker={"color": theme.INK, "size": 10, "symbol": "circle"},
                error_x={
                    "type": "data",
                    "symmetric": False,
                    "array": [v["max"] - v["mean"] for v in panel["values"]],
                    "arrayminus": [v["mean"] - v["min"] for v in panel["values"]],
                    "color": theme.INK,
                    "thickness": 1.5,
                    "width": 5,
                },
                text=[value(m) for m in means],
                textposition="top center",
                textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
                hovertemplate="%{y}: %{text}<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=i,
        )
        if panel.get("reference") is not None:
            fig.add_vline(
                x=panel["reference"],
                line={"color": theme.INK_MUTED, "dash": "dot", "width": 2},
                row=1,
                col=i,
            )
        fig.update_xaxes(
            tickformat=".0%" if pct_mode else None, showgrid=False, nticks=4, row=1, col=i
        )
    # Holgura arriba para que el valor rotulado del primer grupo no choque con el título.
    fig.update_yaxes(range=[len(labels) - 0.5, -1.0], showgrid=True, gridcolor=theme.RULE)
    for ann in fig.layout.annotations:
        ann.update(
            font={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
            xanchor="left",
        )
    return with_disclaimer(fig, title=title, height=170 + 36 * max(len(labels), 1), axis_room=40)


def _flags(panels: Sequence[dict[str, Any]]) -> list[bool]:
    """Un grupo se marca con ▲ si está fuera de la brecha permitida en alguna métrica."""
    size = len(panels[0]["flags"]) if panels else 0
    return [any(p["flags"][i] for p in panels) for i in range(size)]


def calendar_heatmap(
    *,
    title: str,
    row_labels: Sequence[str],
    dates: Sequence[str],
    cells: dict[tuple[int, int], dict[str, int]],
) -> go.Figure:
    """Mapa de calor recurso x día: el número de citas va dentro de la celda.

    `cells[(fila, columna)] = {"booked": citas, "overbooked": sobrecupos, "capacity": ...}`. El
    color solo refuerza; las celdas con sobrecupo llevan borde y `+n`.
    """
    z: list[list[float | None]] = [[None] * len(dates) for _ in row_labels]
    text: list[list[str]] = [[""] * len(dates) for _ in row_labels]
    hover: list[list[str]] = [[""] * len(dates) for _ in row_labels]
    shapes: list[dict[str, Any]] = []
    for (r, c), cell in cells.items():
        booked = cell["booked"]
        over = cell["overbooked"]
        z[r][c] = float(booked)
        text[r][c] = f"{booked}" + (f" +{over}" if over else "")
        hover[r][c] = (
            f"{row_labels[r]}<br>{fmt.weekday_date(dates[c])}<br>{booked} citas"
            f"{f' ({over} con sobrecupo)' if over else ''}<br>capacidad {cell['capacity']}"
        )
        if over:
            shapes.append(
                {
                    "type": "rect",
                    "xref": "x",
                    "yref": "y",
                    "x0": c - 0.5,
                    "x1": c + 0.5,
                    "y0": r - 0.5,
                    "y1": r + 0.5,
                    "line": {"color": theme.INK, "width": 3},
                }
            )
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=list(range(len(dates))),
            y=list(range(len(row_labels))),
            text=text,
            texttemplate="%{text}",
            textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=[[0, theme.SURFACE], [1, theme.SCRUB_TINT]],
            xgap=2,
            ygap=2,
            showscale=False,
            hoverongaps=False,
        )
    )
    fig.update_layout(shapes=shapes)
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(len(dates))),
        ticktext=[fmt.weekday_date(d) for d in dates],
        tickangle=-60,
        side="top",
        showgrid=False,
    )
    fig.update_yaxes(
        tickmode="array",
        tickvals=list(range(len(row_labels))),
        ticktext=list(row_labels),
        autorange="reversed",
        showgrid=False,
    )
    return with_disclaimer(
        fig, title=title, height=240 + 26 * max(len(row_labels), 1), axis_room=12, top=150
    )


def component_bars(*, title: str, components: Sequence[dict[str, Any]]) -> go.Figure:
    """Barras horizontales del desglose del puntaje; cada una rotulada con su aporte en puntos."""
    labels = [c["label"] for c in components]
    values = [c["contribution"] for c in components]
    maxima = [c["weight"] for c in components]
    fig = go.Figure(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker={"color": theme.SCRUB},
            text=[
                f"{fmt.num(v, 1)} de {fmt.num(m, 0)} pts"
                for v, m in zip(values, maxima, strict=True)
            ],
            textposition="outside",
            textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
            hovertemplate="%{y}: %{x:.1f} puntos<extra></extra>",
            cliponaxis=False,
        )
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    # Holgura para el rótulo "x de y pts" fuera de la barra en el panel de detalle angosto.
    fig.update_xaxes(range=[0, max([*maxima, 1]) * 2.1], showgrid=False, title_text="puntos")
    return with_disclaimer(
        fig, title=title, height=170 + 48 * max(len(labels), 1), axis_room=56, wrap=34
    )
