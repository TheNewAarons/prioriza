"""Tests rutinarios de cada endpoint de la API (P12-T3).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Cubre `/healthz`, `/v1/me`, lista de espera, paciente, programaciones, planes, simulación,
aviso obligatorio y OpenAPI. Los permisos y las invariantes de revisión y vigencia están en
`test_api_permissions.py`; el flujo completo, en `test_api_flow.py`. Sin red: la corrida
sintética viene del fixture de sesión `run_dir`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from shared.disclaimer import DISCLAIMER

GESTOR = {"X-API-Key": "clave-gestor"}
REVISOR = {"X-API-Key": "clave-revisor"}
LECTURA = {"X-API-Key": "clave-lectura"}

# Atributos protegidos o proxies que no deben salir en las asignaciones.
FORBIDDEN_COLUMNS = {"age_group", "insurance", "commune_code", "sex", "ethnicity", "nationality"}


def fetch_all_waitlist(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    """Recorre todas las páginas de la lista de espera con los filtros dados."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        r = client.get(
            "/v1/waitlist", params={**params, "limit": 500, "offset": offset}, headers=LECTURA
        )
        assert r.status_code == 200, r.text
        body = r.json()
        items.extend(body["items"])
        offset += 500
        if offset >= body["total"]:
            return items


def make_plan(client: TestClient, policy: str = "fifo") -> str:
    """Pide una programación sin modelo y devuelve el id del plan pendiente."""
    r = client.post(
        "/v1/schedule-runs", json={"policy": policy, "horizon_weeks": 4}, headers=GESTOR
    )
    assert r.status_code == 202, r.text
    job = client.get(r.headers["Location"], headers=LECTURA).json()
    assert job["status"] == "succeeded", job
    return str(job["plan_id"])


# ------------------------------------------------------------------ sistema


