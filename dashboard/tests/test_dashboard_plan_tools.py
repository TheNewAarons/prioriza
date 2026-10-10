"""Descargar, comparar y explicar planes en la vista Programación, más sus callbacks (P18-D).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

La API se reemplaza por `httpx.MockTransport`; los callbacks se invocan como funciones con un
contexto de Dash simulado. Todos los ids, usuarios y claves son inventados.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from dash import dcc, no_update
from dash._callback_context import context_value
from dash._utils import AttributeDict
from dash.development.base_component import Component
from dashboard.api_client import ApiClient
from dashboard.session import Session
from dashboard.views import programacion as prog

from dashboard import fmt, runtime

NB = fmt.NBSP
KEY = "clave-sintetica-no-real-456"
PLAN_A = "aaaaaaaa-0000-0000-0000-000000000001"
PLAN_B = "bbbbbbbb-0000-0000-0000-000000000002"
ENTRY = "entry-0001-sintetica"
SESSION = {"api_key": KEY, "user": "ana.sintetica", "role": "gestor"}


class Api:
    """API falsa mínima con rutas fijas o calculadas."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[httpx.Request] = []

    def on(
        self, method: str, path: str, status: int = 200, body: Any = None, text: str = ""
    ) -> None:
        if text:
            self.routes[(method, path)] = lambda _r: httpx.Response(status, text=text)
        else:
            self.routes[(method, path)] = lambda _r: httpx.Response(status, json=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get((request.method, request.url.path))
        return route(request) if route else httpx.Response(404, json={"detail": "Not Found"})

    def client(self) -> ApiClient:
        return ApiClient("http://api.test", transport=httpx.MockTransport(self.handle))


@contextmanager
def triggered(prop_id: str | None) -> Iterator[None]:
    """Contexto de callback de Dash con el disparador dado (`ctx.triggered_id`)."""
    inputs = [{"prop_id": prop_id, "value": 1}] if prop_id else []
    token = context_value.set(AttributeDict(triggered_inputs=inputs))
    try:
        yield
    finally:
        context_value.reset(token)


@pytest.fixture(autouse=True)
def _callback_context() -> Iterator[None]:
    """Contexto de Dash por defecto (sin disparador) para invocar los callbacks directo."""
    with triggered(None):
        yield


@pytest.fixture
def api() -> Iterator[Api]:
    fake = Api()
    runtime.set_client(fake.client())
    yield fake
    runtime.set_client(None)


def text_of(node: Any) -> str:
    out: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, list | tuple):
            for i in n:
                walk(i)
        elif isinstance(n, Component):
            walk(getattr(n, "children", None))

    walk(node)
    return " ".join(out)


def ids_of(node: Any) -> set[str]:
    found: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, list | tuple):
            for i in n:
                walk(i)
        elif isinstance(n, Component):
            if isinstance(getattr(n, "id", None), str):
                found.add(n.id)
            walk(getattr(n, "children", None))

    walk(node)
    return found


# ------------------------------------------------------------------ cuerpos de la API


def side(
    plan_id: str, policy: str, status: str = "pending", current: bool = False
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "policy": policy,
        "review_status": status,
        "is_current": current,
        "created_at": "2026-10-05T12:00:00Z",
        "requested_by": "gestor.sintetico",
        "solver_status": "OPTIMAL",
    }


def metric(
    key: str, label: str, a: float | None, b: float | None, direction: str, better: str
) -> dict[str, Any]:
    diff = None if a is None or b is None else b - a
    return {
        "key": key,
        "label": label,
        "direction": direction,
        "a": a,
        "b": b,
        "diff": diff,
        "better": better,
    }


