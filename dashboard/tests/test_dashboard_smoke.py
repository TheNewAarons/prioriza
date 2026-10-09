"""Pruebas de humo del panel: cliente HTTP, páginas registradas y lógica pura (sin red)."""

import httpx
import pytest
from dashboard.api_client import ApiAuthError, ApiClient, ApiForbidden, ApiUnavailable
from dashboard.app import app, server
from dashboard.session import Session, attempt_login
from dashboard.views.lista import build_params, ges_state, resolve_page
from dashboard.views.programacion import build_run_request, decision_view
from dashboard.views.simulacion import verdict


def _client(handler):  # type: ignore[no-untyped-def]
    return ApiClient("http://api.test", transport=httpx.MockTransport(handler))


def test_pages_are_served() -> None:
    http = server.test_client()
    for path in ("/", "/lista", "/programacion", "/simulacion", "/equidad"):
        assert http.get(path).status_code == 200
    assert "Prioriza" in str(app.layout)


def test_login_valid_and_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["X-API-Key"] == "buena-clave":
            return httpx.Response(200, json={"user": "ana", "role": "gestor"})
        return httpx.Response(401, json={"detail": "x"})

    client = _client(handler)
    ok = attempt_login(client, "buena-clave")
    assert ok.session is not None and ok.session.role == "gestor"
    assert "buena-clave" not in repr(ok.session)
    assert attempt_login(client, "mala").error is not None
    assert attempt_login(client, "  ").error is not None


def test_client_errors_are_typed() -> None:
    client = _client(lambda r: httpx.Response(403, json={"detail": "no puedes"}))
    with pytest.raises(ApiForbidden, match="no puedes"):
        client.me("k")
    client = _client(lambda r: httpx.Response(401))
    with pytest.raises(ApiAuthError):
        client.me("k")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    with pytest.raises(ApiUnavailable, match="make api"):
        _client(boom).me("k")


def test_summary_is_cached() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"total": 1})

    client = _client(handler)
    client.waitlist_summary("k")
    client.waitlist_summary("k")
    assert len(calls) == 1


def test_pure_logic() -> None:
    from datetime import date

    assert build_params(
        service=None,
        specialty=None,
        care=None,
        priority=None,
        ges="true",
        tier=None,
        order=None,
        page=2,
    ) == {"limit": 50, "offset": 100, "order_by": "score", "is_ges": True}
    assert resolve_page("f-care", 3) == 0 and resolve_page("lista-table", 3) == 3
    assert ges_state(True, "2025-09-01", date(2025, 9, 30)) == "overdue"
    assert ges_state(True, "2025-10-15", date(2025, 9, 30)) == "risk"
    assert ges_state(False, None, date(2025, 9, 30)) is None
    with pytest.raises(ValueError):
        build_run_request("optimized", 99, [], 10)
    assert verdict(-5.0, -8.0, -2.0, -1) == "✓ Mejora"
    assert verdict(5.0, 2.0, 8.0, -1) == "● Empeora"
    plan = {"review_status": "pending", "requested_by": "ana", "is_current": False}
    assert decision_view("revisor", plan, "luis").show_review
    assert not decision_view("revisor", plan, "ANA").show_review
    assert not decision_view("lectura", plan, "x").show_review
    assert Session("k", "u", "gestor").role == "gestor"
