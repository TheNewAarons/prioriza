"""Tests básicos del panel."""

from dashboard.app import DISCLAIMER, app, server


def test_healthz() -> None:
    response = server.test_client().get("/healthz")
    assert response.status_code == 200


def test_layout_has_title_and_disclaimer() -> None:
    text = str(app.layout)
    assert "Prioriza" in text
    assert DISCLAIMER in text
