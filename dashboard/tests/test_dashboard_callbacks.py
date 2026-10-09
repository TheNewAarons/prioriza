"""Tests de la lógica de los callbacks del panel (sin red, con respuestas sintéticas).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Se prueban las funciones puras de `dashboard.shell` y `dashboard.views.*` (nunca se importa
desde `dashboard.pages`, porque Dash ejecuta esos archivos dos veces y duplicaría callbacks).
La API se reemplaza por `httpx.MockTransport` con cuerpos mínimos que respetan los esquemas de
`api/src/api/schemas.py`. Todos los identificadores, usuarios y claves son inventados.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import httpx
import pytest
from dash import dcc, html
from dash.development.base_component import Component
from dashboard.api_client import ApiClient
from dashboard.session import Session
from dashboard.views import equidad, lista, programacion, resumen, simulacion
from shared.disclaimer import DISCLAIMER

from dashboard import shell

SECRET_KEY = "clave-sintetica-no-real-123"
PLAN_ID = "11111111-aaaa-bbbb-cccc-000000000001"
AS_OF = date(2026, 10, 1)


# ------------------------------------------------------------------ utilidades


class FakeApi:
    """API falsa: enruta por (método, ruta) y registra cada petición recibida."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[httpx.Request] = []

    def on(
        self,
        method: str,
        path: str,
        status: int = 200,
        body: Any = None,
    ) -> None:
        """Registra una respuesta fija."""
        self.routes[(method, path)] = lambda _r: httpx.Response(status, json=body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get((request.method, request.url.path))
        if route is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        return route(request)

    def client(self) -> ApiClient:
        return ApiClient("http://api.test", transport=httpx.MockTransport(self.handler))


def walk(node: Any) -> Iterator[Any]:
    """Recorre un árbol de componentes Dash (en profundidad)."""
    yield node
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)
    elif isinstance(node, Component):
        yield from walk(getattr(node, "children", None))


def text_of(node: Any) -> str:
    """Todo el texto visible de un árbol de componentes."""
    return " ".join(str(n) for n in walk(node) if isinstance(n, str))


def graphs(node: Any) -> list[Any]:
    """Figuras (`dcc.Graph`) de un árbol."""
    return [n.figure for n in walk(node) if isinstance(n, dcc.Graph)]


def session(role: str = "gestor", user: str = "usuario.sintetico") -> Session:
    return Session(SECRET_KEY, user, role)


def plan(
    status: str = "pending",
    *,
    current: bool = False,
    requested_by: str | None = "gestor.sintetico",
) -> dict[str, Any]:
    """Plan mínimo con los campos de `PlanDetailOut`."""
    return {
        "plan_id": PLAN_ID,
        "run_id": "run-sintetica",
        "policy": "optimized",
        "review_status": status,
        "is_current": current,
        "requested_by": requested_by,
        "created_at": "2026-10-05T12:00:00Z",
        "solver_status": "OPTIMAL",
        "objective_value": 10.0,
        "horizon_start": "2026-10-12",
        "horizon_end": "2026-11-08",
        "summary": {"scheduled": 12, "overbooked_flags": 1, "by_status": {"scheduled": 12}},
        "ges": {"obligated": 3, "met": 2, "unmet": 1},
        "config": {},
    }


def summary_body(**overrides: Any) -> dict[str, Any]:
    """`WaitlistSummaryOut` sintético."""
    body: dict[str, Any] = {
        "as_of": AS_OF.isoformat(),
        "run_id": "abcdef0123456789",
        "run_entries": 1000,
        "total": 900,
        "wait_median": 300.0,
        "wait_p90": 640.0,
        "ges_total": 100,
        "ges_at_risk": 12,
        "ges_overdue": 7,
        "by_care_type": [
            {
                "care_type": "consultation",
                "total": 600,
                "wait_median": 280.0,
                "wait_p90": 600.0,
                "ges_total": 60,
                "ges_at_risk": 8,
                "ges_overdue": 4,
            }
        ],
        "wait_histogram": [
            {"from_day": 0, "to_day": 30, "count": 50},
            {"from_day": 30, "to_day": 60, "count": 80},
            {"from_day": 720, "to_day": None, "count": 20},
        ],
        "disclaimer": DISCLAIMER,
    }
    body.update(overrides)
    return body


def item(i: int, *, is_ges: bool, deadline: str | None) -> dict[str, Any]:
    """`WaitlistItemOut` sintético."""
    return {
        "entry_id": f"entry-{i:04d}-sintetica",
        "patient_id": f"pac-{i:04d}",
        "health_service_code": 7,
        "specialty_code": "cne_medical:medicina_interna",
        "care_type": "consultation",
        "clinical_priority": "p1",
        "is_ges": is_ges,
        "ges_deadline": deadline,
        "entry_date": "2025-12-01",
        "wait_days": 300 + i,
        "score": 87.3,
        "rank": i + 1,
        "tier": "NONE",
    }


# ------------------------------------------------------------------ acceso y sesión


