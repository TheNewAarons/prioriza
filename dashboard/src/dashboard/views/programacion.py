"""Programación: pedir, revisar y decidir planes.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Tres zonas en secuencia: 1) pedir una programación (solo gestor), 2) revisar el plan (calendario
por recurso, GES no cumplidas y explicaciones) y 3) decidir (aprobar o rechazar solo el revisor;
marcar vigente solo el gestor). El sistema apoya, no decide: todo plan nace pendiente y requiere
revisión humana.

Funciones puras: `build_run_request`, `step_jobs`, `plan_options`, `pick_plan`, `build_plan_header`,
`decision_view`, `step_decision`, `prepare_calendar`, `fetch_calendar`, `ges_rows`,
`explanation_rows`, `build_audit` y `request_visibility`. Los callbacks solo las encadenan.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from dash import Input, Output, State, callback, ctx, dcc, html
from dash.development.base_component import Component

from dashboard import fmt, runtime, theme
from dashboard.api_client import (
    ApiClient,
    ApiConflict,
    ApiError,
    ApiForbidden,
    ApiNotFound,
)
from dashboard.components.attrs import aria
from dashboard.components.badges import job_badge, plan_badges
from dashboard.components.charts import calendar_heatmap
from dashboard.components.common import (
    empty_state,
    error_panel,
    field,
    figure_block,
    note,
    ok_panel,
    section,
)
from dashboard.components.tables import server_table, simple_table
from dashboard.session import Session, call_guarded, from_store

POLICY_OPTIONS = [
    {"label": "Orden de llegada", "value": "fifo"},
    {"label": "Solo prioridad", "value": "priority"},
    {"label": "Optimizada", "value": "optimized"},
]
HIDDEN = {"display": "none"}
SHOWN: dict[str, str] = {}
GES_PAGE_SIZE = 10
EXP_PAGE_SIZE = 10
CALENDAR_MAX_ROWS = 40
CALENDAR_MAX_PAGES = 4
MAX_JOBS = 10
TERMINAL = ("succeeded", "failed")
ACTION_LABELS = {
    "approve": "Aprobó el plan",
    "reject": "Rechazó el plan",
    "activate": "Marcó el plan como vigente",
    "deactivate": "Dejó de ser el plan vigente",
}
DECISION_WORDS = {"approved": ("Aprobar", "aprobado"), "rejected": ("Rechazar", "rechazado")}


# ------------------------------------------------------------------ pedir una programación


def request_visibility(role: str | None) -> tuple[dict[str, str], str]:
    """Estilo del formulario y línea explicativa: solo el gestor ve el botón "Programar"."""
    if role == "gestor":
        return SHOWN, ""
    if role is None:
        return HIDDEN, ""
    return (
        HIDDEN,
        f"Tu rol ({role}) no puede programar. Solo un gestor puede pedir una programación.",
    )


def build_run_request(
    policy: str | None,
    weeks: Any,
    overbooking: Sequence[str] | None,
    time_limit_s: Any,
) -> dict[str, Any]:
    """Cuerpo de `POST /v1/schedule-runs`; `ValueError` con un mensaje claro si algo no sirve."""
    if policy not in {o["value"] for o in POLICY_OPTIONS}:
        raise ValueError("Elige una política.")
    try:
        n_weeks = int(weeks)
    except (TypeError, ValueError):
        raise ValueError("Las semanas del horizonte deben ser un número entre 1 y 52.") from None
    if not 1 <= n_weeks <= 52:
        raise ValueError("Las semanas del horizonte deben estar entre 1 y 52.")
    try:
        limit = float(time_limit_s)
    except (TypeError, ValueError):
        raise ValueError("El límite de tiempo del solver debe ser un número.") from None
    if not 0 < limit <= 3600:
        raise ValueError("El límite de tiempo del solver debe estar entre 1 y 3.600.")
    return {
        "policy": policy,
        "horizon_weeks": n_weeks,
        # El sobrecupo solo existe para la política optimizada.
        "overbooking": policy == "optimized" and bool(overbooking),
        "time_limit_s": limit,
    }


def policy_label(policy: str, overbooking: bool | None) -> str:
    """Nombre humano de la política (la optimizada con sobrecupo tiene el suyo)."""
    if policy == "optimized" and overbooking:
        return theme.SERIES["optimized_overbooking"].label
    return (
        theme.SERIES.get(policy, theme.SERIES["fifo"]).label if policy in theme.SERIES else policy
    )


def plan_overbooking(plan: dict[str, Any]) -> bool:
    """Si el plan se calculó con sobrecupo (según la configuración que devolvió la API)."""
    config = plan.get("config") or {}
    enabled = ((config.get("scheduler") or {}).get("overbooking") or {}).get("enabled")
    if enabled is not None:
        return bool(enabled)
    return bool((config.get("request") or {}).get("overbooking"))


@dataclass(frozen=True)
class JobsStep:
    """Resultado de un paso del manejo de trabajos."""

    jobs: list[dict[str, Any]]
    interval_disabled: bool
    message: Component | None
    refresh_plans: bool


def _job_entry(job: dict[str, Any], overbooking: bool) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "policy": job["policy"],
        "overbooking": overbooking,
        "status": job["status"],
        "plan_id": job.get("plan_id"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
    }


def active(jobs: Sequence[dict[str, Any]]) -> bool:
    """Hay trabajos en cola o en curso (el `dcc.Interval` sigue encendido)."""
    return any(j["status"] not in TERMINAL for j in jobs)


def step_jobs(
    trigger: str | None,
    client: ApiClient,
    session: Session,
    jobs: Sequence[dict[str, Any]] | None,
    form: dict[str, Any] | None,
) -> JobsStep:
    """Pide una programación (`prog-submit`) o consulta los trabajos pendientes (el resto).

    El `dcc.Interval` se apaga cuando ya no queda ningún trabajo en cola o en curso.
    """
    current = [dict(j) for j in (jobs or [])]
    message: Component | None = None
    refresh = False
    if trigger == "prog-submit":
        try:
            body = build_run_request(**(form or {}))
            job = client.create_schedule_run(session.api_key, body)
        except ValueError as exc:
            message = error_panel(str(exc))
        except ApiError as exc:
            message = error_panel(exc.message)
        else:
            current.insert(0, _job_entry(job, body["overbooking"]))
            current = current[:MAX_JOBS]
            message = ok_panel("Programación pedida. El plan quedará pendiente de revisión.")
    else:
        for i, job in enumerate(current):
            if job["status"] in TERMINAL:
                continue
            try:
                fresh = client.schedule_run(session.api_key, job["job_id"])
            except ApiNotFound:
                job.update(
                    status="failed",
                    error="La API ya no conoce este trabajo (se reinició). Pídelo de nuevo.",
                )
            except ApiError as exc:
                message = error_panel(exc.message)
                continue
            else:
                refresh = refresh or (fresh["status"] == "succeeded")
                current[i] = _job_entry(fresh, job.get("overbooking", False))
    return JobsStep(current, not active(current), message, refresh)


def build_jobs_list(jobs: Sequence[dict[str, Any]]) -> Component:
    """Trabajos de la sesión con su estado (icono y texto)."""
    if not jobs:
        return empty_state("Todavía no pediste programaciones en esta sesión.")
    items: list[Component] = []
    for job in jobs:
        parts: list[Component | str] = [
            job_badge(job["status"]),
            html.Span(policy_label(job["policy"], job.get("overbooking"))),
            html.Span(fmt.date_es(job.get("created_at"), year=False), className="note"),
        ]
        if job["status"] == "succeeded" and job.get("plan_id"):
            parts.append(dcc.Link("Ver plan", href=f"/programacion?plan={job['plan_id']}"))
        if job["status"] == "failed":
            parts.append(
                html.Span(job.get("error") or "Falló sin mensaje.", className="field-error")
            )
        items.append(html.Li(parts))
    return html.Ul(items, className="job-list")


# ------------------------------------------------------------------ elegir y describir un plan


def plan_options(plans: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Opciones del selector, del más reciente al más antiguo, con el estado en texto e icono."""
    status_text = {
        "pending": f"{theme.STATUS['pending'].icon} Pendiente de revisión",
        "approved": f"{theme.STATUS['ok'].icon} Aprobado",
        "rejected": f"{theme.STATUS['overdue'].icon} Rechazado",
    }
    out = []
    for p in plans:
        label = (
            f"{fmt.short_id(p['plan_id'])}, {policy_label(p['policy'], None)}, "
            f"{fmt.date_es(p['created_at'], year=False)}, "
            f"{status_text.get(p['review_status'], p['review_status'])}"
        )
        if p["is_current"]:
            label += f", {theme.STATUS['current'].icon} Vigente"
        out.append({"label": label, "value": p["plan_id"]})
    return out


