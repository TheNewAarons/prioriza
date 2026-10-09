"""Regresiones de la revisión del módulo `api/` (P12).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red ni datos reales; las claves son de prueba.
"""

from __future__ import annotations

import json
from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Any

import pytest
from api.auth import Role, User, UserDirectory
from api.jobs import InlineExecutor
from api.main import create_app
from api.plans import MemoryPlanStore, PermissionDenied, same_person
from api.settings import ApiSettings
from fastapi.testclient import TestClient
from shared.db.enums import ReviewStatus
from test_api_permissions import new_plan

GOOD_KEY = "k" * 40


def _write_users(tmp_path: Path, users: dict[str, Any]) -> Path:
    path = tmp_path / "users.json"
    path.write_text(json.dumps(users), encoding="utf-8")
    return path


# --- A2 y M1: cuatro ojos ---------------------------------------------------------------


def test_plan_without_requester_fails_closed() -> None:
    store = MemoryPlanStore()
    rec = store.add(new_plan("run-a", "ana"))
    # Simula un plan sin solicitante (como los que escribe la CLI con --persist).
    stored = store._plans[rec.id]
    stored.record = stored.record.__class__(**{**vars(stored.record), "requested_by": None})
    with pytest.raises(PermissionDenied, match="solicitante"):
        store.review(rec.id, User("carla", Role.REVISOR), ReviewStatus.APPROVED, None)
    assert store.get(rec.id).review_status is ReviewStatus.PENDING


@pytest.mark.parametrize("alias", ["Ana", " ana", "ANA ", "ana"])
def test_four_eyes_ignores_case_and_spaces(alias: str) -> None:
    assert same_person("ana", alias)
    store = MemoryPlanStore()
    rec = store.add(new_plan("run-a", "ana"))
    with pytest.raises(PermissionDenied, match="cuatro ojos"):
        store.review(rec.id, User(alias, Role.REVISOR), ReviewStatus.APPROVED, None)


# --- M1 y B2: archivo de usuarios -------------------------------------------------------


def test_users_file_accepts_valid_entries(tmp_path: Path) -> None:
    path = _write_users(tmp_path, {GOOD_KEY: {"user": " ana ", "role": "revisor"}})
    directory = UserDirectory.from_file(path)
    assert directory.authenticate(GOOD_KEY) == User("ana", Role.REVISOR)
    assert directory.authenticate("otra") is None


