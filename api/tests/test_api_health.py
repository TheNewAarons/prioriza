"""Test del endpoint de salud."""

from api.main import create_app
from api.settings import ApiSettings
from fastapi.testclient import TestClient


def test_healthz() -> None:
    response = TestClient(create_app(ApiSettings())).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