def plan_from_search(search: str | None) -> str | None:
    """Id de plan del parámetro `?plan=` de la dirección."""
    if not search:
        return None
    values = parse_qs(search.lstrip("?")).get("plan")
    return values[0] if values else None


def pick_plan(
    options: Sequence[dict[str, str]], current: str | None, from_search: str | None
) -> str | None:
    """Plan seleccionado: el pedido por la dirección, el actual si sigue, o el más reciente."""
    valid = {o["value"] for o in options}
    if from_search in valid:
        return from_search
    if current in valid:
        return current
    return options[0]["value"] if options else None


def build_plan_header(plan: dict[str, Any]) -> Component:
    """Encabezado: política, horizonte, quién lo pidió, estado, vigencia y resumen."""
    summary = plan.get("summary", {})
    ges = plan.get("ges", {})
    label = policy_label(plan["policy"], plan_overbooking(plan))
    facts = [
        ("Política", label),
        (
            "Horizonte",
            f"{fmt.date_es(plan['horizon_start'], year=False)} a "
            f"{fmt.date_es(plan['horizon_end'])}",
        ),
        (
            "Pedido por",
            f"{plan.get('requested_by') or 'sin registro'}, {fmt.date_es(plan['created_at'])}",
        ),
        ("Citas propuestas", fmt.num(summary.get("scheduled"))),
        ("Sobrecupos", fmt.num(summary.get("overbooked_flags"))),
        ("GES con obligación", fmt.num(ges.get("obligated"))),
        ("GES cumplidas", fmt.num(ges.get("met"))),
        ("GES no cumplidas", fmt.num(ges.get("unmet"))),
        ("Estado del solver", str(plan.get("solver_status") or "—")),
    ]
    children: list[Component] = [
        html.Div(
            [
                html.H3(f"Plan {fmt.short_id(plan['plan_id'])}"),
                plan_badges(plan["review_status"], plan["is_current"]),
            ],
            style={
                "display": "flex",
                "gap": f"{theme.S3}px",
                "alignItems": "baseline",
                "flexWrap": "wrap",
            },
        ),
        simple_table(["Dato", "Valor"], [[k, v] for k, v in facts]),
    ]
    warnings = plan.get("warnings") or []
    if warnings:
        children.append(html.H3("Advertencias del programador"))
        children.append(html.Ul([html.Li(w) for w in warnings]))
    children.append(
        note(
            "Este plan es una propuesta del sistema. Requiere revisión humana antes de usarse.",
            ink=True,
        )
    )
    return html.Div(children, className="stack")


