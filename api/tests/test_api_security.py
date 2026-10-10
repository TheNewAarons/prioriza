"""Controles de seguridad de la API (P16-T1): límites, cabeceras, entorno y redacción de logs.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red ni datos reales; las claves son de prueba.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
from api.auth import Role, User, UserDirectory
from api.jobs import InlineExecutor
from api.main import InsecureConfiguration, create_app
from api.plans import MemoryPlanStore
from api.settings import ApiSettings
from fastapi.testclient import TestClient
from shared.logging import clear_secrets, uninstall_redaction

H = {"X-API-Key": "clave-gestor"}
KEYS = {
    "clave-gestor": User("gestora.test", Role.GESTOR),
    "clave-revisor": User("revisor.test", Role.REVISOR),
}


def _client(run_dir: Path, tmp_path: Path, **overrides: object) -> TestClient:
    settings = ApiSettings(
        run_dir=run_dir,
        results_dir=tmp_path / "r",
        models_dir=tmp_path / "m",
        trusted_hosts=["testserver"],
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(
        settings,
        store=MemoryPlanStore(),
        executor=InlineExecutor(),
        users=UserDirectory(dict(KEYS)),
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_logging() -> object:
    yield
    uninstall_redaction()
    clear_secrets()


# --- tamaño del cuerpo ------------------------------------------------------------------


def test_body_too_large_by_content_length_is_413(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, max_body_bytes=100)
    resp = client.post("/v1/schedule-runs", headers=H, content=b"x" * 101)
    assert resp.status_code == 413
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_body_too_large_without_content_length_is_413(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, max_body_bytes=100)

    def chunks():  # type: ignore[no-untyped-def]
        yield b"x" * 60
        yield b"x" * 60

    resp = client.post("/v1/schedule-runs", headers=H, content=chunks())
    assert resp.status_code == 413


def test_small_body_still_works(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    assert client.post("/v1/schedule-runs", headers=H, json={"policy": "nope"}).status_code == 422


# --- largo de parámetros ----------------------------------------------------------------


def test_long_path_id_is_422(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    resp = client.get("/v1/patients/" + "a" * 65, headers=H)
    assert resp.status_code == 422
    assert client.get("/v1/patients/" + "a" * 64, headers=H).status_code != 422


def test_long_query_param_is_422(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    resp = client.get("/v1/waitlist", params={"specialty_code": "z" * 65}, headers=H)
    assert resp.status_code == 422


def test_long_review_note_is_422(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, max_note_length=10)
    resp = client.post(
        "/v1/plans/00000000-0000-0000-0000-000000000000/review",
        headers={"X-API-Key": "clave-revisor"},
        json={"decision": "approved", "note": "n" * 11},
    )
    assert resp.status_code == 422
    assert "nota" in resp.json()["detail"]


# --- tope de la programación ------------------------------------------------------------


def test_schedule_horizon_and_time_limit_caps(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    over_h = client.post(
        "/v1/schedule-runs", headers=H, json={"policy": "fifo", "horizon_weeks": 13}
    )
    over_t = client.post(
        "/v1/schedule-runs", headers=H, json={"policy": "fifo", "time_limit_s": 601}
    )
    assert over_h.status_code == 422 and "horizon_weeks" in over_h.json()["detail"]
    assert over_t.status_code == 422 and "time_limit_s" in over_t.json()["detail"]
    ok = client.post("/v1/schedule-runs", headers=H, json={"policy": "fifo", "horizon_weeks": 12})
    assert ok.status_code == 202


# --- límite de peticiones ---------------------------------------------------------------


def test_rate_limit_429_with_retry_after_and_healthz_exempt(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, rate_limit_per_minute=3)
    for _ in range(3):
        assert client.get("/v1/me", headers=H).status_code == 200
    resp = client.get("/v1/me", headers=H)
    assert resp.status_code == 429
    assert 1 <= int(resp.headers["Retry-After"]) <= 60
    # Otro usuario tiene su propio cubo y /healthz nunca se limita.
    assert client.get("/v1/me", headers={"X-API-Key": "clave-revisor"}).status_code == 200
    for _ in range(10):
        assert client.get("/healthz").status_code == 200


def test_rate_limit_window_slides() -> None:
    from api.security import RateLimitMiddleware

    now = [0.0]

    async def app(*_: object) -> None: ...

    limiter = RateLimitMiddleware(
        app, settings=ApiSettings(rate_limit_per_minute=2), clock=lambda: now[0]
    )
    assert limiter.check("u") is None and limiter.check("u") is None
    wait = limiter.check("u")
    assert wait == 60
    now[0] = 61.0
    assert limiter.check("u") is None


def test_rate_limit_fake_keys_share_ip_bucket(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, rate_limit_per_minute=2)
    codes = [
        client.get("/v1/me", headers={"X-API-Key": f"falsa-{i}"}).status_code for i in range(3)
    ]
    assert codes == [401, 401, 429]


# --- cabeceras --------------------------------------------------------------------------


def test_security_headers_on_every_response(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    for resp in (client.get("/healthz"), client.get("/v1/me"), client.get("/v1/me", headers=H)):
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert resp.headers["Cache-Control"] == "no-store"
        assert "default-src 'none'" in resp.headers["Content-Security-Policy"]


def test_docs_have_their_own_csp(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "cdn.jsdelivr.net" in resp.headers["Content-Security-Policy"]


# --- entorno ----------------------------------------------------------------------------


def test_production_disables_docs_unless_enabled(run_dir: Path, tmp_path: Path) -> None:
    prod = _client(run_dir, tmp_path, environment="production")
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert prod.get(path).status_code == 404
    forced = _client(run_dir, tmp_path, environment="production", docs_enabled=True)
    assert forced.get("/openapi.json").status_code == 200
    assert _client(run_dir, tmp_path).get("/openapi.json").status_code == 200


def _users_file(tmp_path: Path, mode: int) -> Path:
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"k" * 40: {"user": "ana", "role": "lectura"}}), encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_production_requires_users_file(tmp_path: Path) -> None:
    with pytest.raises(InsecureConfiguration, match="obligatorio"):
        create_app(ApiSettings(environment="production"))


def test_production_rejects_open_permissions(tmp_path: Path) -> None:
    settings = ApiSettings(environment="production", users_file=_users_file(tmp_path, 0o644))
    with pytest.raises(InsecureConfiguration, match="600"):
        create_app(settings)


def test_production_accepts_private_users_file(tmp_path: Path) -> None:
    settings = ApiSettings(environment="production", users_file=_users_file(tmp_path, 0o600))
    assert create_app(settings).docs_url is None


def test_development_only_warns_on_open_permissions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = ApiSettings(users_file=_users_file(tmp_path, 0o644))
    with caplog.at_level(logging.WARNING, logger="api"):
        create_app(settings)
    assert "permisos 600" in caplog.text


# --- CORS y hosts -----------------------------------------------------------------------


def test_no_cors_by_default_and_allowlist_when_set(run_dir: Path, tmp_path: Path) -> None:
    origin = {"Origin": "https://otro.example"}
    plain = _client(run_dir, tmp_path)
    assert "access-control-allow-origin" not in plain.get("/healthz", headers=origin).headers
    allowed = _client(run_dir, tmp_path, cors_origins=["https://otro.example"])
    resp = allowed.get("/healthz", headers=origin)
    assert resp.headers["access-control-allow-origin"] == "https://otro.example"
    denied = allowed.get("/healthz", headers={"Origin": "https://malo.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_untrusted_host_is_rejected(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path)
    r = client.get("/healthz", headers={"Host": "evil.example"})
    assert r.status_code == 400
    # Las cabeceras de seguridad envuelven también este rechazo.
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_trusted_hosts_accepts_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIORIZA_API_TRUSTED_HOSTS", "a.example, b.example")
    monkeypatch.setenv("PRIORIZA_API_CORS_ORIGINS", '["https://x.example"]')
    cfg = ApiSettings()
    assert cfg.trusted_hosts == ["a.example", "b.example"]
    assert cfg.cors_origins == ["https://x.example"]


# --- tiempo máximo de un trabajo ----------------------------------------------------------


def test_job_timeout_marks_failed(run_dir: Path, tmp_path: Path) -> None:
    import uuid

    from api.catalog import CatalogProvider
    from api.jobs import JobManager
    from api.schemas import JobStatus

    settings = ApiSettings(run_dir=run_dir, results_dir=tmp_path, models_dir=tmp_path)
    mgr = JobManager(
        executor=InlineExecutor(),
        store=MemoryPlanStore(),
        catalogs=CatalogProvider(settings),
        settings=settings,
    )
    from datetime import UTC, datetime

    from api.jobs import JobRecord
    from shared.db.enums import Policy

    job_id = uuid.uuid4()
    mgr._jobs[job_id] = JobRecord(job_id, JobStatus.RUNNING, Policy.FIFO, "ana", datetime.now(UTC))
    mgr._timeout(job_id)
    job = mgr.get(job_id)
    assert job.status is JobStatus.FAILED and "tiempo máximo" in (job.error or "")
    mgr._timeout(job_id)  # idempotente


# --- redacción en el access log real de uvicorn -----------------------------------------


def test_uvicorn_access_log_redacts_patient_id_and_key(
    run_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from uvicorn.logging import AccessFormatter

    _client(run_dir, tmp_path)  # create_app instala la redacción y registra las claves
    formatter = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    )
    log = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        log.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/v1/patients/P-000123?key=clave-gestor",
            "1.1",
            200,
        )
    record = caplog.records[-1]
    line = formatter.format(record)
    assert "/v1/patients/" in line and "200" in line
    assert "P-000123" not in line and "clave-gestor" not in line
    assert "P-000123" not in caplog.text and "clave-gestor" not in caplog.text


def test_app_loggers_never_show_known_keys(
    run_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _client(run_dir, tmp_path)
    with caplog.at_level(logging.INFO):
        logging.getLogger("api.jobs").error("falló con X-API-Key: clave-revisor y 12.345.678-5")
    assert "clave-revisor" not in caplog.text and "12.345.678" not in caplog.text