def compare_body() -> dict[str, Any]:
    return {
        "run_id": "run-sintetica",
        "a": side(PLAN_A, "fifo"),
        "b": side(PLAN_B, "optimized", "approved", True),
        "metrics": [
            metric("scheduled", "Citas agendadas", 100, 120, "higher_is_better", "b"),
            metric("ges_unmet", "GES no cumplidas", 5, 9, "lower_is_better", "a"),
            metric("ges_met", "GES cumplidas", 7, 7, "higher_is_better", "tie"),
            metric("overbooked_flags", "Citas en sobrecupo", 0, 12, "neutral", "none"),
            metric(
                "max_overflow_risk", "Riesgo máximo de desborde", 0.0, 0.11, "lower_is_better", "a"
            ),
        ],
        "equity": [
            {
                **metric(
                    "scheduled_rate", "Tasa de agendamiento", 0.5, 0.6, "higher_is_better", "b"
                ),
                "dimension": "age_group",
                "value": "0_14",
            },
            {
                **metric(
                    "exposure_share", "Exposición al sobrecupo", 0.1, 0.3, "lower_is_better", "a"
                ),
                "dimension": "insurance",
                "value": "fonasa_a",
            },
        ],
        "disclaimer": "x",
    }


def reason_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "plan_id": PLAN_A,
        "entry_id": ENTRY,
        "policy": "optimized",
        "status": "scheduled",
        "detail": "added_by_overbooking",
        "text": "Agendada el 2026-10-14 a las 09:00. Puntaje P4 87,3 (puesto 4 en su cola).",
        "phase": "3b",
        "assignment": {
            "entry_id": ENTRY,
            "patient_id": "pac-0001",
            "slot_id": "slot-12345678-xyz",
            "specialty_code": "cne_medical:medicina_interna",
            "scheduled_start": "2026-10-14T12:00:00Z",
            "duration_min": 20,
            "lead_days": 13,
            "is_overbooked": True,
            "predicted_noshow_prob": 0.18,
        },
        "block_load": {"capacity": 4, "scheduled": 5, "overbooked": 1, "risk_exact": 0.07},
        "ges": {
            "entry_id": ENTRY,
            "obligation": "deadline",
            "ges_deadline": "2026-10-20",
            "met": False,
            "on_time": False,
            "scheduled_date": "2026-10-25",
            "days_late": 5,
            "first_possible_date": "2026-10-14",
            "cause": "capacity_taken",
            "text": "x",
        },
        "score": {
            "patient_id": "pac-0001",
            "clinical_priority": "p1",
            "is_ges": True,
            "ges_deadline": "2026-10-20",
            "entry_date": "2025-12-01",
            "wait_days": 310,
            "score": 87.3,
            "rank": 4,
            "tier": "NONE",
            "explanation": {"lines": ["Prioridad P1 aporta 40 puntos."]},
            "components": [
                {
                    "field": "clinical_priority",
                    "label": "Prioridad clínica",
                    "raw_value": "p1",
                    "normalized": 1.0,
                    "weight": 40.0,
                    "contribution": 40.0,
                }
            ],
        },
        "disclaimer": "x",
    }
    body.update(over)
    return body


# ------------------------------------------------------------------ cliente y descarga


def test_client_export_sends_key_in_header_and_returns_text() -> None:
    fake = Api()
    fake.on("GET", f"/v1/plans/{PLAN_A}/export", text="# aviso: x\nEntrada\n")
    text = fake.client().plan_export_csv(KEY, PLAN_A)
    assert text.startswith("# aviso")
    sent = fake.calls[0]
    assert sent.headers["X-API-Key"] == KEY
    assert KEY not in str(sent.url)
    assert sent.url.params["format"] == "csv"


def test_step_export_ok_and_errors() -> None:
    fake = Api()
    fake.on("GET", f"/v1/plans/{PLAN_A}/export", text="# aviso: x\n")
    ok = prog.step_export(fake.client(), Session(KEY, "u", "lectura"), PLAN_A)
    assert (
        ok.filename == "plan-aaaaaaaa.csv" and ok.content == "# aviso: x\n" and ok.message is None
    )
    none = prog.step_export(fake.client(), Session(KEY, "u", "lectura"), None)
    assert none.content is None and "Elige un plan" in text_of(none.message)
    broken = Api()
    broken.on("GET", f"/v1/plans/{PLAN_A}/export", status=404, body={"detail": "no existe el plan"})
    bad = prog.step_export(broken.client(), Session(KEY, "u", "lectura"), PLAN_A)
    assert bad.content is None and "no existe el plan" in text_of(bad.message)