def test_healthz_without_key(make_client) -> None:  # type: ignore[no-untyped-def]
    """La sonda de salud no exige clave."""
    r = make_client().get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("key", "user", "role"),
    [
        ("clave-gestor", "gestora.test", "gestor"),
        ("clave-revisor", "revisor.test", "revisor"),
        ("clave-lectura", "lectura.test", "lectura"),
    ],
)
def test_me_by_role(make_client, key: str, user: str, role: str) -> None:  # type: ignore[no-untyped-def]
    """`/v1/me` devuelve usuario y rol de la clave."""
    r = make_client().get("/v1/me", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json() == {"user": user, "role": role}


# ------------------------------------------------------------------ lista de espera


def test_waitlist_pagination(make_client) -> None:  # type: ignore[no-untyped-def]
    """`total` es constante y las páginas no se solapan."""
    client = make_client()
    p1 = client.get("/v1/waitlist?limit=20&offset=0", headers=LECTURA).json()
    p2 = client.get("/v1/waitlist?limit=20&offset=20", headers=LECTURA).json()
    assert p1["total"] == p2["total"] > 40
    assert (p1["limit"], p1["offset"], p2["offset"]) == (20, 0, 20)
    assert len(p1["items"]) == len(p2["items"]) == 20
    ids1 = {i["entry_id"] for i in p1["items"]}
    ids2 = {i["entry_id"] for i in p2["items"]}
    assert not ids1 & ids2
    assert p1["disclaimer"] == DISCLAIMER


def test_waitlist_pagination_covers_total(make_client) -> None:  # type: ignore[no-untyped-def]
    """Recorrer todas las páginas entrega `total` entradas distintas."""
    client = make_client()
    total = client.get("/v1/waitlist?limit=1", headers=LECTURA).json()["total"]
    items = fetch_all_waitlist(client)
    assert len(items) == total
    assert len({i["entry_id"] for i in items}) == total


def test_waitlist_offset_past_end_is_empty(make_client) -> None:  # type: ignore[no-untyped-def]
    """Un `offset` mayor que `total` da página vacía, no error."""
    client = make_client()
    total = client.get("/v1/waitlist?limit=1", headers=LECTURA).json()["total"]
    r = client.get(f"/v1/waitlist?offset={total + 10}", headers=LECTURA)
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["total"] == total


@pytest.mark.parametrize(
    ("field", "param"),
    [
        ("health_service_code", "health_service_code"),
        ("specialty_code", "specialty_code"),
        ("care_type", "care_type"),
        ("clinical_priority", "clinical_priority"),
        ("is_ges", "is_ges"),
        ("tier", "tier"),
    ],
)
def test_waitlist_filters(make_client, field: str, param: str) -> None:  # type: ignore[no-untyped-def]
    """Cada filtro devuelve solo filas que lo cumplen y reduce el total."""
    client = make_client()
    everything = fetch_all_waitlist(client)
    value = everything[0][field]
    # Se prefiere un valor que no sea el de todas las filas, para que el filtro filtre algo.
    for row in everything:
        if row[field] != value:
            break
    wire = str(value).lower() if isinstance(value, bool) else str(value)
    filtered = fetch_all_waitlist(client, **{param: wire})
    expected = [r for r in everything if r[field] == value]
    assert filtered
    assert all(r[field] == value for r in filtered)
    assert {r["entry_id"] for r in filtered} == {r["entry_id"] for r in expected}


def test_waitlist_filter_is_ges_false(make_client) -> None:  # type: ignore[no-untyped-def]
    """`is_ges=false` también filtra (no se confunde con filtro ausente)."""
    client = make_client()
    rows = fetch_all_waitlist(client, is_ges="false")
    assert rows
    assert all(r["is_ges"] is False for r in rows)


def test_waitlist_filters_combine(make_client) -> None:  # type: ignore[no-untyped-def]
    """Dos filtros juntos son una intersección."""
    client = make_client()
    base = fetch_all_waitlist(client)[0]
    rows = fetch_all_waitlist(
        client, specialty_code=base["specialty_code"], care_type=base["care_type"]
    )
    assert rows
    assert all(
        r["specialty_code"] == base["specialty_code"] and r["care_type"] == base["care_type"]
        for r in rows
    )


def test_waitlist_filter_unknown_value_is_empty(make_client) -> None:  # type: ignore[no-untyped-def]
    """Una especialidad inexistente da lista vacía con `total` 0."""
    r = make_client().get("/v1/waitlist?specialty_code=__no_existe__", headers=LECTURA)
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


@pytest.mark.parametrize(
    ("order", "key", "reverse"),
    [("score", "score", True), ("entry_date", "entry_date", False)],
)
def test_waitlist_ordering(make_client, order: str, key: str, reverse: bool) -> None:  # type: ignore[no-untyped-def]
    """El orden pedido se cumple en toda la lista (puntaje descendente, fecha ascendente)."""
    items = fetch_all_waitlist(make_client(), order_by=order)
    values = [i[key] for i in items]
    assert values == sorted(values, reverse=reverse)


def test_waitlist_order_rank(make_client) -> None:  # type: ignore[no-untyped-def]
    """Con `order_by=rank` (por defecto) el puesto crece dentro de cada cola."""
    items = fetch_all_waitlist(make_client(), order_by="rank")
    queues: dict[tuple[Any, ...], list[int]] = {}
    for i in items:
        queue = (i["health_service_code"], i["specialty_code"], i["care_type"])
        queues.setdefault(queue, []).append(i["rank"])
    for ranks in queues.values():
        assert ranks == sorted(ranks)
        assert ranks[0] >= 1
        assert len(set(ranks)) == len(ranks)


def test_waitlist_item_fields(make_client) -> None:  # type: ignore[no-untyped-def]
    """Cada ítem trae los campos públicos del diseño y ninguno protegido."""
    item = make_client().get("/v1/waitlist?limit=1", headers=LECTURA).json()["items"][0]
    assert set(item) == {
        "entry_id",
        "patient_id",
        "health_service_code",
        "specialty_code",
        "care_type",
        "clinical_priority",
        "is_ges",
        "ges_deadline",
        "entry_date",
        "wait_days",
        "score",
        "rank",
        "tier",
    }


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=501", "offset=-1", "limit=abc", "care_type=inventado", "order_by=nombre"],
)
def test_waitlist_invalid_params_422(make_client, query: str) -> None:  # type: ignore[no-untyped-def]
    """Parámetros fuera de rango o de dominio se rechazan con 422."""
    assert make_client().get(f"/v1/waitlist?{query}", headers=LECTURA).status_code == 422