def test_login_valid_key_stores_user_and_role() -> None:
    api = FakeApi()
    api.on("GET", "/v1/me", body={"user": "ana.sintetica", "role": "revisor"})
    step = shell.auth_step("login-btn", api.client(), SECRET_KEY)
    assert step.session == {"api_key": SECRET_KEY, "user": "ana.sintetica", "role": "revisor"}
    assert step.error is None and step.changed and step.clear_key
    # La clave se envió en la cabecera, no en la ruta ni en la consulta.
    assert api.calls[0].headers["X-API-Key"] == SECRET_KEY
    assert SECRET_KEY not in str(api.calls[0].url)
    assert shell.user_text(step.session) == "ana.sintetica, revisor"


def test_login_invalid_key_shows_design_error() -> None:
    api = FakeApi()
    api.on("GET", "/v1/me", status=401, body={"detail": "x"})
    step = shell.auth_step("login-btn", api.client(), "clave-mala")
    assert step.session is None and not step.changed
    assert step.error == "La clave de API no es válida. Revísala y vuelve a intentar."


def test_login_empty_key_asks_for_it() -> None:
    api = FakeApi()
    step = shell.auth_step("login-btn", api.client(), "   ")
    assert step.session is None and step.error and "clave" in step.error.lower()
    assert api.calls == []


def test_login_api_down_says_api_does_not_respond() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    client = ApiClient("http://api.test", transport=httpx.MockTransport(boom))
    step = shell.auth_step("login-btn", client, SECRET_KEY)
    assert step.session is None
    assert step.error is not None and step.error.startswith("La API no responde")
    assert "make api" in step.error


def test_logout_clears_session_and_cache() -> None:
    api = FakeApi()
    api.on("GET", "/v1/waitlist/summary", body=summary_body())
    client = api.client()
    client.waitlist_summary(SECRET_KEY)
    client.waitlist_summary(SECRET_KEY)
    assert len(api.calls) == 1  # segunda lectura salió de la caché
    step = shell.auth_step("logout-btn", client, None)
    assert step.session is None and step.clear_key and step.changed
    client.waitlist_summary(SECRET_KEY)
    assert len(api.calls) == 2  # la caché se descartó al salir


def test_api_key_never_in_texts_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    outcomes: list[Any] = []
    # Éxito, clave inválida y API caída, todos con la misma clave.
    ok = FakeApi()
    ok.on("GET", "/v1/me", body={"user": "ana.sintetica", "role": "gestor"})
    outcomes.append(shell.auth_step("login-btn", ok.client(), SECRET_KEY))
    bad = FakeApi()
    bad.on("GET", "/v1/me", status=401, body={"detail": SECRET_KEY})
    outcomes.append(shell.auth_step("login-btn", bad.client(), SECRET_KEY))

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    down = ApiClient("http://api.test", transport=httpx.MockTransport(boom))
    outcomes.append(shell.auth_step("login-btn", down, SECRET_KEY))

    for step in outcomes:
        assert SECRET_KEY not in (step.error or "")
    assert SECRET_KEY not in caplog.text
    assert SECRET_KEY not in repr(session())
    # La cabecera y el texto de usuario tampoco la muestran.
    header = shell.user_text(session().to_store())
    assert SECRET_KEY not in header
    # Ni siquiera el bloque de la barra lateral con una API que falla.
    assert SECRET_KEY not in text_of(shell.run_info(None))


def test_visibility_switches_between_login_and_shell() -> None:
    assert shell.visibility(None) == (shell.SHOWN, shell.HIDDEN)
    assert shell.visibility({"api_key": "", "user": "u", "role": "gestor"}) == (
        shell.SHOWN,
        shell.HIDDEN,
    )
    assert shell.visibility(session().to_store()) == (shell.HIDDEN, shell.SHOWN)


def test_run_info_shows_short_id_size_and_cutoff() -> None:
    text = text_of(shell.run_info(summary_body()))
    assert "abcdef01" in text and "abcdef0123" not in text
    assert "1.000 entradas" in text and "Datos sintéticos" in text


# ------------------------------------------------------------------ aviso permanente


def test_root_layout_always_has_disclaimer() -> None:
    layout = shell.root_layout()
    strips = [
        n
        for n in walk(layout)
        if isinstance(n, html.Div) and getattr(n, "id", None) == "disclaimer"
    ]
    assert len(strips) == 1
    assert strips[0].children == DISCLAIMER
    # La franja es hija directa del layout, fuera de la pantalla de acceso y de la estructura
    # que se oculta según la sesión: se ve con y sin sesión.
    assert strips[0] in layout.children
    assert getattr(strips[0], "style", None) is None


# ------------------------------------------------------------------ visibilidad por rol


def visible_actions(role: str, p: dict[str, Any], user: str = "usuario.sintetico") -> set[str]:
    """Botones que el rol ve para ese plan, según las funciones de visibilidad del panel."""
    shown: set[str] = set()
    style, _ = programacion.request_visibility(role)
    if style != programacion.HIDDEN and "Programar" in text_of(programacion.request_form()):
        shown.add("Programar")
    view = programacion.decision_view(role, p, user)
    if view.show_review:
        shown |= {"Aprobar plan", "Rechazar plan"}
    if view.show_activate:
        shown.add("Marcar como vigente")
    return shown