def test_on_download_returns_file_and_message(api: Api) -> None:
    api.on("GET", f"/v1/plans/{PLAN_A}/export", text="# aviso: x\nEntrada\n")
    data, msg = prog.on_download(1, PLAN_A, SESSION)
    assert data == {
        "content": "# aviso: x\nEntrada\n",
        "filename": "plan-aaaaaaaa.csv",
        "type": "text/csv",
    }
    assert msg == ""
    missing, error = prog.on_download(1, None, SESSION)
    assert missing is no_update and "Elige un plan" in text_of(error)
    nosession, error2 = prog.on_download(1, PLAN_A, None)
    assert nosession is no_update and "clave" in text_of(error2)


def test_layout_has_download_compare_and_reason_controls() -> None:
    ids = ids_of(prog.layout())
    assert {"prog-download-btn", "prog-download", "cmp-a", "cmp-b", "cmp-body", "why-body"} <= ids
    assert {"exp-table", "ges-table"} <= ids


# ------------------------------------------------------------------ comparar


def test_compare_value_and_diff_formats() -> None:
    assert prog.compare_value("scheduled", 1234) == "1.234"
    assert prog.compare_value("scheduled_rate", 0.5) == f"50,0{NB}%"
    assert prog.compare_value("scheduled", None) == "—"
    assert prog.compare_diff("scheduled", 20) == "+20"
    assert prog.compare_diff("scheduled", -3) == "-3"
    assert prog.compare_diff("scheduled", 0) == "0"
    assert prog.compare_diff("exposure_share", 0.2) == f"+20,0{NB}pp"
    assert prog.compare_diff("exposure_share", None) == "—"


def test_compare_sentence_counts_unfavourable_results() -> None:
    sentence = prog.compare_sentence(compare_body())
    assert "mejor en 1, peor en 2 e igual en 1" in sentence
    assert "Por grupo, es mejor en 1 comparaciones, peor en 1" in sentence
    no_equity = prog.compare_sentence({**compare_body(), "equity": []})
    assert "Ninguno de los dos planes trae equidad por grupo" in no_equity


def test_build_compare_shows_both_plans_and_unfavourable_first() -> None:
    node = prog.build_compare(compare_body())
    text = text_of(node)
    assert "Plan A" in text and "Plan B" in text
    assert "Orden de llegada" in text and "Optimizada" in text
    assert "Peor en B" in text and "Mejor en B" in text and "Solo informa" in text
    assert "Vigente" in text
    # Equidad: lo desfavorable para B va primero y los grupos tienen nombre legible.
    assert text.index("Previsión") < text.index("Grupo etario")
    assert "Fonasa A" in text and "0-14" in text
    assert f"+20,0{NB}pp" in text


def test_build_compare_caps_equity_rows_and_says_so() -> None:
    body = compare_body()
    body["equity"] = [
        {**body["equity"][0], "value": f"g{i:04d}", "dimension": "commune_code"} for i in range(400)
    ]
    text = text_of(prog.build_compare(body))
    assert f"Se muestran las primeras {prog.EQUITY_MAX_ROWS}" in text
    assert "400 comparaciones" in text


def test_build_compare_without_equity_has_no_equity_section() -> None:
    text = text_of(prog.build_compare({**compare_body(), "equity": []}))
    assert "Equidad por grupo (" not in text


def test_compare_defaults_keep_valid_choices() -> None:
    options = [{"label": "n", "value": PLAN_B}, {"label": "o", "value": PLAN_A}]
    assert prog.compare_defaults(options, None, None) == (PLAN_A, PLAN_B)
    assert prog.compare_defaults(options, PLAN_B, PLAN_A) == (PLAN_B, PLAN_A)
    assert prog.compare_defaults(options, "otro", "otro") == (PLAN_A, PLAN_B)
    assert prog.compare_defaults(options[:1], None, None) == (None, None)


def test_on_compare_options_and_body(api: Api) -> None:
    options = [{"label": "n", "value": PLAN_B}, {"label": "o", "value": PLAN_A}]
    opts_a, opts_b, a, b = prog.on_compare_options(options, None, None)
    assert opts_a == opts_b == options and (a, b) == (PLAN_A, PLAN_B)
    assert prog.on_compare_options(None, None, None) == ([], [], None, None)

    api.on("GET", "/v1/plans/compare", body=compare_body())
    out = prog.on_compare(PLAN_A, PLAN_B, SESSION)
    assert "Citas agendadas" in text_of(out)
    assert api.calls[0].url.params["a"] == PLAN_A and api.calls[0].url.params["b"] == PLAN_B
    assert "al menos dos planes" in text_of(prog.on_compare(None, PLAN_B, SESSION))
    assert "clave" in text_of(prog.on_compare(PLAN_A, PLAN_B, None))