def test_waitlist_limit_bounds_accepted(make_client) -> None:  # type: ignore[no-untyped-def]
    """Los extremos 1 y 500 son válidos."""
    client = make_client()
    assert client.get("/v1/waitlist?limit=1", headers=LECTURA).status_code == 200
    assert client.get("/v1/waitlist?limit=500", headers=LECTURA).status_code == 200


# ------------------------------------------------------------------ pacientes


def test_patient_found_with_explanation(make_client) -> None:  # type: ignore[no-untyped-def]
    """El paciente trae sus entradas y la explicación del puntaje de las que esperan."""
    client = make_client()
    entry = client.get("/v1/waitlist?limit=1", headers=LECTURA).json()["items"][0]
    r = client.get(f"/v1/patients/{entry['patient_id']}", headers=LECTURA)
    assert r.status_code == 200
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["patient_id"] == entry["patient_id"]
    mine = [e for e in body["entries"] if e["entry_id"] == entry["entry_id"]]
    assert len(mine) == 1
    expl = mine[0]["explanation"]
    assert expl is not None
    assert expl["score"] == pytest.approx(entry["score"])
    assert expl["tier"] == entry["tier"]
    assert expl["lines"]
    assert expl["text"]
    assert mine[0]["rank"] == entry["rank"]
    # La prioridad clínica sale tal como entró.
    assert mine[0]["clinical_priority"] == entry["clinical_priority"]


def test_patient_not_found_404(make_client) -> None:  # type: ignore[no-untyped-def]
    """Un paciente inexistente da 404 con `detail`."""
    r = make_client().get("/v1/patients/no-existe", headers=LECTURA)
    assert r.status_code == 404
    assert "no existe" in r.json()["detail"]


# ------------------------------------------------------------------ programaciones


@pytest.mark.parametrize("policy", ["fifo", "priority"])
def test_schedule_run_accepted(make_client, policy: str) -> None:  # type: ignore[no-untyped-def]
    """`fifo` y `priority` responden 202 con `Location` y terminan con un plan pendiente."""
    client = make_client()
    r = client.post(
        "/v1/schedule-runs", json={"policy": policy, "horizon_weeks": 4}, headers=GESTOR
    )
    assert r.status_code == 202
    body = r.json()
    assert r.headers["Location"] == f"/v1/schedule-runs/{body['job_id']}"
    assert body["disclaimer"] == DISCLAIMER
    assert body["policy"] == policy
    assert body["requested_by"] == "gestora.test"
    job = client.get(r.headers["Location"], headers=LECTURA).json()
    assert job["status"] == "succeeded"
    assert job["error"] is None
    assert job["disclaimer"] == DISCLAIMER
    plan = client.get(f"/v1/plans/{job['plan_id']}", headers=LECTURA).json()
    assert plan["review_status"] == "pending"
    assert plan["is_current"] is False
    assert plan["policy"] == policy