def test_read_role_sees_no_actions() -> None:
    for status in ("pending", "approved", "rejected"):
        assert visible_actions("lectura", plan(status)) == set()
    _, hint = programacion.request_visibility("lectura")
    assert (
        hint == "Tu rol (lectura) no puede programar. Solo un gestor puede pedir una programación."
    )
    view = programacion.decision_view("lectura", plan("pending"), "usuario.sintetico")
    assert "Solo un revisor puede aprobar o rechazar planes." in view.hint
    assert "Solo un gestor puede marcar un plan como vigente." in view.hint


def test_manager_sees_programar_and_activate_only_for_approved() -> None:
    assert visible_actions("gestor", plan("pending")) == {"Programar"}
    assert visible_actions("gestor", plan("rejected")) == {"Programar"}
    assert visible_actions("gestor", plan("approved")) == {"Programar", "Marcar como vigente"}
    # Un plan aprobado que ya es el vigente no ofrece volver a activarlo.
    current = visible_actions("gestor", plan("approved", current=True))
    assert current == {"Programar"}
    hint = programacion.decision_view("gestor", plan("pending"), "g").hint
    assert "Solo un revisor puede aprobar o rechazar planes." in hint
    assert "aprobado" in hint


def test_reviewer_sees_approve_reject_only_for_pending_and_never_programar() -> None:
    assert visible_actions("revisor", plan("pending")) == {"Aprobar plan", "Rechazar plan"}
    assert visible_actions("revisor", plan("approved")) == set()
    assert visible_actions("revisor", plan("rejected")) == set()
    style, hint = programacion.request_visibility("revisor")
    assert style == programacion.HIDDEN and "revisor" in hint
    # Un revisor tampoco activa planes: la línea lo explica.
    approved = programacion.decision_view("revisor", plan("approved"), "r")
    assert not approved.show_activate
    assert "Solo un gestor puede marcar un plan como vigente." in approved.hint


def test_reviewer_cannot_review_own_request() -> None:
    own = plan("pending", requested_by="Revisor.Sintetico")
    view = programacion.decision_view("revisor", own, "revisor.sintetico")
    assert not view.show_review and "cuatro ojos" in view.hint
    unknown = programacion.decision_view("revisor", plan(requested_by=None), "r")
    assert not unknown.show_review


def test_manager_form_is_shown_and_has_no_hint() -> None:
    assert programacion.request_visibility("gestor") == (programacion.SHOWN, "")
    assert programacion.request_visibility(None) == (programacion.HIDDEN, "")


# ------------------------------------------------------------------ lista


def test_build_params_translates_filters_and_order() -> None:
    params = lista.build_params(
        service=7,
        specialty=" cne_medical:medicina_interna ",
        care="consultation",
        priority="p2",
        ges="true",
        tier="GES_OVERDUE",
        order="score",
        page=2,
    )
    assert params == {
        "limit": 50,
        "offset": 100,
        "order_by": "score",
        "health_service_code": 7,
        "specialty_code": "cne_medical:medicina_interna",
        "care_type": "consultation",
        "clinical_priority": "p2",
        "is_ges": True,
        "tier": "GES_OVERDUE",
    }


def test_build_params_defaults_omit_empty_filters() -> None:
    params = lista.build_params(
        service=None,
        specialty="  ",
        care=None,
        priority=None,
        ges=None,
        tier=None,
        order=None,
        page=0,
    )
    assert params == {"limit": 50, "offset": 0, "order_by": "score"}
    no_ges = lista.build_params(
        service=None, specialty=None, care=None, priority=None, ges="false", tier=None,
        order="entry_date", page=0,
    )  # fmt: skip
    assert no_ges["is_ges"] is False and no_ges["order_by"] == "entry_date"


def test_resolve_page_resets_on_filter_and_keeps_on_paging() -> None:
    assert lista.resolve_page("lista-table", 3) == 3
    assert lista.resolve_page("lista-table", None) == 0
    for trigger in ("f-care", "f-order", "session", None):
        assert lista.resolve_page(trigger, 3) == 0


def test_server_pagination_requests_one_page_of_50() -> None:
    api = FakeApi()
    api.on("GET", "/v1/waitlist/summary", body=summary_body())
    api.on(
        "GET",
        "/v1/waitlist",
        body={
            "total": 100_000,
            "limit": 50,
            "offset": 150,
            "items": [item(i, is_ges=False, deadline=None) for i in range(3)],
            "disclaimer": DISCLAIMER,
        },
    )
    params = lista.build_params(
        service=None, specialty=None, care=None, priority=None, ges=None, tier=None,
        order=None, page=3,
    )  # fmt: skip
    page = lista.fetch_lista(api.client(), session(), params)
    request = next(c for c in api.calls if c.url.path == "/v1/waitlist")
    assert request.url.params["limit"] == "50"
    assert request.url.params["offset"] == "150"
    # Nunca se pide la lista completa: ninguna petición sin límite o con límite mayor.
    for call in api.calls:
        if call.url.path == "/v1/waitlist":
            assert int(call.url.params["limit"]) <= lista.PAGE_SIZE
    assert page.pages == 2000
    assert page.text == "Mostrando 151 a 153 de 100.000 entradas."
    assert len(page.rows) == 3