def test_on_compare_shows_api_error_for_different_runs(api: Api) -> None:
    api.on(
        "GET",
        "/v1/plans/compare",
        status=422,
        body={"detail": "los planes son de corridas distintas; no se pueden comparar"},
    )
    out = prog.on_compare(PLAN_A, PLAN_B, SESSION)
    assert "corridas distintas" in text_of(out)


# ------------------------------------------------------------------ por qué este cupo


def test_selected_entry() -> None:
    rows = [{"entry_id": "e1"}, {"entry_id": "e2"}, {"entry": "sin-id"}]
    assert prog.selected_entry(rows, [1]) == "e2"
    assert prog.selected_entry(rows, []) is None
    assert prog.selected_entry(rows, None) is None
    assert prog.selected_entry(None, [0]) is None
    assert prog.selected_entry(rows, [7]) is None
    assert prog.selected_entry(rows, [2]) is None


def test_reason_facts_full() -> None:
    facts = dict((k, v) for k, v in prog.reason_facts(reason_body()))
    assert "entró gracias al sobreagendamiento" in facts["Estado en el plan"]
    assert facts["Puntaje"].startswith("87,3 de 100, puesto 4")
    assert (
        "P1" in facts["Prioridad clínica"]
        and "el sistema no la cambia" in facts["Prioridad clínica"]
    )
    assert (
        "no cumplida (Cupos tomados)" in facts["Plazo GES"]
        and "5 días de atraso" in facts["Plazo GES"]
    )
    assert facts["Fase en que se agendó"].startswith("Fase 3b")
    assert "14 oct 2026 12:00 UTC" in facts["Cita"]
    assert facts["Sobrecupo"].startswith("Sí")
    assert facts["Riesgo de inasistencia estimado"] == f"18,0{NB}%"
    assert f"7,0{NB}%" in facts["Riesgo de desborde de la sesión"]
    assert "capacidad 4" in facts["Riesgo de desborde de la sesión"]


def test_reason_facts_unscheduled_without_extras() -> None:
    body = reason_body(
        status="capacity_taken",
        detail=None,
        phase=None,
        assignment=None,
        block_load=None,
        ges=None,
        score=None,
    )
    facts = dict((k, v) for k, v in prog.reason_facts(body))
    assert facts["Fase en que se agendó"] == "No quedó agendada en este plan"
    assert "Sin obligación GES" in facts["Plazo GES"]
    assert "ya no está en la lista de espera" in facts["Puntaje"]
    assert "Cita" not in facts and "Sobrecupo" not in facts


def test_reason_facts_met_ges_without_probability_or_block() -> None:
    body = reason_body(detail=None, phase="fifo", block_load=None)
    body["ges"] = {**body["ges"], "met": True, "days_late": 0, "cause": None}
    body["assignment"] = {
        **body["assignment"],
        "is_overbooked": False,
        "predicted_noshow_prob": None,
    }
    facts = dict((k, v) for k, v in prog.reason_facts(body))
    assert facts["Plazo GES"].endswith("cumplida")
    assert facts["Sobrecupo"] == "No"
    assert facts["Riesgo de inasistencia estimado"] == "—"
    assert facts["Fase en que se agendó"].startswith("Orden de llegada")
    assert "Riesgo de desborde de la sesión" not in facts


def test_build_reason_has_text_table_chart_and_review_note() -> None:
    node = prog.build_reason(reason_body())
    text = text_of(node)
    assert "Agendada el 2026-10-14" in text
    assert "Prioridad P1 aporta 40 puntos." in text
    assert "la decisión final es de una persona" in text
    assert any(isinstance(n, dcc.Graph) for n in _walk(node))
    no_score = text_of(prog.build_reason(reason_body(score=None)))
    assert "Aporte de cada componente" not in no_score


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, list | tuple):
        for i in node:
            yield from _walk(i)
    elif isinstance(node, Component):
        yield from _walk(getattr(node, "children", None))