@pytest.mark.parametrize(
    "body",
    [
        {"policy": "inventada"},
        {},
        {"policy": "fifo", "horizon_weeks": 0},
        {"policy": "fifo", "horizon_weeks": 53},
        {"policy": "optimized", "alpha": 0},
        {"policy": "optimized", "alpha": 1},
        {"policy": "fifo", "time_limit_s": 0},
        {"policy": "fifo", "campo_extra": 1},
    ],
)
def test_schedule_run_invalid_body_422(make_client, body: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    """Cuerpos inválidos se rechazan antes de encolar nada."""
    r = make_client().post("/v1/schedule-runs", json=body, headers=GESTOR)
    assert r.status_code == 422


def test_schedule_run_unknown_job_404(make_client) -> None:  # type: ignore[no-untyped-def]
    """Un trabajo inexistente da 404; un id no-uuid, 422."""
    client = make_client()
    assert client.get(f"/v1/schedule-runs/{uuid.uuid4()}", headers=LECTURA).status_code == 404
    assert client.get("/v1/schedule-runs/no-uuid", headers=LECTURA).status_code == 422


def test_schedule_run_failure_is_reported(make_client) -> None:  # type: ignore[no-untyped-def]
    """`optimized` con sobrecupo y sin modelo falla: queda `failed`, con mensaje y sin plan."""
    client = make_client()
    r = client.post(
        "/v1/schedule-runs",
        json={"policy": "optimized", "overbooking": True, "horizon_weeks": 4},
        headers=GESTOR,
    )
    assert r.status_code == 202
    job = client.get(r.headers["Location"], headers=LECTURA).json()
    assert job["status"] == "failed"
    assert job["error"]
    assert job["plan_id"] is None
    assert job["disclaimer"] == DISCLAIMER
    assert client.get("/v1/plans", headers=LECTURA).json()["total"] == 0


# ------------------------------------------------------------------ planes


def test_plans_list_and_filters(make_client) -> None:  # type: ignore[no-untyped-def]
    """Listado de planes con filtros `review_status` y `current`."""
    client = make_client()
    empty = client.get("/v1/plans", headers=LECTURA).json()
    assert empty["total"] == 0
    assert empty["items"] == []
    assert empty["disclaimer"] == DISCLAIMER

    first = make_plan(client, "fifo")
    second = make_plan(client, "priority")
    body = client.get("/v1/plans", headers=LECTURA).json()
    assert body["total"] == 2
    # Del más reciente al más antiguo.
    assert [p["plan_id"] for p in body["items"]] == [second, first]

    approved = client.post(
        f"/v1/plans/{first}/review", json={"decision": "approved"}, headers=REVISOR
    )
    assert approved.status_code == 200
    only_approved = client.get("/v1/plans?review_status=approved", headers=LECTURA).json()
    assert [p["plan_id"] for p in only_approved["items"]] == [first]
    only_pending = client.get("/v1/plans?review_status=pending", headers=LECTURA).json()
    assert [p["plan_id"] for p in only_pending["items"]] == [second]
    assert client.get("/v1/plans?review_status=rejected", headers=LECTURA).json()["total"] == 0

    assert client.get("/v1/plans?current=true", headers=LECTURA).json()["total"] == 0
    assert client.post(f"/v1/plans/{first}/activate", headers=GESTOR).status_code == 200
    current = client.get("/v1/plans?current=true", headers=LECTURA).json()
    assert [p["plan_id"] for p in current["items"]] == [first]
    not_current = client.get("/v1/plans?current=false", headers=LECTURA).json()
    assert [p["plan_id"] for p in not_current["items"]] == [second]


def test_plans_list_pagination_and_invalid(make_client) -> None:  # type: ignore[no-untyped-def]
    """Paginación de planes y validación de parámetros."""
    client = make_client()
    make_plan(client, "fifo")
    make_plan(client, "priority")
    page = client.get("/v1/plans?limit=1&offset=1", headers=LECTURA).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    for q in ("limit=0", "limit=501", "offset=-1", "review_status=otro", "current=quizas"):
        assert client.get(f"/v1/plans?{q}", headers=LECTURA).status_code == 422


def test_plan_detail(make_client) -> None:  # type: ignore[no-untyped-def]
    """El detalle trae resumen del informe, equidad y aviso."""
    client = make_client()
    plan_id = make_plan(client)
    r = client.get(f"/v1/plans/{plan_id}", headers=LECTURA)
    assert r.status_code == 200
    body = r.json()
    assert body["plan_id"] == plan_id
    assert body["disclaimer"] == DISCLAIMER
    assert body["review_status"] == "pending"
    assert body["requested_by"] == "gestora.test"
    assert isinstance(body["summary"], dict)
    assert isinstance(body["equity"], list)
    assert isinstance(body["warnings"], list)
    assert "request" in body["config"]


def test_plan_not_found_and_bad_id(make_client) -> None:  # type: ignore[no-untyped-def]
    """Uuid inexistente da 404 y un id no-uuid da 422 en todas las rutas por plan."""
    client = make_client()
    missing = uuid.uuid4()
    for suffix in ("", "/assignments", "/explanations", "/reviews"):
        assert client.get(f"/v1/plans/{missing}{suffix}", headers=LECTURA).status_code == 404
        assert client.get(f"/v1/plans/no-uuid{suffix}", headers=LECTURA).status_code == 422


def test_plan_current_404_without_current(make_client) -> None:  # type: ignore[no-untyped-def]
    """Sin plan vigente, `/v1/plans/current` da 404."""
    client = make_client()
    make_plan(client)
    assert client.get("/v1/plans/current", headers=LECTURA).status_code == 404


def test_plan_assignments(make_client) -> None:  # type: ignore[no-untyped-def]
    """Asignaciones: páginas sin solapamiento, columnas públicas y sin atributos protegidos."""
    client = make_client()
    plan_id = make_plan(client)
    url = f"/v1/plans/{plan_id}/assignments"
    p1 = client.get(f"{url}?limit=10&offset=0", headers=LECTURA).json()
    p2 = client.get(f"{url}?limit=10&offset=10", headers=LECTURA).json()
    assert p1["disclaimer"] == DISCLAIMER
    assert p1["total"] == p2["total"] > 20
    assert len(p1["items"]) == len(p2["items"]) == 10
    keys1 = {(i["entry_id"], i["slot_id"]) for i in p1["items"]}
    keys2 = {(i["entry_id"], i["slot_id"]) for i in p2["items"]}
    assert not keys1 & keys2
    starts = [i["scheduled_start"] for i in p1["items"] + p2["items"]]
    assert starts == sorted(starts)
    expected = {
        "entry_id",
        "patient_id",
        "slot_id",
        "specialty_code",
        "scheduled_start",
        "duration_min",
        "lead_days",
        "is_overbooked",
        "predicted_noshow_prob",
    }
    for item in p1["items"]:
        assert set(item) == expected
        assert not FORBIDDEN_COLUMNS & set(item)
    for q in ("limit=0", "limit=501", "offset=-1"):
        assert client.get(f"{url}?{q}", headers=LECTURA).status_code == 422


def test_plan_explanations_filter(make_client) -> None:  # type: ignore[no-untyped-def]
    """Explicaciones: el filtro `status` devuelve solo ese estado y los totales cuadran."""
    client = make_client()
    plan_id = make_plan(client)
    url = f"/v1/plans/{plan_id}/explanations"
    allx = client.get(f"{url}?limit=500", headers=LECTURA).json()
    assert allx["disclaimer"] == DISCLAIMER
    assert allx["total"] > 0
    for item in allx["items"]:
        assert set(item) == {"entry_id", "status", "detail", "text"}
    # Todos los estados presentes, recorriendo las páginas completas.
    statuses: set[str] = set()
    for offset in range(0, allx["total"], 500):
        page = client.get(f"{url}?limit=500&offset={offset}", headers=LECTURA).json()
        statuses |= {i["status"] for i in page["items"]}
    assert "scheduled" in statuses
    counts_total = 0
    for st in statuses:
        sub = client.get(f"{url}?status={st}&limit=500", headers=LECTURA).json()
        assert sub["total"] > 0
        assert all(i["status"] == st for i in sub["items"])
        counts_total += sub["total"]
    assert counts_total == allx["total"]
    none = client.get(f"{url}?status=__no_existe__", headers=LECTURA).json()
    assert none["total"] == 0
    assert none["items"] == []
    page = client.get(f"{url}?limit=5&offset=5", headers=LECTURA).json()
    assert len(page["items"]) == 5
    assert client.get(f"{url}?limit=0", headers=LECTURA).status_code == 422


def test_plan_reviews_audit(make_client) -> None:  # type: ignore[no-untyped-def]
    """La auditoría parte vacía y registra aprobación y activación con usuario y rol."""
    client = make_client()
    plan_id = make_plan(client)
    url = f"/v1/plans/{plan_id}/reviews"
    empty = client.get(url, headers=LECTURA).json()
    assert empty["plan_id"] == plan_id
    assert empty["items"] == []
    assert empty["disclaimer"] == DISCLAIMER

    client.post(
        f"/v1/plans/{plan_id}/review",
        json={"decision": "approved", "note": "ok"},
        headers=REVISOR,
    )
    client.post(f"/v1/plans/{plan_id}/activate", headers=GESTOR)
    items = client.get(url, headers=LECTURA).json()["items"]
    assert [i["action"] for i in items] == ["approve", "activate"]
    assert (items[0]["user_name"], items[0]["role"], items[0]["note"]) == (
        "revisor.test",
        "revisor",
        "ok",
    )
    assert (items[1]["user_name"], items[1]["role"]) == ("gestora.test", "gestor")
    assert all(i["created_at"] for i in items)


def test_plan_current_returns_active_plan(make_client) -> None:  # type: ignore[no-untyped-def]
    """Tras aprobar y activar, `/v1/plans/current` devuelve ese plan con aviso."""
    client = make_client()
    plan_id = make_plan(client)
    client.post(f"/v1/plans/{plan_id}/review", json={"decision": "approved"}, headers=REVISOR)
    client.post(f"/v1/plans/{plan_id}/activate", headers=GESTOR)
    r = client.get("/v1/plans/current", headers=LECTURA)
    assert r.status_code == 200
    assert r.json()["plan_id"] == plan_id
    assert r.json()["is_current"] is True
    assert r.json()["disclaimer"] == DISCLAIMER


# ------------------------------------------------------------------ simulación


def _write_simulation(tmp_path, results_dir_name: str = "results") -> None:  # type: ignore[no-untyped-def]
    """Escribe un `simulation.json` mínimo y sintético."""
    out = tmp_path / results_dir_name
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "run": {"seed": 7, "size": 1000},
        "noshow_model_version": None,
        "config": {"months": 3},
        "supply_coverage": {"ratio": 0.5},
        "aggregate": {
            "fifo": {"wait_median": 100.0},
            "priority": {"wait_median": 90.0},
            "optimized": {"wait_median": 95.0},
            "optimized_overbooking": {"wait_median": 94.0},
        },
        "comparisons": {
            "priority_vs_fifo": {"delta": -10.0},
            "optimized_vs_fifo": {"delta": -5.0},
            "optimized_overbooking_vs_priority": {"delta": 4.0},
        },
        "limitations": ["Población sintética."],
        "replicas": [],
    }
    (out / "simulation.json").write_text(json.dumps(data), encoding="utf-8")