# ------------------------------------------------------------------ calendario


def fetch_calendar(
    client: ApiClient,
    session: Session,
    plan_id: str,
    kind: str | None,
    service: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Filas del calendario (hasta `CALENDAR_MAX_PAGES` páginas de 500) y el total del servidor."""
    items: list[dict[str, Any]] = []
    total = 0
    for page in range(CALENDAR_MAX_PAGES):
        params = {
            "limit": 500,
            "offset": page * 500,
            "resource_kind": kind,
            "health_service_code": service,
        }
        data = client.plan_calendar(session.api_key, plan_id, params)
        items.extend(data["items"])
        total = data["total"]
        if len(items) >= total:
            break
    return items, total


@dataclass(frozen=True)
class CalendarData:
    """Calendario listo para dibujar."""

    row_labels: list[str]
    dates: list[str]
    cells: dict[tuple[int, int], dict[str, int]]
    shown_resources: int
    total_resources: int


def prepare_calendar(
    items: Sequence[dict[str, Any]], max_rows: int = CALENDAR_MAX_ROWS
) -> CalendarData:
    """Recursos en filas y días en columnas; se muestran los `max_rows` recursos con más citas."""
    booked: dict[str, int] = {}
    labels: dict[str, str] = {}
    for it in items:
        rid = it["resource_id"]
        booked[rid] = booked.get(rid, 0) + it["scheduled"] + it["overbooked"]
        labels[rid] = f"{it['resource_label']}, SS {it['health_service_code']}"
    chosen = sorted(booked, key=lambda r: (-booked[r], labels[r]))[:max_rows]
    chosen = sorted(chosen, key=lambda r: (labels[r], r))
    row_of = {rid: i for i, rid in enumerate(chosen)}
    dates = sorted({it["date"] for it in items if it["resource_id"] in row_of})
    col_of = {d: i for i, d in enumerate(dates)}
    cells: dict[tuple[int, int], dict[str, int]] = {}
    for it in items:
        if it["resource_id"] not in row_of:
            continue
        key = (row_of[it["resource_id"]], col_of[it["date"]])
        cell = cells.setdefault(key, {"booked": 0, "overbooked": 0, "capacity": 0})
        cell["booked"] += it["scheduled"] + it["overbooked"]
        cell["overbooked"] += it["overbooked"]
        cell["capacity"] += it["capacity"]
    return CalendarData([labels[r] for r in chosen], dates, cells, len(chosen), len(booked))


def build_calendar(data: CalendarData) -> Component:
    """Mapa de calor con su tabla equivalente y las notas de lectura."""
    if not data.cells:
        return empty_state("Este plan no tiene bloques en el horizonte para esos filtros.")
    fig = calendar_heatmap(
        title="Citas por recurso y día",
        row_labels=data.row_labels,
        dates=data.dates,
        cells=data.cells,
    )
    rows = [
        [
            data.row_labels[r],
            fmt.weekday_date(data.dates[c]),
            cell["booked"],
            cell["overbooked"],
            cell["capacity"],
        ]
        for (r, c), cell in sorted(data.cells.items())
    ]
    notes = [
        note(
            "El número es el total de citas del día; +n indica cuántas son sobrecupo "
            "(borde grueso). Capacidad: cupos de 20 minutos en agendas y minutos de pabellón."
        )
    ]
    if data.shown_resources < data.total_resources:
        notes.append(
            note(
                f"Se muestran los {data.shown_resources} recursos con más citas de "
                f"{data.total_resources}. Filtra por servicio de salud para ver otros."
            )
        )
    return html.Div(
        [
            figure_block(
                fig,
                aria_label=(
                    f"Mapa de calor de citas por recurso y día: {data.shown_resources} recursos, "
                    f"{len(data.dates)} días."
                ),
                headers=["Recurso", "Día", "Citas", "Sobrecupos", "Capacidad"],
                rows=rows,
            ),
            *notes,
        ],
        className="stack",
    )


# ------------------------------------------------------------------ GES y explicaciones


def ges_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas de la tabla de garantías GES."""
    return [
        {
            "entry": fmt.short_id(it["entry_id"]),
            "deadline": fmt.date_es(it["ges_deadline"]),
            "state": "✓ Cumplida" if it["met"] else "● No cumplida",
            "cause": "—" if it["met"] else fmt.cause_label(it["cause"]),
            "scheduled": fmt.date_es(it["scheduled_date"]),
            "late": it["days_late"] if it["days_late"] is not None else "—",
            "text": it["text"],
        }
        for it in page["items"]
    ]


def build_cause_summary(by_cause: Sequence[dict[str, Any]]) -> Component:
    """GES no cumplidas agrupadas por causa, con el conteo."""
    if not by_cause:
        return empty_state("Todas las GES del plan quedaron cumplidas.")
    return simple_table(
        ["Causa", "GES no cumplidas"],
        [[fmt.cause_label(c["cause"]), fmt.num(c["count"])] for c in by_cause],
        numeric=(1,),
    )


def explanation_rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Filas de la tabla de explicaciones."""
    return [
        {
            "entry": fmt.short_id(it["entry_id"]),
            "status": fmt.status_label(it["status"]),
            "detail": fmt.cause_label(it["detail"]) if it.get("detail") else "—",
            "text": it["text"],
        }
        for it in page["items"]
    ]


def total_pages(total: int, size: int) -> int:
    """Páginas necesarias (al menos una)."""
    return max(1, -(-total // size))


def resolve_page(trigger: str | None, table_id: str, page_current: int | None) -> int:
    """Cambiar plan o filtro vuelve a la primera página; cambiar de página la respeta."""
    return (page_current or 0) if trigger == table_id else 0


# ------------------------------------------------------------------ decidir


@dataclass(frozen=True)
class DecisionView:
    """Qué controles de decisión se muestran y la línea que explica los que faltan."""

    show_review: bool
    show_activate: bool
    hint: str


def decision_view(role: str, plan: dict[str, Any], user: str) -> DecisionView:
    """Botones según el rol y el estado: los que no se pueden usar no se muestran.

    Donde falta una acción por rol o estado, una línea lo explica.
    """
    status = plan["review_status"]
    requested_by = plan.get("requested_by")
    hints: list[str] = []
    show_review = show_activate = False
    if role == "revisor":
        if status != "pending":
            hints.append("Este plan ya fue revisado; la decisión es final.")
        elif requested_by is None:
            hints.append(
                "Este plan no tiene solicitante registrado; no se puede revisar desde el panel."
            )
        elif requested_by.strip().casefold() == user.strip().casefold():
            hints.append("No puedes revisar un plan que pediste tú (regla de cuatro ojos).")
        else:
            show_review = True
        if status == "approved" and not plan["is_current"]:
            hints.append("Solo un gestor puede marcar un plan como vigente.")
    else:
        hints.append("Solo un revisor puede aprobar o rechazar planes.")
        if role == "gestor":
            if status == "approved" and not plan["is_current"]:
                show_activate = True
            elif plan["is_current"]:
                hints.append("Este plan ya es el vigente.")
            elif status == "pending":
                hints.append("Un plan debe estar aprobado para poder quedar vigente.")
            else:
                hints.append("Un plan rechazado no puede quedar vigente.")
        else:
            hints.append("Solo un gestor puede marcar un plan como vigente.")
    return DecisionView(show_review, show_activate, " ".join(hints))


def confirm_text(action: str | None, plan_id: str | None) -> tuple[dict[str, str], str]:
    """Estilo y texto del panel de confirmación elevado."""
    if action not in DECISION_WORDS or not plan_id:
        return HIDDEN, ""
    verb = DECISION_WORDS[action][0]
    effect = (
        "Aprobar no lo deja vigente: un gestor debe activarlo."
        if action == "approved"
        else "La decisión es final y no se puede deshacer."
    )
    return SHOWN, f"{verb} el plan {fmt.short_id(plan_id)}. {effect}"


@dataclass(frozen=True)
class DecisionStep:
    """Resultado de un paso de decisión."""

    pending: dict[str, str] | None
    message: Component | None
    changed: bool
    clear_note: bool


def step_decision(
    trigger: str | None,
    client: ApiClient,
    session: Session,
    pending: dict[str, str] | None,
    plan_id: str | None,
    note_text: str | None,
) -> DecisionStep:
    """Abre la confirmación, la cancela o ejecuta la decisión (aprobar, rechazar o activar)."""
    if plan_id is None:
        return DecisionStep(None, error_panel("Elige un plan primero."), False, False)
    if trigger == "decide-approve":
        return DecisionStep({"action": "approved"}, None, False, False)
    if trigger == "decide-reject":
        return DecisionStep({"action": "rejected"}, None, False, False)
    if trigger == "decide-cancel":
        return DecisionStep(None, None, False, False)
    text = (note_text or "").strip() or None
    try:
        if trigger == "decide-confirm":
            action = (pending or {}).get("action")
            if action not in DECISION_WORDS:
                return DecisionStep(None, None, False, False)
            client.review_plan(session.api_key, plan_id, action, text)
            msg = ok_panel(f"Plan {DECISION_WORDS[action][1]} por {session.user}.")
            return DecisionStep(None, msg, True, True)
        if trigger == "decide-activate":
            client.activate_plan(session.api_key, plan_id, text)
            return DecisionStep(
                None, ok_panel(f"Plan marcado como vigente por {session.user}."), True, True
            )
    except (ApiForbidden, ApiConflict, ApiNotFound) as exc:
        return DecisionStep(None, error_panel(exc.message), True, False)
    except ApiError as exc:
        return DecisionStep(None, error_panel(exc.message), False, False)
    return DecisionStep(pending, None, False, False)


def build_audit(reviews: Sequence[dict[str, Any]]) -> Component:
    """Auditoría: quién, rol, cuándo y nota de cada acción."""
    if not reviews:
        return empty_state("Este plan todavía no tiene decisiones registradas.")
    return simple_table(
        ["Cuándo", "Quién", "Rol", "Acción", "Nota"],
        [
            [
                fmt.date_es(r["created_at"]),
                r["user_name"],
                r["role"],
                ACTION_LABELS.get(r["action"], r["action"]),
                r.get("note") or "—",
            ]
            for r in reviews
        ],
    )


# ------------------------------------------------------------------ lectura con la API


@dataclass(frozen=True)
class PlanView:
    """Todo lo que necesita el encabezado y la zona de decisión."""

    header: Component
    status_options: list[dict[str, str]]
    decision: DecisionView
    audit: Component


def fetch_plan_view(client: ApiClient, session: Session, plan_id: str) -> PlanView:
    """Lee el plan y su auditoría."""
    plan = client.plan(session.api_key, plan_id)
    reviews = client.plan_reviews(session.api_key, plan_id)["items"]
    statuses = (plan.get("summary") or {}).get("by_status") or {}
    return PlanView(
        header=build_plan_header(plan),
        status_options=[{"label": fmt.status_label(s), "value": s} for s in statuses],
        decision=decision_view(session.role, plan, session.user),
        audit=build_audit(reviews),
    )


# ------------------------------------------------------------------ componentes


def _numeric(control_id: str, value: int, minimum: int, maximum: int) -> dcc.Input:
    return dcc.Input(id=control_id, type="number", value=value, min=minimum, max=maximum, step=1)


def request_form() -> Component:
    """Formulario para pedir una programación (solo gestor)."""
    return html.Div(
        [
            html.Div(
                [
                    field(
                        "Política",
                        dcc.Dropdown(
                            id="prog-policy",
                            options=POLICY_OPTIONS,
                            value="optimized",
                            clearable=False,
                            searchable=False,
                        ),
                        control_id="prog-policy",
                    ),
                    field(
                        "Semanas del horizonte",
                        _numeric("prog-weeks", 4, 1, 52),
                        control_id="prog-weeks",
                    ),
                    html.Div(
                        dcc.Checklist(
                            id="prog-overbooking",
                            options=[{"label": " Sobrecupo controlado", "value": "on"}],
                            value=["on"],
                        ),
                        id="prog-overbooking-wrap",
                        className="field",
                    ),
                    field(
                        "Límite de tiempo del solver",
                        _numeric("prog-limit", 120, 1, 3600),
                        control_id="prog-limit",
                    ),
                ],
                className="filters",
            ),
            html.Button("Programar", id="prog-submit", n_clicks=0, className="btn btn--primary"),
            html.Div(id="prog-job-msg", role="status", **aria({"aria-live": "polite"})),
            html.Div(id="prog-jobs-list"),
        ],
        className="stack",
    )


def plan_section() -> list[Component]:
    """Zona 2: selector de plan, calendario, GES y explicaciones."""
    return [
        field(
            "Plan",
            dcc.Dropdown(
                id="prog-plan",
                options=[],
                placeholder="Elige un plan",
                clearable=False,
                searchable=False,
            ),
            control_id="prog-plan",
        ),
        html.Div(id="prog-plan-empty"),
        html.Div(id="prog-plan-head"),
        html.H3("Calendario por recurso"),
        html.Div(
            [
                field(
                    "Tipo de recurso",
                    dcc.Dropdown(
                        id="cal-kind",
                        options=[{"label": v, "value": k} for k, v in fmt.KIND_LABELS.items()],
                        placeholder="Todos",
                        clearable=True,
                        searchable=False,
                    ),
                    control_id="cal-kind",
                ),
                field(
                    "Servicio de salud (código)",
                    dcc.Input(
                        id="cal-service",
                        type="number",
                        min=1,
                        step=1,
                        debounce=True,
                        placeholder="Todos",
                    ),
                    control_id="cal-service",
                ),
            ],
            className="filters",
        ),
        dcc.Loading(html.Div(id="cal-body"), type="default"),
        html.H3("Garantías GES no cumplidas"),
        html.Div(id="ges-summary"),
        html.Div(
            field(
                "Causa",
                dcc.Dropdown(
                    id="ges-cause",
                    options=[],
                    placeholder="Todas",
                    clearable=True,
                    searchable=False,
                ),
                control_id="ges-cause",
            ),
            className="filters",
        ),
        html.P(id="ges-count", className="note", role="status"),
        server_table(
            "ges-table",
            [
                {"name": "Entrada", "id": "entry"},
                {"name": "Plazo GES", "id": "deadline"},
                {"name": "Estado", "id": "state"},
                {"name": "Causa", "id": "cause"},
                {"name": "Agendada", "id": "scheduled"},
                {"name": "Días de atraso", "id": "late"},
                {"name": "Detalle", "id": "text"},
            ],
            page_size=GES_PAGE_SIZE,
            right_aligned=("late",),
        ),
        html.H3("Explicación por entrada"),
        html.Div(
            field(
                "Estado",
                dcc.Dropdown(
                    id="exp-status",
                    options=[],
                    placeholder="Todos",
                    clearable=True,
                    searchable=False,
                ),
                control_id="exp-status",
            ),
            className="filters",
        ),
        html.P(id="exp-count", className="note", role="status"),
        server_table(
            "exp-table",
            [
                {"name": "Entrada", "id": "entry"},
                {"name": "Estado", "id": "status"},
                {"name": "Detalle", "id": "detail"},
                {"name": "Explicación", "id": "text"},
            ],
            page_size=EXP_PAGE_SIZE,
        ),
    ]


def decide_section() -> list[Component]:
    """Zona 3: aprobar, rechazar o marcar vigente, con confirmación y auditoría."""
    return [
        html.P(id="decide-hint", className="note note--ink"),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Nota (opcional)", htmlFor="decide-note"),
                        dcc.Textarea(
                            id="decide-note",
                            value="",
                            maxLength=2000,
                            style={"width": "100%", "minHeight": "72px"},
                        ),
                    ],
                    className="field",
                ),
                html.Div(
                    [
                        html.Button(
                            "Aprobar plan",
                            id="decide-approve",
                            n_clicks=0,
                            className="btn btn--primary",
                        ),
                        html.Button(
                            "Rechazar plan",
                            id="decide-reject",
                            n_clicks=0,
                            className="btn btn--danger",
                        ),
                    ],
                    id="decide-review-buttons",
                    style={"display": "flex", "gap": f"{theme.S3}px", "marginTop": f"{theme.S3}px"},
                ),
            ],
            id="decide-review-wrap",
            style=HIDDEN,
        ),
        html.Div(
            html.Button(
                "Marcar como vigente",
                id="decide-activate",
                n_clicks=0,
                className="btn btn--primary",
            ),
            id="decide-activate-wrap",
            style=HIDDEN,
        ),
        html.Div(
            [
                html.P(id="confirm-text"),
                html.Div(
                    [
                        html.Button(
                            "Confirmar",
                            id="decide-confirm",
                            n_clicks=0,
                            className="btn btn--primary",
                        ),
                        html.Button(
                            "Cancelar", id="decide-cancel", n_clicks=0, className="btn btn--quiet"
                        ),
                    ],
                    className="actions",
                ),
            ],
            id="confirm-panel",
            className="confirm-panel",
            role="alertdialog",
            style=HIDDEN,
            **aria({"aria-label": "Confirmar decisión"}),
        ),
        html.Div(id="decide-msg", role="status", **aria({"aria-live": "polite"})),
        html.H3("Auditoría"),
        html.Div(id="audit"),
    ]


def layout() -> Component:
    """Las tres zonas numeradas y los almacenes de estado de la página."""
    return html.Div(
        [
            dcc.Store(id="prog-jobs", storage_type="session", data=[]),
            dcc.Store(id="prog-version-jobs", data=0),
            dcc.Store(id="prog-version-decision", data=0),
            dcc.Store(id="prog-pending", data=None),
            dcc.Interval(id="prog-interval", interval=2000, n_intervals=0, disabled=True),
            section(
                "Pedir una programación",
                html.P(id="prog-request-hint", className="note note--ink"),
                html.Div(request_form(), id="prog-request-wrap", style=HIDDEN),
                step=1,
            ),
            section("Revisar el plan", *plan_section(), step=2),
            section("Decidir", *decide_section(), step=3),
        ],
        className="steps",
    )


# ------------------------------------------------------------------ callbacks


@callback(
    Output("prog-request-wrap", "style"),
    Output("prog-request-hint", "children"),
    Input("session", "data"),
)
def on_request_visibility(session_data: Any) -> tuple[dict[str, str], str]:
    """Muestra el formulario solo al gestor; a los demás les explica por qué falta."""
    session = from_store(session_data)
    return request_visibility(session.role if session else None)


@callback(Output("prog-overbooking-wrap", "style"), Input("prog-policy", "value"))
def on_policy_change(policy: str | None) -> dict[str, str]:
    """El sobrecupo solo se ofrece para la política optimizada."""
    return SHOWN if policy == "optimized" else HIDDEN


@callback(
    Output("prog-jobs", "data"),
    Output("prog-interval", "disabled"),
    Output("prog-job-msg", "children"),
    Output("prog-jobs-list", "children"),
    Output("prog-version-jobs", "data"),
    Input("prog-submit", "n_clicks"),
    Input("prog-interval", "n_intervals"),
    Input("session", "data"),
    State("prog-jobs", "data"),
    State("prog-policy", "value"),
    State("prog-weeks", "value"),
    State("prog-overbooking", "value"),
    State("prog-limit", "value"),
    State("prog-version-jobs", "data"),
)
def on_jobs(
    _clicks: int,
    _ticks: int,
    session_data: Any,
    jobs: list[dict[str, Any]] | None,
    policy: str | None,
    weeks: Any,
    overbooking: list[str] | None,
    limit: Any,
    version: int | None,
) -> tuple[Any, ...]:
    """Pide la programación y vigila los trabajos; el intervalo se apaga al terminar."""
    session = from_store(session_data)
    if session is None:
        return [], True, "", "", version or 0
    form = {"policy": policy, "weeks": weeks, "overbooking": overbooking, "time_limit_s": limit}
    step = step_jobs(ctx.triggered_id, runtime.get_client(), session, jobs, form)
    new_version = (version or 0) + (1 if step.refresh_plans else 0)
    return (
        step.jobs,
        step.interval_disabled,
        step.message or "",
        build_jobs_list(step.jobs),
        new_version,
    )


@callback(
    Output("prog-plan", "options"),
    Output("prog-plan", "value"),
    Output("prog-plan-empty", "children"),
    Input("session", "data"),
    Input("prog-version-jobs", "data"),
    Input("prog-version-decision", "data"),
    Input("url", "search"),
    State("prog-plan", "value"),
)
def on_plan_options(
    session_data: Any, _v1: int, _v2: int, search: str | None, current: str | None
) -> tuple[Any, ...]:
    """Lista de planes (los más recientes primero) y plan elegido."""
    result = call_guarded(
        session_data, lambda s: runtime.get_client().plans(s.api_key, {"limit": 50})["items"]
    )
    if result.value is None:
        return [], None, result.error
    options = plan_options(result.value)
    session = from_store(session_data)
    empty: Any = ""
    if not options:
        empty = empty_state(
            "Todavía no hay planes. Pide uno en Programar."
            if session and session.role == "gestor"
            else "Todavía no hay planes."
        )
    return options, pick_plan(options, current, plan_from_search(search)), empty


@callback(
    Output("prog-plan-head", "children"),
    Output("exp-status", "options"),
    Output("decide-review-wrap", "style"),
    Output("decide-activate-wrap", "style"),
    Output("decide-hint", "children"),
    Output("audit", "children"),
    Input("prog-plan", "value"),
    Input("session", "data"),
    Input("prog-version-decision", "data"),
)
def on_plan_head(plan_id: str | None, session_data: Any, _version: int) -> tuple[Any, ...]:
    """Encabezado del plan, controles de decisión según rol y estado, y auditoría."""
    if not plan_id:
        return "", [], HIDDEN, HIDDEN, "", ""
    result = call_guarded(session_data, lambda s: fetch_plan_view(runtime.get_client(), s, plan_id))
    if result.value is None:
        return result.error, [], HIDDEN, HIDDEN, "", ""
    view = result.value
    return (
        view.header,
        view.status_options,
        SHOWN if view.decision.show_review else HIDDEN,
        SHOWN if view.decision.show_activate else HIDDEN,
        view.decision.hint,
        view.audit,
    )


@callback(
    Output("cal-body", "children"),
    Input("prog-plan", "value"),
    Input("cal-kind", "value"),
    Input("cal-service", "value"),
    Input("session", "data"),
)
def on_calendar(
    plan_id: str | None, kind: str | None, service: int | None, session_data: Any
) -> Any:
    """Mapa de calor del plan por recurso y día."""
    if not plan_id:
        return ""

    def build(session: Session) -> CalendarData:
        items, _ = fetch_calendar(runtime.get_client(), session, plan_id, kind, service)
        return prepare_calendar(items)

    result = call_guarded(session_data, build)
    if result.value is None:
        return result.error
    return build_calendar(result.value)


@callback(
    Output("ges-table", "data"),
    Output("ges-table", "page_count"),
    Output("ges-table", "page_current"),
    Output("ges-summary", "children"),
    Output("ges-count", "children"),
    Output("ges-cause", "options"),
    Input("prog-plan", "value"),
    Input("ges-cause", "value"),
    Input("ges-table", "page_current"),
    Input("session", "data"),
)
def on_ges(
    plan_id: str | None, cause: str | None, page_current: int | None, session_data: Any
) -> tuple[Any, ...]:
    """GES no cumplidas del plan por causa, con tabla paginada en el servidor."""
    if not plan_id:
        return [], 1, 0, "", "", []
    page = resolve_page(ctx.triggered_id, "ges-table", page_current)

    def build(session: Session) -> dict[str, Any]:
        params = {
            "met": False,
            "cause": cause,
            "limit": GES_PAGE_SIZE,
            "offset": page * GES_PAGE_SIZE,
        }
        return runtime.get_client().plan_ges(session.api_key, plan_id, params)

    result = call_guarded(session_data, build)
    if result.value is None:
        return [], 1, 0, result.error, "", []
    data = result.value
    options = [
        {"label": fmt.cause_label(c["cause"]), "value": c["cause"]} for c in data["by_cause"]
    ]
    count = f"{fmt.num(data['total'])} garantías GES no cumplidas con ese filtro."
    return (
        ges_rows(data),
        total_pages(data["total"], GES_PAGE_SIZE),
        page,
        build_cause_summary(data["by_cause"]),
        count,
        options,
    )


@callback(
    Output("exp-table", "data"),
    Output("exp-table", "page_count"),
    Output("exp-table", "page_current"),
    Output("exp-count", "children"),
    Input("prog-plan", "value"),
    Input("exp-status", "value"),
    Input("exp-table", "page_current"),
    Input("session", "data"),
)
def on_explanations(
    plan_id: str | None, status: str | None, page_current: int | None, session_data: Any
) -> tuple[Any, ...]:
    """Explicaciones por entrada, filtrables por estado, paginadas en el servidor."""
    if not plan_id:
        return [], 1, 0, ""
    page = resolve_page(ctx.triggered_id, "exp-table", page_current)

    def build(session: Session) -> dict[str, Any]:
        params = {"status": status, "limit": EXP_PAGE_SIZE, "offset": page * EXP_PAGE_SIZE}
        return runtime.get_client().plan_explanations(session.api_key, plan_id, params)

    result = call_guarded(session_data, build)
    if result.value is None:
        return [], 1, 0, "No se pudieron leer las explicaciones."
    data = result.value
    return (
        explanation_rows(data),
        total_pages(data["total"], EXP_PAGE_SIZE),
        page,
        f"{fmt.num(data['total'])} entradas con ese estado.",
    )


@callback(
    Output("prog-pending", "data"),
    Output("decide-msg", "children"),
    Output("prog-version-decision", "data"),
    Output("decide-note", "value"),
    Input("decide-approve", "n_clicks"),
    Input("decide-reject", "n_clicks"),
    Input("decide-activate", "n_clicks"),
    Input("decide-cancel", "n_clicks"),
    Input("decide-confirm", "n_clicks"),
    State("prog-pending", "data"),
    State("prog-plan", "value"),
    State("decide-note", "value"),
    State("session", "data"),
    State("prog-version-decision", "data"),
    prevent_initial_call=True,
)
def on_decision(
    _a: int,
    _r: int,
    _v: int,
    _c: int,
    _ok: int,
    pending: dict[str, str] | None,
    plan_id: str | None,
    note_text: str | None,
    session_data: Any,
    version: int | None,
) -> tuple[Any, ...]:
    """Aprobar o rechazar (con confirmación) y marcar vigente."""
    session = from_store(session_data)
    if session is None:
        return None, error_panel("Entra con tu clave de API."), version or 0, note_text
    step = step_decision(
        ctx.triggered_id, runtime.get_client(), session, pending, plan_id, note_text
    )
    new_version = (version or 0) + (1 if step.changed else 0)
    return step.pending, step.message or "", new_version, "" if step.clear_note else note_text


@callback(
    Output("confirm-panel", "style"),
    Output("confirm-text", "children"),
    Input("prog-pending", "data"),
    State("prog-plan", "value"),
)
def on_confirm_panel(
    pending: dict[str, str] | None, plan_id: str | None
) -> tuple[dict[str, str], str]:
    """Muestra el panel de confirmación elevado mientras haya una decisión por confirmar."""
    return confirm_text((pending or {}).get("action"), plan_id)