def test_on_reason_picks_the_selected_entry(api: Api) -> None:
    api.on("GET", f"/v1/plans/{PLAN_A}/entries/{ENTRY}/reason", body=reason_body())
    exp_rows = [{"entry_id": ENTRY}]
    with triggered("exp-table.selected_rows"):
        out = prog.on_reason([0], [], PLAN_A, exp_rows, [], SESSION)
    assert "Por qué esta entrada" in text_of(out)
    assert api.calls[0].url.path.endswith(f"/entries/{ENTRY}/reason")
    ges_rows = [{"entry_id": "entry-ges"}]
    api.on(
        "GET",
        f"/v1/plans/{PLAN_A}/entries/entry-ges/reason",
        body=reason_body(entry_id="entry-ges"),
    )
    with triggered("ges-table.selected_rows"):
        prog.on_reason([0], [0], PLAN_A, exp_rows, ges_rows, SESSION)
    assert api.calls[-1].url.path.endswith("/entries/entry-ges/reason")
    with triggered("prog-plan.value"):
        assert prog.on_reason([], [], PLAN_A, exp_rows, ges_rows, SESSION) == ""
        assert prog.on_reason([0], [], None, exp_rows, ges_rows, SESSION) == ""
        # Sin selección en explicaciones, cae a la de garantías.
        prog.on_reason([], [0], PLAN_A, exp_rows, ges_rows, SESSION)
    assert api.calls[-1].url.path.endswith("/entries/entry-ges/reason")


def test_on_reason_shows_api_error(api: Api) -> None:
    api.on(
        "GET",
        f"/v1/plans/{PLAN_A}/entries/{ENTRY}/reason",
        status=404,
        body={"detail": "el plan no tiene explicación para la entrada"},
    )
    with triggered("exp-table.selected_rows"):
        out = prog.on_reason([0], [], PLAN_A, [{"entry_id": ENTRY}], [], SESSION)
    assert "no tiene explicación" in text_of(out)


def test_table_rows_keep_full_entry_id_for_selection() -> None:
    page = {
        "items": [
            {
                "entry_id": ENTRY,
                "status": "scheduled",
                "detail": None,
                "text": "t",
                "ges_deadline": "2026-10-20",
                "met": False,
                "cause": "capacity_taken",
                "scheduled_date": None,
                "days_late": None,
            }
        ]
    }
    assert prog.explanation_rows(page)[0]["entry_id"] == ENTRY
    assert prog.ges_rows(page)[0]["entry_id"] == ENTRY
    assert prog.ges_rows(page)[0]["late"] == "—"


# ------------------------------------------------------------------ callbacks de la vista


def plan_item(
    plan_id: str = PLAN_A, status: str = "pending", current: bool = False
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "policy": "optimized",
        "review_status": status,
        "is_current": current,
        "created_at": "2026-10-05T12:00:00Z",
    }


def plan_detail(
    status: str = "pending", requested_by: str | None = "gestor.sintetico"
) -> dict[str, Any]:
    return {
        **side(PLAN_A, "optimized", status),
        "run_id": "run-sintetica",
        "requested_by": requested_by,
        "objective_value": 1.0,
        "horizon_start": "2026-10-12",
        "horizon_end": "2026-11-08",
        "summary": {"scheduled": 12, "overbooked_flags": 1, "by_status": {"scheduled": 12}},
        "ges": {"obligated": 3, "met": 2, "unmet": 1},
        "warnings": ["aviso del programador"],
        "config": {"scheduler": {"overbooking": {"enabled": True}}},
    }


def test_request_visibility_and_policy_callbacks() -> None:
    assert prog.on_request_visibility(SESSION) == (prog.SHOWN, "")
    assert prog.on_request_visibility(None) == (prog.HIDDEN, "")
    lectura = {**SESSION, "role": "lectura"}
    assert "no puede programar" in prog.on_request_visibility(lectura)[1]
    assert prog.on_policy_change("optimized") == prog.SHOWN
    assert prog.on_policy_change("fifo") == prog.HIDDEN