def test_simulation_ok_and_policy_filter(make_client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Responde 200 con el resumen y filtra agregados y comparaciones por política."""
    _write_simulation(tmp_path)
    client = make_client()
    r = client.get("/v1/simulation", headers=LECTURA)
    assert r.status_code == 200
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert set(body["aggregate"]) == {"fifo", "priority", "optimized", "optimized_overbooking"}
    assert len(body["comparisons"]) == 3
    assert body["limitations"] == ["Población sintética."]
    assert "replicas" not in body

    fifo = client.get("/v1/simulation?policy=fifo", headers=LECTURA).json()
    assert set(fifo["aggregate"]) == {"fifo"}
    assert set(fifo["comparisons"]) == {"priority_vs_fifo", "optimized_vs_fifo"}

    opt = client.get("/v1/simulation?policy=optimized", headers=LECTURA).json()
    assert set(opt["aggregate"]) == {"optimized", "optimized_overbooking"}
    assert set(opt["comparisons"]) == {"optimized_vs_fifo", "optimized_overbooking_vs_priority"}

    assert client.get("/v1/simulation?policy=otra", headers=LECTURA).status_code == 422


def test_simulation_missing_file_404(make_client) -> None:  # type: ignore[no-untyped-def]
    """Sin `results/simulation.json` responde 404."""
    r = make_client().get("/v1/simulation", headers=LECTURA)
    assert r.status_code == 404
    assert "simulate" in r.json()["detail"]


# ------------------------------------------------------------------ aviso


def test_disclaimer_in_every_data_response(make_client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Toda respuesta 200/202 de datos trae el aviso exacto de `shared.disclaimer`."""
    _write_simulation(tmp_path)
    client = make_client()
    patient_id = client.get("/v1/waitlist?limit=1", headers=LECTURA).json()["items"][0][
        "patient_id"
    ]
    created = client.post(
        "/v1/schedule-runs", json={"policy": "fifo", "horizon_weeks": 4}, headers=GESTOR
    )
    plan_id = client.get(created.headers["Location"], headers=LECTURA).json()["plan_id"]
    client.post(f"/v1/plans/{plan_id}/review", json={"decision": "approved"}, headers=REVISOR)
    review_resp = client.post(f"/v1/plans/{plan_id}/activate", headers=GESTOR)
    responses = [
        created,
        review_resp,
        client.get("/v1/waitlist", headers=LECTURA),
        client.get(f"/v1/patients/{patient_id}", headers=LECTURA),
        client.get(created.headers["Location"], headers=LECTURA),
        client.get("/v1/plans", headers=LECTURA),
        client.get("/v1/plans/current", headers=LECTURA),
        client.get(f"/v1/plans/{plan_id}", headers=LECTURA),
        client.get(f"/v1/plans/{plan_id}/assignments", headers=LECTURA),
        client.get(f"/v1/plans/{plan_id}/explanations", headers=LECTURA),
        client.get(f"/v1/plans/{plan_id}/reviews", headers=LECTURA),
        client.get("/v1/simulation", headers=LECTURA),
    ]
    for resp in responses:
        assert resp.status_code in (200, 202), (resp.url, resp.text)
        assert resp.json()["disclaimer"] == DISCLAIMER, resp.url


def test_review_response_has_disclaimer(make_client) -> None:  # type: ignore[no-untyped-def]
    """La respuesta de la revisión también lleva el aviso."""
    client = make_client()
    plan_id = make_plan(client)
    r = client.post(f"/v1/plans/{plan_id}/review", json={"decision": "rejected"}, headers=REVISOR)
    assert r.status_code == 200
    assert r.json()["disclaimer"] == DISCLAIMER


# ------------------------------------------------------------------ OpenAPI


def test_openapi_is_valid(make_client) -> None:  # type: ignore[no-untyped-def]
    """El esquema OpenAPI valida contra la especificación."""
    r = make_client().get("/openapi.json")
    assert r.status_code == 200
    validate(r.json())


def test_openapi_security_scheme(make_client) -> None:  # type: ignore[no-untyped-def]
    """Hay un esquema `apiKey` en la cabecera `X-API-Key`."""
    schemes = make_client().get("/openapi.json").json()["components"]["securitySchemes"]
    assert any(
        s["type"] == "apiKey" and s["in"] == "header" and s["name"] == "X-API-Key"
        for s in schemes.values()
    )


def test_openapi_v1_operations_declare_security_and_401(make_client) -> None:  # type: ignore[no-untyped-def]
    """Cada operación `/v1` exige clave y documenta la respuesta 401; `/healthz` no."""
    spec = make_client().get("/openapi.json").json()
    methods = {"get", "post", "put", "patch", "delete"}
    seen = 0
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in methods:
                continue
            if path.startswith("/v1"):
                seen += 1
                assert op.get("security"), f"{method} {path} sin security"
                assert "401" in op["responses"], f"{method} {path} sin 401"
            else:
                assert not op.get("security"), f"{method} {path} no debería exigir clave"
    assert seen >= 12