def test_page_count_and_range_text() -> None:
    assert lista.page_count(0) == 1
    assert lista.page_count(50) == 1
    assert lista.page_count(51) == 2
    assert lista.range_text(0, 0, 0) == "Ninguna entrada coincide con los filtros."


def test_build_rows_formats_numbers_and_ges_badges_with_icon_and_text() -> None:
    page = {
        "items": [
            item(0, is_ges=True, deadline="2026-09-20"),  # vencida
            item(1, is_ges=True, deadline="2026-10-11"),  # en riesgo (10 días)
            item(2, is_ges=True, deadline="2027-03-01"),  # GES sin alerta
            item(3, is_ges=False, deadline=None),
        ]
    }
    rows = lista.build_rows(page, AS_OF)
    assert [r["ges"] for r in rows] == ["● Vencida", "▲ En riesgo", "GES", "—"]
    first = rows[0]
    assert first["score"] == "87,3"
    assert first["score_bar"] == "█████████░"
    assert first["priority"] == "P1"
    assert first["wait_days"] == 300
    assert first["specialty"] == "Medicina interna"
    assert first["service"] == "SS 7"
    assert first["rank"] == 1


def test_ges_state_boundaries() -> None:
    assert lista.ges_state(False, "2026-09-01", AS_OF) is None
    assert lista.ges_state(True, None, AS_OF) == "ges"
    assert lista.ges_state(True, "2026-09-30", AS_OF) == "overdue"
    assert lista.ges_state(True, "2026-10-01", AS_OF) == "risk"  # vence hoy, no vencida
    assert lista.ges_state(True, "2026-10-31", AS_OF) == "risk"  # 30 días
    assert lista.ges_state(True, "2026-11-01", AS_OF) == "ges"  # 31 días


def test_build_detail_has_score_breakdown_and_explanation() -> None:
    entry = {
        "entry_id": "entry-0001-sintetica",
        "rank": 4,
        "score": 62.5,
        "clinical_priority": "p2",
        "wait_days": 410,
        "tier": "GES_DUE_SOON",
        "components": [
            {
                "field": "clinical_priority",
                "label": "Prioridad clínica",
                "raw_value": "p2",
                "normalized": 0.75,
                "weight": 40.0,
                "contribution": 30.0,
            },
            {
                "field": "wait_days",
                "label": "Tiempo de espera",
                "raw_value": 410,
                "normalized": 0.5,
                "weight": 35.0,
                "contribution": 17.5,
            },
        ],
        "explanation": {
            "tier": "GES_DUE_SOON",
            "tier_reason": "El plazo GES vence en 12 días.",
            "total": 120,
            "lines": ["Prioridad clínica P2 aporta 30 puntos.", "Espera de 410 días."],
        },
    }
    detail = lista.build_detail(entry, summary_body())
    text = text_of(detail)
    assert "Prioridad clínica" in text and "Tiempo de espera" in text
    assert "30,0" in text and "17,5" in text  # aporte en puntos de cada componente
    assert "Puesto 4 de 120" in text
    assert "GES por vencer" in text and "El plazo GES vence en 12 días." in text
    assert "Prioridad clínica P2 aporta 30 puntos." in text
    assert "definida por profesionales" in text
    figures = graphs(detail)
    assert len(figures) == 2  # desglose y regla de espera en miniatura
    bar_text = list(figures[0].data[0].text)
    assert bar_text == ["30,0 de 40 pts", "17,5 de 35 pts"]


def test_fetch_detail_missing_entry_says_so() -> None:
    api = FakeApi()
    api.on("GET", "/v1/patients/pac-0001", body={"entries": []})
    out = lista.fetch_detail(
        api.client(), session(), {"patient_id": "pac-0001", "entry_id": "no-existe"}
    )
    assert "ya no está disponible" in text_of(out)


# ------------------------------------------------------------------ programación


def test_build_run_request_overbooking_only_for_optimized() -> None:
    optimized = programacion.build_run_request("optimized", 4, ["on"], 30)
    assert optimized == {
        "policy": "optimized",
        "horizon_weeks": 4,
        "overbooking": True,
        "time_limit_s": 30.0,
    }
    for policy in ("fifo", "priority"):
        body = programacion.build_run_request(policy, "8", ["on"], "60")
        assert body["overbooking"] is False
        assert body["horizon_weeks"] == 8 and body["time_limit_s"] == 60.0
    assert programacion.build_run_request("optimized", 4, [], 30)["overbooking"] is False
    assert programacion.build_run_request("optimized", 4, None, 30)["overbooking"] is False


