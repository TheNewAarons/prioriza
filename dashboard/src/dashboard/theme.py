"""Tokens de diseño en Python y plantilla Plotly `prioriza` (ver `docs/design.md` §3 y §6).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Las mismas cifras viven en `assets/tokens.css`. Ningún otro archivo escribe un color o una
medida suelta: se importan desde aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import plotly.graph_objects as go
import plotly.io as pio

# --- Color -------------------------------------------------------------------------------------
PAPER: Final = "#F6F8F7"
SURFACE: Final = "#FFFFFF"
ZONE: Final = "#E9EFED"
INK: Final = "#1C2B2E"
INK_MUTED: Final = "#4B5B5F"
RULE: Final = "#C9D3D1"
SCRUB: Final = "#17655F"
SCRUB_DEEP: Final = "#0E4743"
SCRUB_TINT: Final = "#D7EAE7"

FONT_FAMILY: Final = (
    '"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", system-ui, -apple-system, '
    '"Segoe UI", sans-serif'
)
FONT_URL: Final = (
    "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:"
    "wght@400;600;700&display=swap"
)

# --- Tipografía (px) ---------------------------------------------------------------------------
T_DISPLAY: Final = 39
T_H1: Final = 31
T_H2: Final = 25
T_H3: Final = 20
T_BODY: Final = 16
T_SMALL: Final = 13

# --- Espaciado (px) ----------------------------------------------------------------------------
S1, S2, S3, S4, S5, S6, S7, S8 = 4, 8, 12, 16, 24, 32, 48, 64
STRIP_HEIGHT: Final = 40
SIDEBAR_WIDTH: Final = 232
CONTENT_MAX: Final = 1280


@dataclass(frozen=True)
class StatusStyle:
    """Estilo de un estado: texto, fondo, icono y nombre en español."""

    text: str
    background: str
    icon: str
    label: str


# Los estados siempre se muestran con icono y texto, nunca solo con color.
STATUS: Final[dict[str, StatusStyle]] = {
    "ok": StatusStyle("#235C33", "#DDEFE2", "✓", "Cumplida"),
    "pending": StatusStyle("#2D4A6B", "#DFE8F2", "◷", "Pendiente"),
    "risk": StatusStyle("#7A4300", "#FBE7C6", "▲", "En riesgo"),
    "overdue": StatusStyle("#9B2318", "#F9DFDB", "●", "Vencida"),
    "current": StatusStyle("#FFFFFF", "#17655F", "★", "Vigente"),
}


@dataclass(frozen=True)
class SeriesStyle:
    """Estilo de una política: color Okabe-Ito, marcador y línea propios."""

    label: str
    color: str
    marker: str
    dash: str


SERIES: Final[dict[str, SeriesStyle]] = {
    "fifo": SeriesStyle("Orden de llegada", "#6E6E6E", "circle-open", "dot"),
    "priority": SeriesStyle("Solo prioridad", "#0072B2", "square", "solid"),
    "optimized": SeriesStyle("Optimizada", "#009E73", "diamond", "solid"),
    "optimized_overbooking": SeriesStyle(
        "Optimizada con sobrecupo", "#D55E00", "triangle-up", "dash"
    ),
}

SHADOW_ELEVATED: Final = "0 8px 24px rgba(28,43,46,.18)"
AXIS_FONT: Final[dict[str, Any]] = {"family": FONT_FAMILY, "size": T_SMALL, "color": INK_MUTED}

TEMPLATE_NAME: Final = "prioriza"


def build_template() -> go.layout.Template:
    """Plantilla Plotly: fuente de 13 px, ejes en `INK_MUTED`, grilla horizontal, fondo blanco."""
    template = go.layout.Template()
    template.layout = go.Layout(
        font={"family": FONT_FAMILY, "size": T_SMALL, "color": INK_MUTED},
        title={
            "font": {"family": FONT_FAMILY, "size": T_H3, "color": INK},
            "x": 0,
            "xanchor": "left",
        },
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin={"l": 16, "r": 24, "t": 64, "b": 16, "pad": 4},
        xaxis={
            "showgrid": False,
            "zeroline": False,
            "linecolor": RULE,
            "tickfont": AXIS_FONT,
            "automargin": True,
        },
        yaxis={
            "showgrid": True,
            "gridcolor": RULE,
            "zeroline": False,
            "linecolor": RULE,
            "tickfont": AXIS_FONT,
            "automargin": True,
        },
        legend={
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1.02,
            "yanchor": "bottom",
            "font": {"family": FONT_FAMILY, "size": T_SMALL, "color": INK},
        },
        hovermode="closest",
        hoverlabel={"font": {"family": FONT_FAMILY, "size": T_SMALL}},
    )
    return template


# Solo la descarga de imagen en la barra de herramientas (design.md §6).
GRAPH_CONFIG: Final[Any] = {
    "displaylogo": False,
    "displayModeBar": "hover",
    "modeBarButtonsToRemove": [
        "zoom2d",
        "pan2d",
        "select2d",
        "lasso2d",
        "zoomIn2d",
        "zoomOut2d",
        "autoScale2d",
        "resetScale2d",
        "hoverClosestCartesian",
        "hoverCompareCartesian",
        "toggleSpikelines",
    ],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


def register_template() -> None:
    """Registra `prioriza` como plantilla por defecto de Plotly (idempotente)."""
    pio.templates[TEMPLATE_NAME] = build_template()
    pio.templates.default = TEMPLATE_NAME


register_template()
