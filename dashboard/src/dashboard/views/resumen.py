"""Resumen de la lista de espera: regla de espera, indicadores, tipos de atención y plan vigente.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Funciones puras: `fetch_resumen` (lectura de la API), `build_resumen` (datos a componentes),
`approver_of` y `current_plan_block`. El callback `on_resumen` solo las encadena.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dash import Input, Output, callback, dcc, html
from dash.development.base_component import Component

from dashboard import fmt, runtime
from dashboard.api_client import ApiClient, ApiNotFound
from dashboard.components.badges import status_badge
from dashboard.components.common import figure_block, kpi, note, section
from dashboard.components.tables import simple_table
from dashboard.components.wait_ruler import wait_ruler_figure
from dashboard.session import Session, render_guarded

GES_RISK_DAYS = 30


@dataclass(frozen=True)
class ResumenData:
    """Lo que necesita la página: resumen agregado, plan vigente y quién lo aprobó."""

    summary: dict[str, Any]
    current_plan: dict[str, Any] | None
    approver: str | None
    approved_at: str | None


def approver_of(reviews: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Usuario y hora de la última aprobación del plan (según la auditoría)."""
    approvals = [r for r in reviews if r.get("action") == "approve"]
    if not approvals:
        return None, None
    last = approvals[-1]
    return last.get("user_name"), last.get("created_at")


def fetch_resumen(client: ApiClient, session: Session) -> ResumenData:
    """Lee el resumen y el plan vigente (404 = no hay plan vigente, no es un error)."""
    summary = client.waitlist_summary(session.api_key)
    try:
        plan: dict[str, Any] | None = client.current_plan(session.api_key)
    except ApiNotFound:
        plan = None
    approver = approved_at = None
    if plan is not None:
        reviews = client.plan_reviews(session.api_key, plan["plan_id"])["items"]
        approver, approved_at = approver_of(reviews)
    return ResumenData(summary, plan, approver, approved_at)


def care_table(summary: dict[str, Any]) -> Component:
    """Tabla por tipo de atención: entradas, mediana, p90 y GES."""
    rows = [
        [
            fmt.CARE_LABELS.get(item["care_type"], item["care_type"]),
            fmt.num(item["total"]),
            fmt.days(item["wait_median"]),
            fmt.days(item["wait_p90"]),
            fmt.num(item["ges_at_risk"]),
            fmt.num(item["ges_overdue"]),
        ]
        for item in summary["by_care_type"]
    ]
    return simple_table(
        [
            "Tipo de atención",
            "Entradas",
            "Mediana de espera",
            "p90 de espera",
            "GES en riesgo",
            "GES vencidas",
        ],
        rows,
        numeric=(1, 2, 3, 4, 5),
    )


def current_plan_block(data: ResumenData) -> Component:
    """Plan vigente con quién lo aprobó y enlace al plan."""
    plan = data.current_plan
    if plan is None:
        return html.P("Todavía no hay un plan vigente.", className="empty")
    citas = plan.get("summary", {}).get("scheduled")
    by = f" por {data.approver}" if data.approver else ""
    when = f" el {fmt.date_es(data.approved_at, year=False)}" if data.approved_at else ""
    return html.Div(
        [
            status_badge("current", "Plan vigente"),
            html.P(
                f"Plan {fmt.short_id(plan['plan_id'])}, aprobado{by}{when}; "
                f"{fmt.num(citas)} citas. ",
                style={"marginTop": "8px"},
            ),
            dcc.Link("Ver plan", href=f"/programacion?plan={plan['plan_id']}"),
        ]
    )


def build_resumen(data: ResumenData) -> Component:
    """Página completa a partir de los datos."""
    s = data.summary
    figure = wait_ruler_figure(
        median=s["wait_median"],
        p90=s["wait_p90"],
        ges_at_risk=s["ges_at_risk"],
        ges_overdue=s["ges_overdue"],
        histogram=s["wait_histogram"],
    )
    aria = (
        f"Regla de espera de 0 a 730 días: mediana {fmt.num(s['wait_median'])} días, "
        f"p90 {fmt.num(s['wait_p90'])} días; {fmt.num(s['ges_at_risk'])} GES en riesgo y "
        f"{fmt.num(s['ges_overdue'])} vencidas."
    )
    table_rows = [
        [
            f"{b['from_day']} a {b['to_day']}" if b["to_day"] is not None else "720 o más",
            fmt.num(b["count"]),
        ]
        for b in s["wait_histogram"]
    ]
    cutoff = fmt.date_es(s["as_of"])
    return html.Div(
        [
            html.Div(
                [
                    html.Span(fmt.num(s["wait_median"]), className="display-number"),
                    html.Span(" días de mediana de espera", style={"marginLeft": "8px"}),
                ],
                style={"marginBottom": "16px"},
            ),
            figure_block(
                figure,
                aria_label=aria,
                headers=["Tramo de espera (días)", "Entradas"],
                rows=table_rows,
            ),
            note(
                f"En riesgo: GES no vencida con plazo en {GES_RISK_DAYS} días o menos desde la "
                f"fecha de corte ({cutoff}). Vencida: plazo anterior a esa fecha. Las entradas "
                "con 720 días o más se agrupan al final de la regla."
            ),
            html.Div(
                [
                    kpi(fmt.num(s["total"]), "Entradas en espera"),
                    kpi(fmt.days(s["wait_median"]), "Mediana de espera"),
                    kpi(fmt.days(s["wait_p90"]), "p90 de espera"),
                    kpi(fmt.num(s["ges_at_risk"]), "GES en riesgo", "risk"),
                    kpi(fmt.num(s["ges_overdue"]), "GES vencidas", "overdue"),
                ],
                className="kpis",
                style={"marginTop": "32px"},
            ),
            html.Div(
                [
                    section("Por tipo de atención", care_table(s)),
                    section("Plan vigente", current_plan_block(data)),
                ],
                className="columns",
            ),
        ]
    )


def layout() -> Component:
    """Contenedor que llena `on_resumen` cuando hay sesión."""
    return dcc.Loading(html.Div(id="resumen-body"), type="default")


def build_for_session(session: Session) -> Component:
    """Lee la API y arma la página; los errores los captura `render_guarded`."""
    return build_resumen(fetch_resumen(runtime.get_client(), session))


@callback(Output("resumen-body", "children"), Input("session", "data"))
def on_resumen(session_data: Any) -> Component | list[Component]:
    """Dibuja el resumen cuando hay sesión."""
    return render_guarded(session_data, build_for_session)