@pytest.mark.parametrize(
    ("policy", "weeks", "limit", "fragment"),
    [
        (None, 4, 30, "política"),
        ("nope", 4, 30, "política"),
        ("fifo", 0, 30, "semanas"),
        ("fifo", 53, 30, "semanas"),
        ("fifo", "x", 30, "semanas"),
        ("fifo", 4, 0, "límite"),
        ("fifo", 4, 4000, "límite"),
        ("fifo", 4, "x", "límite"),
    ],
)
def test_build_run_request_rejects_bad_values(
    policy: Any, weeks: Any, limit: Any, fragment: str
) -> None:
    with pytest.raises(ValueError, match=fragment):
        programacion.build_run_request(policy, weeks, [], limit)


def _job(status: str, plan_id: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "job_id": "22222222-aaaa-bbbb-cccc-000000000002",
        "status": status,
        "policy": "optimized",
        "requested_by": "gestor.sintetico",
        "created_at": "2026-10-05T12:00:00Z",
        "plan_id": plan_id,
        "error": error,
        "disclaimer": DISCLAIMER,
    }


FORM = {"policy": "optimized", "weeks": 4, "overbooking": ["on"], "time_limit_s": 30}


def test_step_jobs_submit_keeps_interval_on_while_job_is_queued() -> None:
    api = FakeApi()
    api.on("POST", "/v1/schedule-runs", status=202, body=_job("queued"))
    step = programacion.step_jobs("prog-submit", api.client(), session(), [], FORM)
    assert step.jobs[0]["status"] == "queued" and step.jobs[0]["overbooking"] is True
    assert step.interval_disabled is False
    assert "pendiente de revisión" in text_of(step.message)
    sent = json.loads(api.calls[0].content)
    assert sent == {
        "policy": "optimized",
        "horizon_weeks": 4,
        "overbooking": True,
        "time_limit_s": 30.0,
    }


def test_step_jobs_polls_until_terminal_then_turns_interval_off() -> None:
    sid = session()
    running = [{"job_id": _job("queued")["job_id"], "status": "queued", "policy": "optimized"}]
    for status, disabled in (("queued", False), ("running", False)):
        api = FakeApi()
        api.on("GET", f"/v1/schedule-runs/{running[0]['job_id']}", body=_job(status))
        step = programacion.step_jobs("prog-interval", api.client(), sid, running, None)
        assert step.interval_disabled is disabled and not step.refresh_plans
    api = FakeApi()
    api.on(
        "GET",
        f"/v1/schedule-runs/{running[0]['job_id']}",
        body=_job("succeeded", plan_id=PLAN_ID),
    )
    done = programacion.step_jobs("prog-interval", api.client(), sid, running, None)
    assert done.interval_disabled is True and done.refresh_plans is True
    assert done.jobs[0]["plan_id"] == PLAN_ID


def test_step_jobs_failed_job_turns_interval_off_and_shows_message() -> None:
    running = [{"job_id": _job("running")["job_id"], "status": "running", "policy": "optimized"}]
    api = FakeApi()
    api.on(
        "GET",
        f"/v1/schedule-runs/{running[0]['job_id']}",
        body=_job("failed", error="El solver no encontró solución."),
    )
    step = programacion.step_jobs("prog-interval", api.client(), session(), running, None)
    assert step.interval_disabled is True and not step.refresh_plans
    listing = text_of(programacion.build_jobs_list(step.jobs))
    assert "Falló" in listing and "El solver no encontró solución." in listing


def test_step_jobs_unknown_job_after_api_restart_fails_and_stops() -> None:
    jobs = [{"job_id": "x", "status": "running", "policy": "fifo"}]
    api = FakeApi()  # sin ruta: 404
    step = programacion.step_jobs("prog-interval", api.client(), session(), jobs, None)
    assert step.jobs[0]["status"] == "failed" and step.interval_disabled is True
    assert "se reinició" in step.jobs[0]["error"]


def test_step_jobs_transient_error_keeps_polling() -> None:
    jobs = [{"job_id": "x", "status": "running", "policy": "fifo"}]
    api = FakeApi()
    api.on("GET", "/v1/schedule-runs/x", status=500, body={})
    step = programacion.step_jobs("prog-interval", api.client(), session(), jobs, None)
    assert step.interval_disabled is False and step.message is not None


def test_step_jobs_submit_errors_do_not_start_the_interval() -> None:
    api = FakeApi()
    api.on("POST", "/v1/schedule-runs", status=403, body={"detail": "Tu rol (lectura) no puede."})
    step = programacion.step_jobs("prog-submit", api.client(), session("lectura"), [], FORM)
    assert step.jobs == [] and step.interval_disabled is True
    assert "Tu rol (lectura) no puede." in text_of(step.message)
    bad = programacion.step_jobs("prog-submit", api.client(), session(), [], {**FORM, "weeks": 99})
    assert bad.jobs == [] and "semanas" in text_of(bad.message)


