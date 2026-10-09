"""Lista priorizada: filtros, tabla paginada en el servidor y detalle del puntaje.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La tabla nunca baja la lista completa: cada página son 50 filas pedidas a `GET /v1/waitlist`.
Funciones puras: `build_params`, `resolve_page`, `build_rows`, `ges_state`, `page_count`,
`range_text`, `entry_for_row` y `build_detail`. Los callbacks solo las encadenan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from dash import Input, Output, State, callback, ctx, dcc, html
from dash.development.base_component import Component

from dashboard import fmt, runtime, theme
from dashboard.api_client import ApiClient
from dashboard.components.attrs import aria
from dashboard.components.charts import component_bars
from dashboard.components.common import empty_state, field, figure_block, note
from dashboard.components.tables import server_table
from dashboard.components.wait_ruler import wait_ruler_figure
from dashboard.session import Session, call_guarded, render_guarded

PAGE_SIZE = 50
PRIORITY_NOTE = "La prioridad clínica la definen profesionales; el sistema no la cambia."
GES_RISK_DAYS = 30
BAR_CELLS = 10

COLUMNS: list[dict[str, Any]] = [
    {"name": "Puesto", "id": "rank", "type": "numeric"},
    {"name": "Puntaje", "id": "score", "type": "text"},
    {"name": "Prioridad clínica", "id": "priority", "type": "text"},
    {"name": "Días de espera", "id": "wait_days", "type": "numeric"},
    {"name": "GES", "id": "ges", "type": "text"},
    {"name": "Especialidad", "id": "specialty", "type": "text"},
    {"name": "Servicio", "id": "service", "type": "text"},
]
FILTER_IDS = (
    "f-service",
    "f-specialty",
    "f-care",
    "f-priority",
    "f-ges",
    "f-tier",
    "f-order",
)
GES_STYLES: list[dict[str, Any]] = [
    {
        "if": {"column_id": "ges", "filter_query": '{ges} contains "Vencida"'},
        "color": theme.STATUS["overdue"].text,
        "backgroundColor": theme.STATUS["overdue"].background,
        "fontWeight": 600,
    },
    {
        "if": {"column_id": "ges", "filter_query": '{ges} contains "riesgo"'},
        "color": theme.STATUS["risk"].text,
        "backgroundColor": theme.STATUS["risk"].background,
        "fontWeight": 600,
    },
]
TIER_LABELS = {
    "NONE": "Ninguno",
    "GES_DUE_SOON": "GES por vencer",
    "GES_OVERDUE": "GES vencida",
}


# ------------------------------------------------------------------ funciones puras


def build_params(
    *,
    service: int | None,
    specialty: str | None,
    care: str | None,
    priority: str | None,
    ges: str | None,
    tier: str | None,
    order: str | None,
    page: int,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    """Parámetros de `GET /v1/waitlist` para una página (el servidor pagina y filtra)."""
    params: dict[str, Any] = {
        "limit": page_size,
        "offset": max(page, 0) * page_size,
        "order_by": order or "score",
    }
    if service:
        params["health_service_code"] = int(service)
    if specialty and specialty.strip():
        params["specialty_code"] = specialty.strip()
    if care:
        params["care_type"] = care
    if priority:
        params["clinical_priority"] = priority
    if ges in ("true", "false"):
        params["is_ges"] = ges == "true"
    if tier:
        params["tier"] = tier
    return params


def resolve_page(trigger: str | None, page_current: int | None) -> int:
    """Cambiar un filtro vuelve a la primera página; cambiar de página la respeta."""
    if trigger == "lista-table":
        return page_current or 0
    return 0


def page_count(total: int, size: int = PAGE_SIZE) -> int:
    """Cantidad de páginas (al menos una)."""
    return max(1, -(-total // size))


def range_text(total: int, offset: int, shown: int) -> str:
    """`Mostrando 1 a 50 de 100.000 entradas` (o aviso de vacío)."""
    if total == 0:
        return "Ninguna entrada coincide con los filtros."
    return (
        f"Mostrando {fmt.num(offset + 1)} a {fmt.num(offset + shown)} de {fmt.num(total)} entradas."
    )


def ges_state(is_ges: bool, deadline: str | None, as_of: date) -> str | None:
    """`overdue`, `risk` (plazo en 30 días o menos) o `ges` según el plazo y la fecha de corte."""
    if not is_ges:
        return None
    if deadline is None:
        return "ges"
    left = (date.fromisoformat(deadline) - as_of).days
    if left < 0:
        return "overdue"
    return "risk" if left <= GES_RISK_DAYS else "ges"


def ges_text(state: str | None) -> str:
    """Texto de la columna GES (icono y texto, no solo color)."""
    return {"overdue": "● Vencida", "risk": "▲ En riesgo", "ges": "GES", None: "—"}[state]


def score_bar(score: float) -> str:
    """Barra de bloques de 0 a 100 para la celda (el número va al lado)."""
    filled = round(max(0.0, min(score, 100.0)) / 100 * BAR_CELLS)
    return "█" * filled + "░" * (BAR_CELLS - filled)


def score_bar_styles() -> list[dict[str, Any]]:
    """Barra fina de 0 a 100 al pie de la celda del puntaje (diseño §5: "barra horizontal fina").

    Una regla por tramo de 5 puntos sobre `score_step`; el número queda legible encima.
    """
    styles: list[dict[str, Any]] = []
    for step in range(0, 101, 5):
        width = min(step + 2.5, 100)  # centro del tramo
        styles.append(
            {
                "if": {"filter_query": f"{{score_step}} = {step}", "column_id": "score"},
                "background": (
                    f"linear-gradient(90deg, {theme.SCRUB} {width}%, {theme.RULE} {width}%) "
                    "left bottom / 100% 4px no-repeat"
                ),
            }
        )
    return styles


def build_rows(page: dict[str, Any], as_of: date) -> list[dict[str, Any]]:
    """Filas de la tabla desde una página de `GET /v1/waitlist`."""
    rows: list[dict[str, Any]] = []
    for item in page["items"]:
        state = ges_state(item["is_ges"], item.get("ges_deadline"), as_of)
        rows.append(
            {
                "entry_id": item["entry_id"],
                "patient_id": item["patient_id"],
                "rank": item["rank"],
                "score": fmt.num(item["score"], 1),
                "score_bar": score_bar(item["score"]),
                # Tramo de 5 puntos para la barra fina de la celda del puntaje (no se muestra).
                "score_step": int(max(0.0, min(item["score"], 100.0)) // 5 * 5),
                "priority": str(item["clinical_priority"]).upper(),
                "wait_days": item["wait_days"],
                "ges": ges_text(state),
                "specialty": fmt.humanize(item["specialty_code"]),
                "service": f"SS {item['health_service_code']}",
            }
        )
    return rows


def entry_for_row(patient: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    """Entrada del paciente con ese id (el paciente puede tener varias)."""
    return next((e for e in patient["entries"] if e["entry_id"] == entry_id), None)


def build_detail(entry: dict[str, Any], summary: dict[str, Any]) -> Component:
    """Detalle: desglose del puntaje, nivel estricto, explicación y regla de espera en miniatura."""
    explanation = entry.get("explanation") or {}
    components = entry.get("components") or []
    tier = explanation.get("tier", entry.get("tier", "NONE"))
    reason = explanation.get("tier_reason")
    children: list[Component] = [
        html.H3(f"Entrada {fmt.short_id(entry['entry_id'])}"),
        html.P(
            f"Puesto {fmt.num(entry['rank'])} de {fmt.num(explanation.get('total'))} en su cola; "
            f"puntaje {fmt.num(entry['score'], 1)} de 100. "
            f"Prioridad clínica {str(entry['clinical_priority']).upper()}, "
            "definida por profesionales.",
        ),
    ]
    if components:
        children.append(
            figure_block(
                component_bars(title="Aporte de cada componente al puntaje", components=components),
                aria_label="Desglose del puntaje por componente: "
                + "; ".join(
                    f"{c['label']} {fmt.num(c['contribution'], 1)} puntos" for c in components
                ),
                headers=["Componente", "Valor", "Normalizado", "Peso", "Puntos"],
                rows=[
                    [
                        c["label"],
                        "—" if c["raw_value"] is None else str(c["raw_value"]),
                        fmt.num(c["normalized"], 2),
                        fmt.num(c["weight"], 0),
                        fmt.num(c["contribution"], 1),
                    ]
                    for c in components
                ],
            )
        )
    children.append(
        html.P(
            [
                html.Strong("Nivel estricto GES: "),
                TIER_LABELS.get(tier, str(tier)),
                f". {reason}" if reason else "",
            ]
        )
    )
    lines = explanation.get("lines") or []
    if lines:
        children.append(html.H3("Explicación"))
        children.append(html.Ul([html.Li(line) for line in lines]))
    children.append(html.H3("Dónde cae su espera"))
    ruler = wait_ruler_figure(
        median=summary.get("wait_median"),
        p90=summary.get("wait_p90"),
        entry_wait=entry["wait_days"],
        compact=True,
    )
    children.append(
        figure_block(
            ruler,
            aria_label=(
                f"Regla de espera: esta entrada espera {fmt.num(entry['wait_days'])} días; "
                f"la mediana de la lista es {fmt.num(summary.get('wait_median'))} y el p90 "
                f"{fmt.num(summary.get('wait_p90'))}."
            ),
            headers=["Medida", "Días"],
            rows=[
                ["Esta entrada", fmt.num(entry["wait_days"])],
                ["Mediana de la lista", fmt.num(summary.get("wait_median"))],
                ["p90 de la lista", fmt.num(summary.get("wait_p90"))],
            ],
        )
    )
    return html.Div(children, className="stack")


def fetch_detail(client: ApiClient, session: Session, row: dict[str, Any]) -> Component:
    """Pide paciente y resumen (con caché) y arma el detalle de la fila."""
    patient = client.patient(session.api_key, row["patient_id"])
    entry = entry_for_row(patient, row["entry_id"])
    if entry is None:
        return empty_state("Esa entrada ya no está disponible.")
    summary = client.waitlist_summary(session.api_key)
    return build_detail(entry, summary)


# ------------------------------------------------------------------ componentes


def _dropdown(control_id: str, options: list[dict[str, str]], placeholder: str) -> dcc.Dropdown:
    return dcc.Dropdown(
        id=control_id, options=options, placeholder=placeholder, clearable=True, searchable=False
    )


def layout() -> Component:
    """Filtros, tabla y panel de detalle."""
    filters = html.Div(
        [
            field(
                "Servicio de salud (código)",
                dcc.Input(
                    id="f-service", type="number", min=1, step=1, debounce=True, placeholder="Todos"
                ),
                control_id="f-service",
            ),
            field(
                "Especialidad (código)",
                dcc.Input(id="f-specialty", type="text", debounce=True, placeholder="Todas"),
                control_id="f-specialty",
            ),
            field(
                "Tipo de atención",
                _dropdown(
                    "f-care",
                    [{"label": v, "value": k} for k, v in fmt.CARE_LABELS.items()],
                    "Todos",
                ),
                control_id="f-care",
            ),
            field(
                "Prioridad clínica",
                _dropdown(
                    "f-priority",
                    [{"label": p.upper(), "value": p} for p in ("p1", "p2", "p3", "p4")],
                    "Todas",
                ),
                control_id="f-priority",
            ),
            field(
                "GES",
                _dropdown(
                    "f-ges",
                    [{"label": "Solo GES", "value": "true"}, {"label": "No GES", "value": "false"}],
                    "Todas",
                ),
                control_id="f-ges",
            ),
            field(
                "Nivel estricto GES",
                _dropdown(
                    "f-tier", [{"label": v, "value": k} for k, v in TIER_LABELS.items()], "Todos"
                ),
                control_id="f-tier",
            ),
            field(
                "Ordenar por",
                dcc.Dropdown(
                    id="f-order",
                    # Por defecto, puntaje: el puesto es por cola y en la lista nacional
                    # muchas filas comparten el puesto 1.
                    options=[
                        {"label": "Puntaje", "value": "score"},
                        {"label": "Puesto en su cola", "value": "rank"},
                        {"label": "Fecha de ingreso", "value": "entry_date"},
                    ],
                    value="score",
                    clearable=False,
                    searchable=False,
                ),
                control_id="f-order",
            ),
        ],
        className="filters",
    )
    table = server_table(
        "lista-table",
        COLUMNS,
        page_size=PAGE_SIZE,
        selectable=True,
        right_aligned=("rank", "score", "wait_days"),
        extra_styles=[*GES_STYLES, *score_bar_styles()],
    )
    return html.Div(
        [
            filters,
            html.P(
                id="lista-count", className="note", role="status", style={"margin": "16px 0 8px"}
            ),
            html.Div(id="lista-error"),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Loading(table, type="default"),
                            note(PRIORITY_NOTE, ink=True),
                        ],
                        className="stack",
                    ),
                    html.Div(
                        empty_state("Elige una fila para ver el desglose de su puntaje."),
                        id="lista-detail",
                        className="detail-panel",
                        **aria({"aria-live": "polite"}),
                    ),
                ],
                className="master-detail",
            ),
        ]
    )


# ------------------------------------------------------------------ callbacks


@dataclass(frozen=True)
class ListaPage:
    """Una página lista para la tabla."""

    rows: list[dict[str, Any]]
    pages: int
    text: str


def fetch_lista(client: ApiClient, session: Session, params: dict[str, Any]) -> ListaPage:
    """Pide la página al servidor (más el resumen en caché para la fecha de corte)."""
    data = client.waitlist(session.api_key, params)
    summary = client.waitlist_summary(session.api_key)
    return ListaPage(
        rows=build_rows(data, date.fromisoformat(summary["as_of"])),
        pages=page_count(data["total"]),
        text=range_text(data["total"], params["offset"], len(data["items"])),
    )


@callback(
    Output("lista-table", "data"),
    Output("lista-table", "page_count"),
    Output("lista-table", "page_current"),
    Output("lista-table", "selected_rows"),
    Output("lista-count", "children"),
    Output("lista-error", "children"),
    Input("session", "data"),
    Input("lista-table", "page_current"),
    *[Input(i, "value") for i in FILTER_IDS],
)
def on_lista(session_data: Any, page_current: int | None, *filters: Any) -> tuple[Any, ...]:
    """Pide al servidor la página que corresponde a los filtros."""
    service, specialty, care, priority, ges, tier, order = filters
    page = resolve_page(ctx.triggered_id, page_current)
    params = build_params(
        service=service,
        specialty=specialty,
        care=care,
        priority=priority,
        ges=ges,
        tier=tier,
        order=order,
        page=page,
    )
    result = call_guarded(session_data, lambda s: fetch_lista(runtime.get_client(), s, params))
    if result.value is None:
        return [], 1, 0, [], "", result.error
    return result.value.rows, result.value.pages, page, [], result.value.text, ""


@callback(
    Output("lista-detail", "children"),
    Input("lista-table", "selected_rows"),
    State("lista-table", "data"),
    State("session", "data"),
    prevent_initial_call=True,
)
def on_lista_detail(
    selected: list[int] | None, data: list[dict[str, Any]] | None, session_data: Any
) -> Any:
    """Detalle de la fila elegida (desglose, explicación y regla de espera)."""
    if not selected or not data:
        return empty_state("Elige una fila para ver el desglose de su puntaje.")
    row = data[selected[0]]
    return render_guarded(session_data, lambda s: fetch_detail(runtime.get_client(), s, row))
