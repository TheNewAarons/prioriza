"""La regla de espera: franja de 0 a 730 días con mediana, p90 y plazos GES.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Es el único gesto audaz del panel (`docs/design.md` §2). Arriba, la distribución de la espera
como barras tenues sobre una regla graduada con la mediana y el p90 rotulados; debajo, las GES
en riesgo y vencidas (las vencidas con rayado). En miniatura marca la espera de una entrada.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import fmt, theme
from dashboard.components.charts import with_disclaimer

RULER_MAX = 730
TICKS = (0, 90, 180, 270, 360, 450, 540, 630, 730)


def _clip(value: float) -> float:
    return min(max(value, 0.0), float(RULER_MAX))


def _marker(
    fig: go.Figure,
    *,
    x: float,
    label: str,
    color: str,
    row: int,
    up: bool,
    symbol: str = "triangle-down",
) -> None:
    """Marca un valor sobre la regla con un triángulo y su rótulo (no solo color)."""
    fig.add_trace(
        go.Scatter(
            x=[_clip(x)],
            y=[0],
            mode="markers+text",
            marker={
                "symbol": symbol,
                "size": 14,
                "color": color,
                "line": {"color": theme.SURFACE, "width": 1},
            },
            text=[label],
            textposition="top center" if up else "bottom center",
            textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
            hovertemplate=f"{label}<extra></extra>",
            showlegend=False,
            cliponaxis=False,
        ),
        row=row,
        col=1,
    )


def wait_ruler_figure(
    *,
    median: float | None,
    p90: float | None,
    ges_at_risk: int = 0,
    ges_overdue: int = 0,
    histogram: Sequence[dict[str, Any]] | None = None,
    entry_wait: int | None = None,
    compact: bool = False,
    height: int | None = None,
) -> go.Figure:
    """Figura de la regla de espera.

    `compact` deja solo la regla con la espera de una entrada (`entry_wait`), la mediana y el p90.
    """
    rows = 1 if compact else 2
    fig = make_subplots(
        rows=rows,
        cols=1,
        row_heights=[1.0] if compact else [0.6, 0.4],
        vertical_spacing=0.16,
    )
    # Distribución de la espera: barras tenues; el tramo "720 o más" cae en 720-730.
    if histogram:
        xs = [b["from_day"] + 15 if b["to_day"] is not None else 725 for b in histogram]
        widths = [30 if b["to_day"] is not None else 10 for b in histogram]
        counts = [b["count"] for b in histogram]
        fig.add_trace(
            go.Bar(
                x=xs,
                y=counts,
                width=widths,
                marker={"color": theme.RULE},
                customdata=[
                    f"{b['from_day']} a {b['to_day']} días"
                    if b["to_day"] is not None
                    else "720 o más días"
                    for b in histogram
                ],
                hovertemplate="%{customdata}: %{y:,} entradas<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    # La regla: línea gruesa en y=0 con marcas cada 90 días.
    fig.add_shape(
        type="line",
        x0=0,
        x1=RULER_MAX,
        y0=0,
        y1=0,
        line={"color": theme.INK, "width": 3},
        row=1,
        col=1,
    )
    fig.update_xaxes(
        range=[-6, RULER_MAX + 6],
        tickmode="array",
        tickvals=list(TICKS),
        ticktext=[str(t) if t != RULER_MAX else f"{t} días" for t in TICKS],
        ticks="outside",
        tickcolor=theme.INK,
        ticklen=8,
        row=1,
        col=1,
    )
    max_count = max((b["count"] for b in histogram or []), default=1)
    fig.update_yaxes(
        visible=False,
        range=[-max_count * 0.08, max_count * (1.35 if not compact else 1.5)],
        showgrid=False,
        row=1,
        col=1,
    )
    if median is not None:
        _marker(
            fig, x=median, label=f"▼ {fmt.num(median)} mediana", color=theme.SCRUB, row=1, up=True
        )
    if p90 is not None:
        _marker(fig, x=p90, label=f"▼ {fmt.num(p90)} p90", color=theme.SCRUB, row=1, up=True)
    if entry_wait is not None:
        # Rombo sin texto sobre la regla y rótulo con flecha más arriba que los de mediana y
        # p90: debajo de la regla chocaba con los números del eje.
        _marker(fig, x=entry_wait, label="", color=theme.INK, row=1, up=True, symbol="diamond")
        fig.add_annotation(
            x=_clip(entry_wait),
            y=0,
            text=f"{fmt.num(entry_wait)} días, esta entrada",
            showarrow=True,
            arrowhead=0,
            arrowcolor=theme.INK,
            ax=0,
            ay=-46,
            font={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
            bgcolor=theme.SURFACE,
            row=1,
            col=1,
        )
    if not compact:
        labels = ["▲ GES en riesgo", "● GES vencidas"]
        values = [ges_at_risk, ges_overdue]
        fig.add_trace(
            go.Bar(
                y=labels,
                x=values,
                orientation="h",
                # Riesgo en su tinte con borde; vencidas con rayado en el color del estado: la
                # más grave pesa más a la vista (antes el café sólido de riesgo dominaba).
                marker={
                    "color": [theme.STATUS["risk"].background, theme.STATUS["overdue"].background],
                    "pattern": {
                        "shape": ["", "/"],
                        "fgcolor": [theme.STATUS["risk"].text, theme.STATUS["overdue"].text],
                        "bgcolor": [
                            theme.STATUS["risk"].background,
                            theme.STATUS["overdue"].background,
                        ],
                        "size": 8,
                        "solidity": 0.45,
                    },
                    "line": {
                        "color": [theme.STATUS["risk"].text, theme.STATUS["overdue"].text],
                        "width": 1.5,
                    },
                },
                text=[fmt.num(v) for v in values],
                textposition="outside",
                textfont={"family": theme.FONT_FAMILY, "size": theme.T_SMALL, "color": theme.INK},
                hovertemplate="%{y}: %{x:,}<extra></extra>",
                showlegend=False,
                cliponaxis=False,
            ),
            row=2,
            col=1,
        )
        fig.update_xaxes(visible=False, range=[0, max(max(values), 1) * 1.15], row=2, col=1)
        fig.update_yaxes(
            autorange="reversed",
            showgrid=False,
            tickfont={"color": theme.INK, "size": theme.T_SMALL},
            row=2,
            col=1,
        )
    default_height = 220 if compact else 400
    return with_disclaimer(
        fig,
        title=None,
        height=height or default_height,
        axis_room=44 if compact else 16,
        wrap=34 if compact else 56,
    )