def test_step_decision_review_sends_decision_and_note() -> None:
    api = FakeApi()
    api.on("POST", f"/v1/plans/{PLAN_ID}/review", body=plan("approved"))
    reviewer = session("revisor", "rev.sintetico")
    opened = programacion.step_decision(
        "decide-approve", api.client(), reviewer, None, PLAN_ID, "ok"
    )
    assert opened.pending == {"action": "approved"} and api.calls == []  # aún no llama a la API
    done = programacion.step_decision(
        "decide-confirm", api.client(), reviewer, opened.pending, PLAN_ID, "  revisado  "
    )
    assert json.loads(api.calls[0].content) == {"decision": "approved", "note": "revisado"}
    assert done.pending is None and done.changed and done.clear_note
    assert text_of(done.message) == "Plan aprobado por rev.sintetico."
    rejected = programacion.step_decision(
        "decide-confirm", api.client(), reviewer, {"action": "rejected"}, PLAN_ID, ""
    )
    assert json.loads(api.calls[1].content) == {"decision": "rejected", "note": None}
    assert text_of(rejected.message) == "Plan rechazado por rev.sintetico."


def test_step_decision_cancel_and_missing_plan() -> None:
    api = FakeApi()
    cancel = programacion.step_decision(
        "decide-cancel", api.client(), session("revisor"), {"action": "approved"}, PLAN_ID, None
    )
    assert cancel.pending is None and not cancel.changed and api.calls == []
    nothing = programacion.step_decision("decide-approve", api.client(), session(), None, None, "")
    assert "Elige un plan" in text_of(nothing.message)


@pytest.mark.parametrize(
    ("status", "detail"), [(409, "El plan ya fue revisado."), (403, "Sin permiso.")]
)
def test_step_decision_shows_api_message_on_409_and_403(status: int, detail: str) -> None:
    api = FakeApi()
    api.on("POST", f"/v1/plans/{PLAN_ID}/review", status=status, body={"detail": detail})
    step = programacion.step_decision(
        "decide-confirm", api.client(), session("revisor"), {"action": "approved"}, PLAN_ID, None
    )
    assert text_of(step.message) == detail
    assert step.pending is None and step.changed and not step.clear_note


def test_step_decision_activate_calls_activate() -> None:
    api = FakeApi()
    api.on("POST", f"/v1/plans/{PLAN_ID}/activate", body=plan("approved", current=True))
    step = programacion.step_decision(
        "decide-activate", api.client(), session("gestor", "ges.sintetico"), None, PLAN_ID, "va"
    )
    assert json.loads(api.calls[0].content) == {"note": "va"}
    assert text_of(step.message) == "Plan marcado como vigente por ges.sintetico."
    api.on("POST", f"/v1/plans/{PLAN_ID}/activate", status=409, body={"detail": "No aprobado."})
    conflict = programacion.step_decision(
        "decide-activate", api.client(), session("gestor"), None, PLAN_ID, None
    )
    assert text_of(conflict.message) == "No aprobado."


def test_confirm_text_describes_the_effect() -> None:
    style, approve = programacion.confirm_text("approved", PLAN_ID)
    assert style == programacion.SHOWN
    assert approve.startswith("Aprobar el plan 11111111.")
    assert "Aprobar no lo deja vigente: un gestor debe activarlo." in approve
    _, reject = programacion.confirm_text("rejected", PLAN_ID)
    assert reject.startswith("Rechazar el plan 11111111.")
    assert "no se puede deshacer" in reject
    assert programacion.confirm_text(None, PLAN_ID) == (programacion.HIDDEN, "")
    assert programacion.confirm_text("approved", None) == (programacion.HIDDEN, "")


def test_build_audit_lists_who_role_and_when() -> None:
    reviews = [
        {
            "created_at": "2026-10-06T10:00:00Z",
            "user_name": "rev.sintetico",
            "role": "revisor",
            "action": "approve",
            "note": "Todo en orden.",
        },
        {
            "created_at": "2026-10-07T09:00:00Z",
            "user_name": "ges.sintetico",
            "role": "gestor",
            "action": "activate",
            "note": None,
        },
    ]
    text = text_of(programacion.build_audit(reviews))
    for expected in (
        "rev.sintetico",
        "revisor",
        "6 oct 2026",
        "Aprobó el plan",
        "Todo en orden.",
        "ges.sintetico",
        "gestor",
        "7 oct 2026",
        "Marcó el plan como vigente",
    ):
        assert expected in text
    assert "todavía no tiene decisiones" in text_of(programacion.build_audit([]))


def test_plan_header_states_it_is_a_proposal_needing_review() -> None:
    text = text_of(programacion.build_plan_header(plan("pending")))
    assert "Requiere revisión humana" in text
    assert "Pendiente de revisión" in text
    assert "gestor.sintetico" in text


def test_pick_plan_prefers_url_then_current_then_latest() -> None:
    opts = programacion.plan_options(
        [
            {**plan("approved", current=True), "plan_id": "a" * 8 + "-1"},
            {**plan("pending"), "plan_id": "b" * 8 + "-2"},
        ]
    )
    a, b = opts[0]["value"], opts[1]["value"]
    assert programacion.pick_plan(opts, None, b) == b
    assert programacion.pick_plan(opts, b, "inexistente") == b
    assert programacion.pick_plan(opts, "viejo", None) == a
    assert programacion.pick_plan([], None, None) is None
    assert "Vigente" in opts[0]["label"] and "Vigente" not in opts[1]["label"]
    assert programacion.plan_from_search(f"?plan={a}") == a


