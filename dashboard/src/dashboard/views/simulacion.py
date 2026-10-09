"""Simulación: intervalos por política, comparaciones pareadas, cobertura y limitaciones.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Muestra `results/simulation.json` tal como lo entrega la API. Si una política no mejora en una
métrica, la tabla lo dice con las mismas palabras que cuando mejora.

Funciones puras: `interval_rows`, `comparison_rows`, `verdict`, `pair_label`, `fetch_simulation`
y `build_simulation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dash import Input, Output, callback, dcc, html
from dash.development.base_component import Component

from dashboard import fmt, runtime, theme
from dashboard.api_client import ApiClient, ApiError, ApiNotFound
from dashboard.components.charts import interval_chart
from dashboard.components.common import empty_state, field, figure_block, note, section
from dashboard.components.tables import simple_table
from dashboard.session import Session, render_guarded

POLICY_ORDER = ("fifo", "priority", "optimized", "optimized_overbooking")


@dataclass(frozen=True)
class Metric:
    """Métrica de la simulación: clave, nombre, formato y dirección (+1 más es mejor)."""

    key: str
    label: str
    kind: str  # "count", "days" o "fraction"
    direction: int


METRICS: tuple[Metric, ...] = (
    Metric("exits_attended", "Atendidos", "count", 1),
    Metric("wait_attended_median", "Mediana de espera de los atendidos (días)", "days", -1),
    Metric("ges_breached", "GES incumplidas", "count", -1),
    Metric("slot_use_cne_utilization", "Uso de cupos de consulta", "fraction", 1),
    Metric("slot_use_or_utilization", "Uso de pabellón", "fraction", 1),
    Metric("lost_slots_cne_units", "Cupos de consulta perdidos", "count", -1),
    Metric("overflow_affected_patients", "Pacientes afectados por desborde", "count", -1),
)
METRIC_BY_KEY = {m.key: m for m in METRICS}


def metric_value(metric: Metric, value: float | None) -> str:
    """Valor formateado según el tipo de métrica."""
    if value is None:
        return "—"
    if metric.kind == "fraction":
        return fmt.pct(value, 1)
    return fmt.num(value, 1 if metric.kind == "days" else 0)


def interval_rows(aggregate: dict[str, Any], metric_key: str) -> list[dict[str, Any]]:
    """Media e IC 95 % de la métrica por política, en el orden fijo de las políticas."""
    rows = []
    for policy in POLICY_ORDER:
        stats = (aggregate.get(policy) or {}).get(metric_key)
        if stats is None:
            continue
        rows.append(
            {
                "policy": policy,
                "mean": stats["mean"],
                "low": stats["ci95_low"],
                "high": stats["ci95_high"],
            }
        )
    return rows


def pair_label(name: str) -> str:
    """`optimized_vs_fifo` -> `Optimizada frente a orden de llegada`."""
    left, _, right = name.partition("_vs_")
    left_label = theme.SERIES[left].label if left in theme.SERIES else left
    right_label = theme.SERIES[right].label if right in theme.SERIES else right
    return f"{left_label} frente a {right_label[:1].lower() + right_label[1:]}"


def verdict(mean_diff: float, low: float, high: float, direction: int | None) -> str:
    """Lectura honesta: mejora, empeora o sin diferencia clara (IC 95 % que incluye 0)."""
    if direction is None:
        return "Sin dirección definida"
    if low <= 0 <= high:
        return "◷ Sin diferencia clara"
    return "✓ Mejora" if mean_diff * direction > 0 else "● Empeora"


def _is_mirror(name: str, comparisons: dict[str, Any]) -> bool:
    """Si la comparación es el reverso de otra ya presente (se muestra solo la más natural).

    `fifo_vs_priority` es el espejo de `priority_vs_fifo`: se conserva la de la política más
    avanzada contra la base.
    """
    left, _, right = name.partition("_vs_")
    reverse = f"{right}_vs_{left}"
    if reverse not in comparisons or left not in POLICY_ORDER or right not in POLICY_ORDER:
        return False
    return POLICY_ORDER.index(left) < POLICY_ORDER.index(right)


def comparison_rows(
    comparisons: dict[str, Any], metric: Metric, n_replicas: int
) -> list[list[str]]:
    """Filas de la tabla de comparaciones pareadas para la métrica elegida."""
    rows = []
    for name in sorted(comparisons):
        if _is_mirror(name, comparisons):
            continue
        stats = comparisons[name].get(metric.key)
        if stats is None:
            continue
        better = stats.get("better_in")
        rows.append(
            [
                pair_label(name),
                metric_value(metric, stats["mean_diff"]),
                f"{metric_value(metric, stats['ci95_low'])} a "
                f"{metric_value(metric, stats['ci95_high'])}",
                "—" if better is None else f"{better} de {n_replicas}",
                verdict(
                    stats["mean_diff"],
                    stats["ci95_low"],
                    stats["ci95_high"],
                    stats.get("direction"),
                ),
            ]
        )
    return rows


def direction_text(metric: Metric) -> str:
    """Dirección de la métrica escrita ("menos es mejor")."""
    return "más es mejor" if metric.direction > 0 else "menos es mejor"


def coverage_rows(coverage: dict[str, Any]) -> list[list[str]]:
    """Cobertura de la oferta por tipo de atención."""
    return [
        [
            fmt.CARE_LABELS.get(kind, kind),
            fmt.num(c["blocks"]),
            f"{fmt.num(c['cells_with_block'])} de {fmt.num(c['cells'])}",
            fmt.num(c["stock"]),
            fmt.num(c["stock_in_cells_with_block"]),
        ]
        for kind, c in coverage.items()
    ]


@dataclass(frozen=True)
class SimulationData:
    """Resultados de la simulación y la corrida de la lista en uso (para avisar si difieren)."""

    sim: dict[str, Any] | None
    live_run_id: str | None


def fetch_simulation(client: ApiClient, session: Session) -> SimulationData:
    """Lee la simulación (404 = aún no se ejecutó `make simulate`)."""
    try:
        sim: dict[str, Any] | None = client.simulation(session.api_key)
    except ApiNotFound:
        sim = None
    live = None
    try:
        live = client.waitlist_summary(session.api_key).get("run_id")
    except ApiError:
        live = None
    return SimulationData(sim, live)


def build_simulation(data: SimulationData, metric_key: str) -> Component:
    """Página completa para la métrica elegida."""
    sim = data.sim
    if sim is None:
        return empty_state("Todavía no hay resultados de simulación. Ejecuta `make simulate`.")
    metric = METRIC_BY_KEY.get(metric_key, METRICS[0])
    run = sim["run"]
    config = sim["config"]
    n_replicas = len(config.get("replica_seeds", [])) or 1
    intro = (
        f"Simulación de {config['weeks']} semanas con {n_replicas} réplicas sobre la corrida "
        f"{fmt.short_id(run['id'])} ({fmt.num(run['size'])} entradas), generada el "
        f"{fmt.date_es(sim['generated_at'])}."
    )
    blocks: list[Component] = [note(intro, ink=True)]
    if data.live_run_id and data.live_run_id != run["id"]:
        blocks.append(
            note(
                f"Esta simulación se hizo con otra corrida ({fmt.short_id(run['id'])}), "
                "no con la de la lista de espera que ves "
                f"({fmt.short_id(data.live_run_id)}). Sus cifras no se comparan "
                "directamente con la lista.",
                ink=True,
            )
        )
    rows = interval_rows(sim["aggregate"], metric.key)
    fig = interval_chart(
        title=f"{metric.label}: media e intervalo de confianza del 95 % por política",
        rows=rows,
        unit_decimals=1 if metric.kind == "days" else 0,
        percent=metric.kind == "fraction",
        x_title=f"{metric.label} ({direction_text(metric)})",
    )
    aria = f"{metric.label} por política ({direction_text(metric)}): " + "; ".join(
        f"{theme.SERIES[r['policy']].label} {metric_value(metric, r['mean'])}" for r in rows
    )
    blocks.append(
        figure_block(
            fig,
            aria_label=aria,
            headers=["Política", "Media", "IC 95 % inferior", "IC 95 % superior"],
            rows=[
                [
                    theme.SERIES[r["policy"]].label,
                    metric_value(metric, r["mean"]),
                    metric_value(metric, r["low"]),
                    metric_value(metric, r["high"]),
                ]
                for r in rows
            ],
        )
    )
    blocks.append(
        section(
            "Comparaciones pareadas",
            note(
                f"Métrica: {metric.label}. Dirección: {direction_text(metric)}. "
                "La diferencia es la primera política menos la segunda.",
                ink=True,
            ),
            simple_table(
                ["Comparación", "Diferencia media", "IC 95 %", "Réplicas en que mejora", "Lectura"],
                comparison_rows(sim["comparisons"], metric, n_replicas),
                numeric=(1, 2, 3),
            ),
        )
    )
    blocks.append(
        section(
            "Cobertura de la oferta",
            simple_table(
                [
                    "Tipo de atención",
                    "Bloques",
                    "Celdas con bloque",
                    "Entradas en espera",
                    "En celdas con bloque",
                ],
                coverage_rows(sim["supply_coverage"]),
                numeric=(1, 2, 3, 4),
            ),
        )
    )
    blocks.append(
        section("Limitaciones de la simulación", html.Ul([html.Li(t) for t in sim["limitations"]]))
    )
    return html.Div(blocks, className="stack")


def layout() -> Component:
    """Selector de métrica y cuerpo de la página."""
    return html.Div(
        [
            html.Div(
                field(
                    "Métrica",
                    dcc.Dropdown(
                        id="sim-metric",
                        options=[{"label": m.label, "value": m.key} for m in METRICS],
                        value=METRICS[0].key,
                        clearable=False,
                        searchable=False,
                    ),
                    control_id="sim-metric",
                ),
                className="filters",
            ),
            dcc.Loading(
                html.Div(id="sim-body", style={"marginTop": f"{theme.S5}px"}), type="default"
            ),
        ]
    )


@callback(Output("sim-body", "children"), Input("session", "data"), Input("sim-metric", "value"))
def on_simulation(session_data: Any, metric_key: str | None) -> Component | list[Component]:
    """Dibuja la simulación para la métrica elegida."""
    return render_guarded(
        session_data,
        lambda s: build_simulation(
            fetch_simulation(runtime.get_client(), s), metric_key or METRICS[0].key
        ),
    )
