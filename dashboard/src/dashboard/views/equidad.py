"""Equidad: tasas por grupo (edad, previsión, comuna) con rango entre réplicas.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Se mide si el sobreagendamiento perjudica sistemáticamente a algún grupo y se informa tal cual,
también cuando un grupo queda peor. Los grupos fuera de la brecha permitida se marcan con ▲ y
texto. La brecha permitida es una decisión del panel (ver `docs/decisions.md` §15): 5 puntos
porcentuales en tasas y 15 % relativo en la mediana de espera, respecto del total.

Funciones puras: `group_rows`, `reference_values`, `flag_groups`, `reading_sentences`,
`select_groups`, `build_equity` y `fetch_equity`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dash import Input, Output, callback, dcc, html
from dash.development.base_component import Component

from dashboard import fmt, runtime, theme
from dashboard.api_client import ApiNotFound
from dashboard.components.charts import group_dot_chart
from dashboard.components.common import empty_state, field, figure_block, note
from dashboard.session import Session, render_guarded

DIMENSIONS = {
    "age_group": ("Edad", "grupos de edad", "todos los grupos de edad"),
    "insurance": ("Previsión", "grupos de previsión", "todos los grupos de previsión"),
    "commune_code": ("Comuna", "comunas", "todas las comunas"),
}
POLICY_ORDER = ("fifo", "priority", "optimized", "optimized_overbooking")
MAX_GROUPS = 15
# Brecha permitida respecto del total: (tipo, umbral). "pp" = puntos porcentuales (fracción).
GAP_RULES: dict[str, tuple[str, float]] = {
    "attention_rate": ("pp", 0.05),
    "overbooking_exposure": ("pp", 0.05),
    "wait_attended_median": ("rel", 0.15),
}
# +1: valores altos perjudican (espera, exposición); -1: valores bajos perjudican (atención).
HARM_SIGN = {"attention_rate": -1, "overbooking_exposure": 1, "wait_attended_median": 1}
PANELS = (
    ("attention_rate", "Tasa de atención", True, 0),
    ("wait_attended_median", "Mediana de espera (días)", False, 0),
    ("overbooking_exposure", "Exposición al sobrecupo", True, 0),
    ("no_show_realized_rate", "Inasistencia realizada", True, 0),
)


@dataclass(frozen=True)
class GroupRow:
    """Un grupo con sus métricas (media, mínimo y máximo entre réplicas)."""

    value: str
    label: str
    entries: float
    metrics: dict[str, dict[str, float]]


def group_rows(
    equity: dict[str, Any], policy: str, dimension: str
) -> tuple[list[GroupRow], int | None]:
    """Grupos de la política y dimensión, y el mínimo de entradas por grupo de la simulación."""
    dim = (equity.get(policy) or {}).get(dimension)
    if not dim:
        return [], None
    rows = []
    for value, metrics in dim["groups"].items():
        entries = (metrics.get("entries") or {}).get("mean", 0.0)
        rows.append(GroupRow(value, fmt.group_label(dimension, value), entries, metrics))
    return rows, dim.get("min_n")


def reference_values(rows: list[GroupRow]) -> dict[str, float | None]:
    """Total de referencia por métrica: promedio de los grupos ponderado por sus entradas."""
    out: dict[str, float | None] = {}
    for key, _, _, _ in PANELS:
        pairs = [(r.metrics[key]["mean"], r.entries) for r in rows if key in r.metrics]
        weight = sum(w for _, w in pairs)
        out[key] = sum(v * w for v, w in pairs) / weight if weight else None
    return out


def is_outside_gap(metric: str, value: float, reference: float | None) -> bool:
    """Si el grupo queda peor que el total por más de la brecha permitida."""
    rule = GAP_RULES.get(metric)
    if rule is None or reference is None:
        return False
    kind, threshold = rule
    worse = (value - reference) * HARM_SIGN[metric]
    if kind == "rel":
        return reference > 0 and worse / reference > threshold
    return worse > threshold


def flag_groups(rows: list[GroupRow], reference: dict[str, float | None]) -> dict[str, list[str]]:
    """Por grupo, las métricas en que queda fuera de la brecha permitida."""
    return {
        r.value: [
            key
            for key in GAP_RULES
            if key in r.metrics and is_outside_gap(key, r.metrics[key]["mean"], reference.get(key))
        ]
        for r in rows
    }


def select_groups(
    rows: list[GroupRow], flagged: dict[str, list[str]], limit: int = MAX_GROUPS
) -> list[GroupRow]:
    """Hasta `limit` grupos: primero los marcados y luego los más grandes; orden alfabético."""
    ranked = sorted(rows, key=lambda r: (not flagged[r.value], -r.entries, r.label))
    return sorted(ranked[:limit], key=lambda r: r.label)


def _extreme(rows: list[GroupRow], metric: str, highest: bool) -> GroupRow | None:
    pool = [r for r in rows if metric in r.metrics]
    if not pool:
        return None
    pick = max if highest else min
    return pick(pool, key=lambda r: r.metrics[metric]["mean"])


def reading_sentences(
    rows: list[GroupRow],
    flagged: dict[str, list[str]],
    policy: str,
    dimension: str,
    min_n: int | None,
) -> list[str]:
    """Frases de lectura generadas desde los datos, incluidas las que muestran un grupo peor."""
    if not rows:
        return []
    plural, every = DIMENSIONS[dimension][1], DIMENSIONS[dimension][2]
    out: list[str] = []
    top = _extreme(rows, "overbooking_exposure", True)
    low = _extreme(rows, "overbooking_exposure", False)
    if top and low:
        high_v, low_v = (
            top.metrics["overbooking_exposure"]["mean"],
            low.metrics["overbooking_exposure"]["mean"],
        )
        if high_v == 0:
            out.append(
                f"La política {theme.SERIES[policy].label.lower()} no sobreagenda: la "
                f"exposición al sobrecupo es {fmt.pct(0.0)} en {every}."
            )
        else:
            out.append(
                f"La exposición al sobrecupo va de {fmt.pct(low_v)} a {fmt.pct(high_v)} "
                f"entre {plural}; el grupo {top.label} es el más expuesto."
            )
    best, worst = _extreme(rows, "attention_rate", True), _extreme(rows, "attention_rate", False)
    if best and worst:
        out.append(
            f"La tasa de atención va de {fmt.pct(worst.metrics['attention_rate']['mean'])} "
            f"a {fmt.pct(best.metrics['attention_rate']['mean'])}; "
            f"el grupo {worst.label} es el que menos se atiende."
        )
    labels = {r.value: r.label for r in rows}
    bad = [labels[v] for v, ms in flagged.items() if ms]
    if bad:
        out.append(
            f"▲ {len(bad)} de {len(rows)} grupos "
            f"{'queda' if len(bad) == 1 else 'quedan'} fuera de la brecha permitida "
            "respecto del total: "
            + ", ".join(sorted(bad)[:8])
            + ("…" if len(bad) > 8 else "")
            + "."
        )
    else:
        out.append("Ningún grupo queda fuera de la brecha permitida respecto del total.")
    if min_n:
        out.append(f"Los grupos con menos de {fmt.num(min_n)} entradas no se muestran.")
    return out


def _panel(
    key: str,
    title: str,
    percent: bool,
    decimals: int,
    rows: list[GroupRow],
    flags: list[bool],
    reference: float | None,
) -> dict[str, Any]:
    return {
        "title": title,
        "percent": percent,
        "decimals": decimals,
        "values": [
            {k: r.metrics[key][k] for k in ("mean", "min", "max")}
            if key in r.metrics
            else {"mean": 0, "min": 0, "max": 0}
            for r in rows
        ],
        "reference": reference,
        "flags": flags,
    }


def build_equity(equity: dict[str, Any], policy: str, dimension: str) -> Component:
    """Frases de lectura, gráfico de puntos por grupo y tabla equivalente."""
    all_rows, min_n = group_rows(equity, policy, dimension)
    if not all_rows:
        return empty_state("Esta política no tiene resultados de equidad para esa dimensión.")
    reference = reference_values(all_rows)
    flagged = flag_groups(all_rows, reference)
    shown = select_groups(all_rows, flagged)
    flags = [bool(flagged[r.value]) for r in shown]
    panels = [
        _panel(key, title, pct_mode, dec, shown, flags, reference[key])
        for key, title, pct_mode, dec in PANELS
    ]
    sentences = reading_sentences(all_rows, flagged, policy, dimension, min_n)
    fig = group_dot_chart(
        title=(
            f"{DIMENSIONS[dimension][0]}: {theme.SERIES[policy].label}, "
            "media y rango entre réplicas"
        ),
        panels=panels,
        labels=[r.label for r in shown],
    )
    table_rows = [
        [
            ("▲ " if flagged[r.value] else "") + r.label,
            fmt.num(r.entries),
            *[
                (fmt.pct(r.metrics[k]["mean"]) if pct_mode else fmt.num(r.metrics[k]["mean"], 1))
                if k in r.metrics
                else "—"
                for k, _, pct_mode, _ in PANELS
            ],
        ]
        for r in shown
    ]
    blocks: list[Component] = [
        html.P(s, className="note note--ink", style={"maxWidth": "none"}) for s in sentences
    ]
    blocks.append(
        figure_block(
            fig,
            aria_label="Tasas por grupo: " + " ".join(sentences),
            headers=["Grupo", "Entradas", *[title for _, title, _, _ in PANELS]],
            rows=table_rows,
        )
    )
    notes = [
        "La línea punteada es el total de los grupos, ponderado por sus entradas. Cada punto "
        "es la media entre réplicas y la barra, el mínimo y el máximo.",
        "▲ marca un grupo que queda peor que el total por más de 5 puntos porcentuales en "
        "tasa de atención o en exposición al sobrecupo, o por más de 15 % en la mediana "
        "de espera.",
    ]
    if len(all_rows) > len(shown):
        notes.append(
            f"Se muestran {len(shown)} de {len(all_rows)} grupos: los marcados y los más grandes."
        )
    blocks.extend(note(t) for t in notes)
    return html.Div(blocks, className="stack")


def fetch_equity(client: Any, session: Session) -> dict[str, Any] | None:
    """Equidad de la simulación; `None` si todavía no se ejecutó."""
    try:
        sim: dict[str, Any] = client.simulation(session.api_key)
    except ApiNotFound:
        return None
    equity: dict[str, Any] = sim.get("equity") or {}
    return equity


def layout() -> Component:
    """Selectores de política y dimensión, y cuerpo de la página."""
    return html.Div(
        [
            html.Div(
                [
                    field(
                        "Política",
                        dcc.Dropdown(
                            id="eq-policy",
                            options=[
                                {"label": theme.SERIES[p].label, "value": p} for p in POLICY_ORDER
                            ],
                            value="optimized_overbooking",
                            clearable=False,
                            searchable=False,
                        ),
                        control_id="eq-policy",
                    ),
                    field(
                        "Dimensión",
                        dcc.Dropdown(
                            id="eq-dimension",
                            options=[{"label": v[0], "value": k} for k, v in DIMENSIONS.items()],
                            value="age_group",
                            clearable=False,
                            searchable=False,
                        ),
                        control_id="eq-dimension",
                    ),
                ],
                className="filters",
            ),
            dcc.Loading(
                html.Div(id="eq-body", style={"marginTop": f"{theme.S5}px"}), type="default"
            ),
        ]
    )


def build_for_session(session: Session, policy: str, dimension: str) -> Component:
    """Lee la simulación y arma la página."""
    equity = fetch_equity(runtime.get_client(), session)
    if equity is None:
        return empty_state("Todavía no hay resultados de simulación. Ejecuta `make simulate`.")
    return build_equity(equity, policy, dimension)


@callback(
    Output("eq-body", "children"),
    Input("session", "data"),
    Input("eq-policy", "value"),
    Input("eq-dimension", "value"),
)
def on_equity(
    session_data: Any, policy: str | None, dimension: str | None
) -> Component | list[Component]:
    """Dibuja la equidad de la política y dimensión elegidas."""
    return render_guarded(
        session_data,
        lambda s: build_for_session(s, policy or "optimized_overbooking", dimension or "age_group"),
    )