# ------------------------------------------------------------------ resumen y regla de espera


def test_wait_ruler_marks_median_and_p90_with_labels() -> None:
    data = resumen.ResumenData(summary_body(), None, None, None)
    body = resumen.build_resumen(data)
    (figure,) = graphs(body)
    labels = [t for trace in figure.data if trace.text is not None for t in trace.text]
    assert "▼ 300 mediana" in labels
    assert "▼ 640 p90" in labels
    assert "▲ GES en riesgo" in [
        y for tr in figure.data for y in (tr.y or []) if isinstance(y, str)
    ]
    text = text_of(body)
    assert "Todavía no hay un plan vigente." in text
    assert "720 o más" in text  # tramo final del histograma, en la tabla equivalente
    assert "30 días o menos" in text  # corte de "en riesgo" escrito en la nota


def test_fetch_resumen_treats_404_as_no_current_plan() -> None:
    api = FakeApi()
    api.on("GET", "/v1/waitlist/summary", body=summary_body())
    data = resumen.fetch_resumen(api.client(), session())
    assert data.current_plan is None and data.approver is None


def test_current_plan_block_names_approver() -> None:
    api = FakeApi()
    api.on("GET", "/v1/waitlist/summary", body=summary_body())
    api.on("GET", "/v1/plans/current", body=plan("approved", current=True))
    api.on(
        "GET",
        f"/v1/plans/{PLAN_ID}/reviews",
        body={
            "items": [
                {
                    "action": "approve",
                    "user_name": "rev.sintetico",
                    "created_at": "2026-10-06T10:00:00Z",
                }
            ]
        },
    )
    data = resumen.fetch_resumen(api.client(), session())
    text = text_of(resumen.current_plan_block(data))
    assert "aprobado por rev.sintetico el 6 oct" in text and "12 citas" in text


# ------------------------------------------------------------------ simulación


def _stats(mean: float, low: float, high: float) -> dict[str, float]:
    return {"mean": mean, "ci95_low": low, "ci95_high": high}


def sim_body() -> dict[str, Any]:
    policies = ("fifo", "priority", "optimized", "optimized_overbooking")
    aggregate = {
        p: {"exits_attended": _stats(100.0 + 10 * i, 90.0 + 10 * i, 110.0 + 10 * i)}
        for i, p in enumerate(policies)
    }
    return {
        "generated_at": "2026-10-08T12:00:00Z",
        "run": {"id": "abcdef0123456789", "size": 1000},
        "config": {"weeks": 26, "replica_seeds": [1, 2, 3]},
        "aggregate": aggregate,
        "comparisons": {
            "optimized_vs_fifo": {
                "exits_attended": {
                    "mean_diff": 20.0,
                    "ci95_low": 5.0,
                    "ci95_high": 35.0,
                    "better_in": 3,
                    "direction": 1,
                }
            }
        },
        "supply_coverage": {
            "consultation": {
                "blocks": 10,
                "cells_with_block": 4,
                "cells": 8,
                "stock": 500,
                "stock_in_cells_with_block": 300,
            }
        },
        "limitations": ["Oferta sintética simplificada."],
        "equity": {},
    }


def test_simulation_charts_use_distinct_marker_and_dash_per_policy() -> None:
    data = simulacion.SimulationData(sim_body(), "abcdef0123456789")
    body = simulacion.build_simulation(data, "exits_attended")
    (figure,) = graphs(body)
    assert len(figure.data) == 4
    centers = [tr.marker.symbol[1] for tr in figure.data]
    dashes = [tr.line.dash for tr in figure.data]
    colors = [tr.line.color for tr in figure.data]
    assert len(set(centers)) == 4  # el marcador distingue cada política
    assert len(set(dashes)) >= 3 and "dot" in dashes and "dash" in dashes  # y el tipo de línea
    assert len(set(colors)) == 4
    # Cada política se distingue sin color: el par (marcador, línea) es único.
    assert len(set(zip(centers, dashes, strict=True))) == 4


def test_simulation_comparison_honest_verdicts() -> None:
    assert simulacion.verdict(20.0, 5.0, 35.0, 1) == "✓ Mejora"
    assert simulacion.verdict(-20.0, -35.0, -5.0, 1) == "● Empeora"
    assert simulacion.verdict(20.0, 5.0, 35.0, -1) == "● Empeora"  # menos es mejor
    assert simulacion.verdict(1.0, -3.0, 5.0, 1) == "◷ Sin diferencia clara"
    metric = simulacion.METRIC_BY_KEY["exits_attended"]
    rows = simulacion.comparison_rows(sim_body()["comparisons"], metric, 3)
    assert rows[0][0] == "Optimizada frente a orden de llegada"
    assert rows[0][3] == "3 de 3" and rows[0][4] == "✓ Mejora"


