"""Cabeceras de seguridad y redacción de la clave en el panel (P16-T1).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from dashboard.api_client import ApiClient
from dashboard.app import server
from dashboard.config import DashboardSettings
from dashboard.session import attempt_login
from shared.logging import clear_secrets


def test_security_headers_on_pages_and_healthz() -> None:
    http = server.test_client()
    for path in ("/", "/lista", "/healthz"):
        headers = http.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["Cache-Control"] == "no-store"
        csp = headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp


def test_debug_is_off_by_default() -> None:
    assert DashboardSettings().debug is False


def test_cli_refuses_debug_on_public_host() -> None:
    from dashboard.cli import main

    with pytest.raises(SystemExit, match="debug"):
        main(["--debug", "--host", "0.0.0.0"])


def test_api_key_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    key = "clave-de-panel-muy-secreta"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user": "ana", "role": "lectura"})

    client = ApiClient("http://api.test", transport=httpx.MockTransport(handler))
    try:
        assert attempt_login(client, key).session is not None
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("dashboard").warning("falló la llamada con %s", key)
            logging.getLogger("werkzeug").warning("GET /?api_key=%s", key)
    finally:
        clear_secrets()
    assert key not in caplog.text