def test_on_jobs_submit_polls_and_logs_out(api: Api) -> None:
    job = {
        "job_id": "job-1",
        "policy": "optimized",
        "status": "queued",
        "created_at": "2026-10-05T12:00:00Z",
    }
    api.on("POST", "/v1/schedule-runs", status=202, body=job)
    with triggered("prog-submit.n_clicks"):
        jobs, disabled, msg, listing, version = prog.on_jobs(
            1, 0, SESSION, [], "optimized", 4, ["on"], 30, 3
        )
    assert jobs[0]["job_id"] == "job-1" and disabled is False and version == 3
    assert "pendiente de revisión" in text_of(msg) and "En cola" in text_of(listing)
    api.on("GET", "/v1/schedule-runs/job-1", body={**job, "status": "succeeded", "plan_id": PLAN_A})
    with triggered("prog-interval.n_intervals"):
        jobs, disabled, _, listing, version = prog.on_jobs(
            1, 1, SESSION, jobs, "optimized", 4, ["on"], 30, 3
        )
    assert disabled is True and version == 4
    assert f"/programacion?plan={PLAN_A}" in str(listing)
    assert prog.on_jobs(0, 0, None, [], None, None, None, None, None) == ([], True, "", "", 0)


def test_build_jobs_list_empty_and_failed() -> None:
    assert "Todavía no pediste" in text_of(prog.build_jobs_list([]))
    failed = [
        {"job_id": "j", "policy": "fifo", "status": "failed", "error": None, "created_at": None}
    ]
    assert "Falló sin mensaje." in text_of(prog.build_jobs_list(failed))


def test_on_plan_options(api: Api) -> None:
    api.on(
        "GET", "/v1/plans", body={"items": [plan_item(PLAN_B), plan_item(PLAN_A, "approved", True)]}
    )
    options, value, empty = prog.on_plan_options(SESSION, 0, 0, f"?plan={PLAN_A}", None)
    assert [o["value"] for o in options] == [PLAN_B, PLAN_A]
    assert value == PLAN_A and empty == ""
    assert "Vigente" in options[1]["label"] and "Aprobado" in options[1]["label"]
    api.on("GET", "/v1/plans", body={"items": []})
    _, none, gestor_empty = prog.on_plan_options(SESSION, 0, 0, None, None)
    assert none is None and "Pide uno en Programar" in text_of(gestor_empty)
    reader = {**SESSION, "role": "lectura"}
    assert text_of(prog.on_plan_options(reader, 0, 0, None, None)[2]) == "Todavía no hay planes."
    assert prog.on_plan_options(None, 0, 0, None, None)[0] == []


def test_on_plan_head_for_gestor_and_reviewer(api: Api) -> None:
    api.on("GET", f"/v1/plans/{PLAN_A}", body=plan_detail("approved"))
    api.on(
        "GET",
        f"/v1/plans/{PLAN_A}/reviews",
        body={
            "items": [
                {
                    "action": "approve",
                    "user_name": "rev",
                    "role": "revisor",
                    "note": None,
                    "created_at": "2026-10-06T12:00:00Z",
                }
            ]
        },
    )
    head, statuses, review, activate, _hint, audit = prog.on_plan_head(PLAN_A, SESSION, 0)
    assert "Sobrecupo" in text_of(head) or "Optimizada" in text_of(head)
    assert "aviso del programador" in text_of(head)
    assert statuses == [{"label": "Agendada", "value": "scheduled"}]
    assert review == prog.HIDDEN and activate == prog.SHOWN
    assert "Aprobó el plan" in text_of(audit)
    assert prog.on_plan_head(None, SESSION, 0) == ("", [], prog.HIDDEN, prog.HIDDEN, "", "")
    err = prog.on_plan_head(PLAN_A, None, 0)
    assert "clave" in text_of(err[0]) and err[1] == []


def test_on_calendar_builds_heatmap_and_filters(api: Api) -> None:
    items = [
        {
            "resource_id": "r1",
            "resource_label": "Box 1",
            "health_service_code": 7,
            "date": "2026-10-12",
            "scheduled": 3,
            "overbooked": 1,
            "capacity": 4,
        },
        {
            "resource_id": "r1",
            "resource_label": "Box 1",
            "health_service_code": 7,
            "date": "2026-10-13",
            "scheduled": 2,
            "overbooked": 0,
            "capacity": 4,
        },
        {
            "resource_id": "r2",
            "resource_label": "Box 2",
            "health_service_code": 7,
            "date": "2026-10-12",
            "scheduled": 1,
            "overbooked": 0,
            "capacity": 4,
        },
    ]
    api.on("GET", f"/v1/plans/{PLAN_A}/calendar", body={"items": items, "total": 3})
    out = prog.on_calendar(PLAN_A, "specialist_agenda", 7, SESSION)
    text = text_of(out)
    assert "Box 1" in text and "+n indica" in text
    params = api.calls[0].url.params
    assert params["resource_kind"] == "specialist_agenda" and params["health_service_code"] == "7"
    assert prog.on_calendar(None, None, None, SESSION) == ""
    assert "clave" in text_of(prog.on_calendar(PLAN_A, None, None, None))