def test_simulation_warns_when_run_differs_and_shows_limitations() -> None:
    data = simulacion.SimulationData(sim_body(), "ffffffff00000000")
    text = text_of(simulacion.build_simulation(data, "exits_attended"))
    assert "otra corrida" in text and "Oferta sintética simplificada." in text
    assert "más es mejor" in text
    empty = text_of(simulacion.build_simulation(simulacion.SimulationData(None, None), "x"))
    assert "make simulate" in empty


# ------------------------------------------------------------------ equidad


def _group(
    entries: float, attention: float, wait: float, exposure: float, no_show: float
) -> dict[str, dict[str, float]]:
    def m(v: float) -> dict[str, float]:
        return {"mean": v, "min": v * 0.9, "max": v * 1.1}

    return {
        "entries": {"mean": entries, "min": entries, "max": entries},
        "attention_rate": m(attention),
        "wait_attended_median": m(wait),
        "overbooking_exposure": m(exposure),
        "no_show_realized_rate": m(no_show),
    }


def equity_body() -> dict[str, Any]:
    groups = {
        "0_14": _group(100, 0.60, 200.0, 0.268, 0.10),  # más expuesto y peor atendido
        "20_44": _group(300, 0.80, 200.0, 0.227, 0.10),
        "65_plus": _group(300, 0.80, 200.0, 0.230, 0.10),
    }
    return {"optimized_overbooking": {"age_group": {"min_n": 30, "groups": groups}}}


def test_reading_sentences_name_most_exposed_group_as_is() -> None:
    rows, min_n = equidad.group_rows(equity_body(), "optimized_overbooking", "age_group")
    reference = equidad.reference_values(rows)
    flagged = equidad.flag_groups(rows, reference)
    sentences = equidad.reading_sentences(
        rows, flagged, "optimized_overbooking", "age_group", min_n
    )
    assert (
        "La exposición al sobrecupo va de 22,7 % a 26,8 % entre grupos de edad; "
        "el grupo 0-14 es el más expuesto."
    ) in sentences
    assert any("el grupo 0-14 es el que menos se atiende" in s for s in sentences)
    assert any(s == "Los grupos con menos de 30 entradas no se muestran." for s in sentences)


def test_flag_groups_marks_groups_outside_gap() -> None:
    rows, _ = equidad.group_rows(equity_body(), "optimized_overbooking", "age_group")
    flagged = equidad.flag_groups(rows, equidad.reference_values(rows))
    assert flagged["0_14"] == ["attention_rate"]  # 60 % frente a ~76 % del total
    assert flagged["20_44"] == [] and flagged["65_plus"] == []
    sentences = equidad.reading_sentences(rows, flagged, "optimized_overbooking", "age_group", None)
    assert any(s.startswith("▲ 1 de 3 grupos") and "0-14" in s for s in sentences)


def test_equity_without_gaps_reports_no_flags() -> None:
    same = {"a": _group(100, 0.8, 200.0, 0.2, 0.1), "b": _group(100, 0.8, 200.0, 0.2, 0.1)}
    rows, _ = equidad.group_rows({"fifo": {"insurance": {"groups": same}}}, "fifo", "insurance")
    flagged = equidad.flag_groups(rows, equidad.reference_values(rows))
    assert all(not v for v in flagged.values())
    sentences = equidad.reading_sentences(rows, flagged, "fifo", "insurance", None)
    assert "Ningún grupo queda fuera de la brecha permitida respecto del total." in sentences


def test_non_overbooking_policy_says_so_instead_of_inventing_a_gap() -> None:
    groups = {"a": _group(100, 0.8, 200.0, 0.0, 0.1), "b": _group(100, 0.8, 200.0, 0.0, 0.1)}
    rows, _ = equidad.group_rows({"fifo": {"age_group": {"groups": groups}}}, "fifo", "age_group")
    sentences = equidad.reading_sentences(
        rows, {r.value: [] for r in rows}, "fifo", "age_group", None
    )
    assert "no sobreagenda" in sentences[0]


def test_is_outside_gap_thresholds() -> None:
    assert equidad.is_outside_gap("attention_rate", 0.70, 0.80)  # 10 pp peor
    assert not equidad.is_outside_gap("attention_rate", 0.76, 0.80)  # 4 pp peor
    assert not equidad.is_outside_gap("attention_rate", 0.95, 0.80)  # mejor, no perjudica
    assert equidad.is_outside_gap("wait_attended_median", 240.0, 200.0)  # 20 % más espera
    assert not equidad.is_outside_gap("wait_attended_median", 220.0, 200.0)
    assert not equidad.is_outside_gap("attention_rate", 0.1, None)


def test_equity_page_is_built_with_table_and_flag_marker() -> None:
    body = equidad.build_equity(equity_body(), "optimized_overbooking", "age_group")
    text = text_of(body)
    assert "▲ 0-14" in text  # grupo marcado, también en la tabla equivalente
    assert len(graphs(body)) == 1
    empty = equidad.build_equity(equity_body(), "fifo", "age_group")
    assert "no tiene resultados de equidad" in text_of(empty)