@pytest.mark.parametrize(
    ("users", "message"),
    [
        ({"EJEMPLO-" + "x" * 40: {"user": "ana", "role": "gestor"}}, "ejemplo"),
        ({"corta": {"user": "ana", "role": "gestor"}}, "ejemplo o de menos"),
        ({GOOD_KEY: {"user": "", "role": "gestor"}}, "nombre"),
        ({GOOD_KEY: {"user": None, "role": "gestor"}}, "nombre"),
        ({GOOD_KEY: {"user": "a" * 65, "role": "gestor"}}, "nombre"),
        ({GOOD_KEY: {"user": "ana", "role": "jefe"}}, "rol"),
        ({GOOD_KEY: "no-es-objeto"}, "entrada"),
    ],
)
def test_users_file_rejects_invalid_entries(
    tmp_path: Path, users: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        UserDirectory.from_file(_write_users(tmp_path, users))


def test_example_users_file_is_rejected() -> None:
    """El archivo de ejemplo del repositorio no sirve tal cual: hay que poner claves propias."""
    example = Path(__file__).resolve().parents[1] / "users.example.json"
    with pytest.raises(ValueError, match="ejemplo"):
        UserDirectory.from_file(example)


# --- M5: trabajos -----------------------------------------------------------------------


class HoldingExecutor(Executor):
    """Acepta trabajos y no los corre: quedan `queued` para probar los límites."""

    def __init__(self) -> None:
        self.held: list[Any] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.held.append((fn, args, kwargs))
        return Future()


class ClosedExecutor(Executor):
    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        raise RuntimeError("cannot schedule new futures after shutdown")


KEYS = {
    "g1": User("gestora.uno", Role.GESTOR),
    "g2": User("gestor.dos", Role.GESTOR),
    "g3": User("gestor.tres", Role.GESTOR),
    "l": User("lectura.test", Role.LECTURA),
}


def _client(run_dir: Path, tmp_path: Path, executor: Executor, **settings: Any) -> TestClient:
    cfg = ApiSettings(
        run_dir=run_dir,
        results_dir=tmp_path / "results",
        models_dir=tmp_path / "models",
        **settings,
    )
    app = create_app(cfg, store=MemoryPlanStore(), executor=executor, users=UserDirectory(KEYS))
    return TestClient(app)


def test_active_jobs_are_limited(run_dir: Path, tmp_path: Path) -> None:
    client = _client(
        run_dir, tmp_path, HoldingExecutor(), max_active_jobs_per_user=2, max_active_jobs=3
    )

    def ask(key: str) -> int:
        r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": key})
        return r.status_code

    assert [ask("g1"), ask("g1"), ask("g1")] == [202, 202, 429]
    assert [ask("g2"), ask("g3")] == [202, 429]  # total de 3 alcanzado


def test_submit_failure_marks_job_failed(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, ClosedExecutor())
    r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": "g1"})
    assert r.status_code == 202
    job = client.get(r.headers["Location"], headers={"X-API-Key": "l"}).json()
    assert job["status"] == "failed" and job["plan_id"] is None
    assert "referencia" in job["error"] and "/" not in job["error"]


# --- M3: errores sin rutas internas ---------------------------------------------------


def test_errors_do_not_leak_paths(tmp_path: Path) -> None:
    secret = tmp_path / "srv" / "secreto" / "run-x"
    client = TestClient(
        create_app(
            ApiSettings(run_dir=secret, results_dir=tmp_path, models_dir=tmp_path),
            store=MemoryPlanStore(),
            executor=InlineExecutor(),
            users=UserDirectory(KEYS),
        )
    )
    r = client.get("/v1/waitlist", headers={"X-API-Key": "l"})
    assert r.status_code == 503 and "secreto" not in r.text and str(tmp_path) not in r.text
    r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": "g1"})
    job = client.get(r.headers["Location"], headers={"X-API-Key": "l"}).json()
    assert job["status"] == "failed"
    assert "secreto" not in job["error"] and str(tmp_path) not in job["error"]
    # B3: sin corrida ubicable, /plans/current no devuelve el vigente de otra corrida.
    assert client.get("/v1/plans/current", headers={"X-API-Key": "l"}).status_code == 503


def test_missing_model_message_is_actionable(run_dir: Path, tmp_path: Path) -> None:
    client = _client(run_dir, tmp_path, InlineExecutor())
    r = client.post(
        "/v1/schedule-runs",
        json={"policy": "optimized", "overbooking": True},
        headers={"X-API-Key": "g1"},
    )
    job = client.get(r.headers["Location"], headers={"X-API-Key": "l"}).json()
    assert job["status"] == "failed"
    assert "make train-noshow" in job["error"] and str(tmp_path) not in job["error"]


# --- A1: equidad por grupo en la simulación ---------------------------------------------


def _group(value: str, exposure: float, rate: float) -> dict[str, Any]:
    return {
        "value": value,
        "entries": 100,
        "attended": 40,
        "attention_rate": rate,
        "wait_attended": {"median": 200.0, "p90": 400.0, "n": 40},
        "ges_breached": 3,
        "removed_no_show": 1,
        "no_show_realized_rate": 0.15,
        "overbooking_exposure": exposure,
        "overflow_share": 0.01,
    }


def test_simulation_reports_equity_by_group(run_dir: Path, tmp_path: Path) -> None:
    replicas = [
        {
            "seed": seed,
            "policies": {
                "optimized_overbooking": {
                    "groups": [
                        {
                            "dimension": "age_group",
                            "min_n": 30,
                            "groups": [_group("0_14", exp, 0.3), _group("65_plus", 0.2, 0.4)],
                            "max_gap_attention_rate": 0.1,
                            "max_gap_overbooking_exposure": exp - 0.2,
                            "max_gap_no_show_realized_rate": 0.0,
                        }
                    ]
                },
                "fifo": {"groups": []},
            },
        }
        for seed, exp in ((101, 0.26), (102, 0.28))
    ]
    data = {
        "generated_at": "2026-10-09T00:00:00+00:00",
        "run": {"id": "x"},
        "noshow_model_version": "m",
        "config": {},
        "supply_coverage": {},
        "aggregate": {"fifo": {}, "optimized_overbooking": {}},
        "comparisons": {},
        "limitations": [],
        "replicas": replicas,
    }
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "simulation.json").write_text(json.dumps(data), encoding="utf-8")
    client = _client(run_dir, tmp_path, InlineExecutor())
    body = client.get("/v1/simulation", headers={"X-API-Key": "l"}).json()
    age = body["equity"]["optimized_overbooking"]["age_group"]
    exposure = age["groups"]["0_14"]["overbooking_exposure"]
    assert exposure == pytest.approx({"mean": 0.27, "min": 0.26, "max": 0.28, "n": 2})
    assert age["groups"]["0_14"]["wait_attended_median"]["mean"] == 200.0
    assert age["max_gap_overbooking_exposure"]["max"] == pytest.approx(0.08)
    filtered = client.get(
        "/v1/simulation", params={"policy": "fifo"}, headers={"X-API-Key": "l"}
    ).json()
    assert "optimized_overbooking" not in filtered["equity"]