def test_calendar_pagination_and_resource_cap(api: Api) -> None:
    def page(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        n = 500 if offset < 1000 else 20
        rows = [
            {
                "resource_id": f"r{offset + i}",
                "resource_label": f"Box {offset + i}",
                "health_service_code": 1,
                "date": "2026-10-12",
                "scheduled": 1,
                "overbooked": 0,
                "capacity": 2,
            }
            for i in range(n)
        ]
        return httpx.Response(200, json={"items": rows, "total": 1020})

    api.routes[("GET", f"/v1/plans/{PLAN_A}/calendar")] = page
    items, total = prog.fetch_calendar(
        api.client(), Session(KEY, "u", "gestor"), PLAN_A, None, None
    )
    assert len(items) == 1020 == total and len(api.calls) == 3
    data = prog.prepare_calendar(items)
    assert data.shown_resources == prog.CALENDAR_MAX_ROWS and data.total_resources == 1020
    assert f"Se muestran los {prog.CALENDAR_MAX_ROWS} recursos" in text_of(
        prog.build_calendar(data)
    )
    empty = prog.build_calendar(prog.prepare_calendar([]))
    assert "no tiene bloques" in text_of(empty)


def test_on_ges_and_on_explanations(api: Api) -> None:
    ges_item = {
        "entry_id": ENTRY,
        "obligation": "deadline",
        "ges_deadline": "2026-10-20",
        "met": False,
        "on_time": False,
        "scheduled_date": None,
        "days_late": None,
        "first_possible_date": None,
        "cause": "capacity_taken",
        "text": "t",
    }
    api.on(
        "GET",
        f"/v1/plans/{PLAN_A}/ges",
        body={
            "total": 25,
            "items": [ges_item],
            "by_cause": [{"cause": "capacity_taken", "count": 25}],
        },
    )
    with triggered("ges-table.page_current"):
        rows, pages, page, summary, count, options, selected = prog.on_ges(
            PLAN_A, "capacity_taken", 2, SESSION
        )
    assert rows[0]["entry_id"] == ENTRY and pages == 3 and page == 2 and selected == []
    assert "25 garantías GES no cumplidas" in count and "Cupos tomados" in text_of(summary)
    assert options == [{"label": "Cupos tomados", "value": "capacity_taken"}]
    params = api.calls[0].url.params
    assert (
        params["offset"] == "20"
        and params["met"] == "false"
        and params["cause"] == "capacity_taken"
    )
    with triggered("ges-cause.value"):
        assert prog.on_ges(PLAN_A, None, 2, SESSION)[2] == 0
    assert prog.on_ges(None, None, 0, SESSION) == ([], 1, 0, "", "", [], [])
    failed = prog.on_ges(PLAN_A, None, 0, None)
    assert failed[0] == [] and "clave" in text_of(failed[3]) and failed[6] == []
    assert "Todas las GES" in text_of(prog.build_cause_summary([]))

    exp_item = {
        "entry_id": ENTRY,
        "status": "capacity_taken",
        "detail": "no_block_in_horizon",
        "text": "t",
    }
    api.on("GET", f"/v1/plans/{PLAN_A}/explanations", body={"total": 11, "items": [exp_item]})
    with triggered("exp-status.value"):
        erows, epages, epage, ecount, esel = prog.on_explanations(
            PLAN_A, "capacity_taken", 1, SESSION
        )
    assert (
        erows[0]["detail"] == "Sin bloque en el horizonte"
        and epages == 2
        and epage == 0
        and esel == []
    )
    assert "11 entradas" in ecount
    assert prog.on_explanations(None, None, 0, SESSION) == ([], 1, 0, "", [])
    assert (
        prog.on_explanations(PLAN_A, None, 0, None)[3] == "No se pudieron leer las explicaciones."
    )


def test_on_decision_and_confirm_panel(api: Api) -> None:
    api.on("POST", f"/v1/plans/{PLAN_A}/review", body=plan_detail("approved"))
    reviewer = {"api_key": KEY, "user": "rev.sintetico", "role": "revisor"}
    with triggered("decide-approve.n_clicks"):
        pending, msg, version, note_value = prog.on_decision(
            1, 0, 0, 0, 0, None, PLAN_A, "nota", reviewer, 5
        )
    assert pending == {"action": "approved"} and msg == "" and version == 5 and note_value == "nota"
    with triggered("decide-confirm.n_clicks"):
        pending, msg, version, note_value = prog.on_decision(
            1, 0, 0, 0, 1, pending, PLAN_A, "nota", reviewer, 5
        )
    assert pending is None and "aprobado por rev.sintetico" in text_of(msg)
    assert version == 6 and note_value == ""
    with triggered("decide-approve.n_clicks"):
        out = prog.on_decision(1, 0, 0, 0, 0, None, PLAN_A, "n", None, None)
    assert out[0] is None and "clave" in text_of(out[1]) and out[2] == 0
    style, text = prog.on_confirm_panel({"action": "rejected"}, PLAN_A)
    assert style == prog.SHOWN and "Rechazar el plan aaaaaaaa" in text
    assert prog.on_confirm_panel(None, PLAN_A) == (prog.HIDDEN, "")


def test_plan_from_search_and_overbooking_helpers() -> None:
    assert prog.plan_from_search(None) is None
    assert prog.plan_from_search("?x=1") is None
    assert prog.plan_from_search(f"?plan={PLAN_A}") == PLAN_A
    assert prog.plan_overbooking({"config": {"request": {"overbooking": True}}}) is True
    assert prog.plan_overbooking({}) is False
    assert prog.policy_label("optimized", True).lower().startswith("optimizada")
    assert prog.policy_label("otra", None) == "otra"


def test_decision_hints_for_gestor_states() -> None:
    def view(status: str, current: bool) -> str:
        p = {"review_status": status, "requested_by": "x", "is_current": current}
        return prog.decision_view("gestor", p, "g").hint

    assert "ya es el vigente" in view("approved", True)
    assert "debe estar aprobado" in view("pending", False)
    assert "rechazado no puede quedar vigente" in view("rejected", False)
    reviewer = prog.decision_view(
        "revisor", {"review_status": "approved", "requested_by": "x", "is_current": False}, "r"
    )
    assert "ya fue revisado" in reviewer.hint
    unknown = prog.decision_view(
        "revisor", {"review_status": "pending", "requested_by": None, "is_current": False}, "r"
    )
    assert "no tiene solicitante" in unknown.hint
    assert prog.confirm_text("approved", None) == (prog.HIDDEN, "")


def test_step_decision_activate_and_unknown_trigger() -> None:
    fake = Api()
    fake.on("POST", f"/v1/plans/{PLAN_A}/activate", body=plan_detail("approved"))
    s = Session(KEY, "ges", "gestor")
    done = prog.step_decision("decide-activate", fake.client(), s, None, PLAN_A, " nota ")
    assert done.changed and done.clear_note and "vigente" in text_of(done.message)
    assert prog.step_decision(
        "otro", fake.client(), s, {"action": "approved"}, PLAN_A, None
    ).pending == {"action": "approved"}
    assert (
        prog.step_decision(
            "decide-confirm", fake.client(), s, {"action": "zzz"}, PLAN_A, None
        ).message
        is None
    )
    bad = Api()
    bad.on("POST", f"/v1/plans/{PLAN_A}/review", status=500, body={})
    err = prog.step_decision(
        "decide-confirm", bad.client(), s, {"action": "approved"}, PLAN_A, None
    )
    assert not err.changed and err.message is not None
    conflict = Api()
    conflict.on("POST", f"/v1/plans/{PLAN_A}/review", status=409, body={"detail": "ya revisado"})
    c = prog.step_decision(
        "decide-confirm", conflict.client(), s, {"action": "approved"}, PLAN_A, None
    )
    assert c.changed and "ya revisado" in text_of(c.message)
