"""Humo del flujo completo: gestor pide `fifo`, revisor aprueba, gestor activa.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Los permisos finos (P12-T2) y cada endpoint
(P12-T3) se prueban en otros archivos.
"""

from __future__ import annotations

from shared.disclaimer import DISCLAIMER


def h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def test_full_flow(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()

    assert client.get("/v1/waitlist").status_code == 401
    me = client.get("/v1/me", headers=h("clave-gestor")).json()
    assert me == {"user": "gestora.test", "role": "gestor"}

    wl = client.get("/v1/waitlist?limit=5", headers=h("clave-lectura"))
    assert wl.status_code == 200
    body = wl.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["total"] > 0
    assert len(body["items"]) == 5
    patient_id = body["items"][0]["patient_id"]
    pat = client.get(f"/v1/patients/{patient_id}", headers=h("clave-lectura")).json()
    assert pat["disclaimer"] == DISCLAIMER
    assert any(e["explanation"] for e in pat["entries"])

    # El gestor pide la programación; el ejecutor inmediato la deja terminada.
    created = client.post(
        "/v1/schedule-runs",
        json={"policy": "fifo", "horizon_weeks": 4},
        headers=h("clave-gestor"),
    )
    assert created.status_code == 202
    job = created.json()
    assert created.headers["Location"] == f"/v1/schedule-runs/{job['job_id']}"
    job = client.get(f"/v1/schedule-runs/{job['job_id']}", headers=h("clave-lectura")).json()
    assert job["status"] == "succeeded", job
    assert job["disclaimer"] == DISCLAIMER
    plan_id = job["plan_id"]

    plan = client.get(f"/v1/plans/{plan_id}", headers=h("clave-lectura")).json()
    assert plan["review_status"] == "pending"
    assert plan["is_current"] is False
    assert plan["requested_by"] == "gestora.test"
    assert plan["disclaimer"] == DISCLAIMER

    # Sin aprobar no se puede activar.
    early = client.post(f"/v1/plans/{plan_id}/activate", headers=h("clave-gestor"))
    assert early.status_code == 409

    # El gestor no revisa; el revisor sí.
    assert (
        client.post(
            f"/v1/plans/{plan_id}/review",
            json={"decision": "approved"},
            headers=h("clave-gestor"),
        ).status_code
        == 403
    )
    approved = client.post(
        f"/v1/plans/{plan_id}/review",
        json={"decision": "approved", "note": "Revisado en el humo."},
        headers=h("clave-revisor"),
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"

    # La decisión es final.
    again = client.post(
        f"/v1/plans/{plan_id}/review",
        json={"decision": "rejected"},
        headers=h("clave-revisor"),
    )
    assert again.status_code == 409

    active = client.post(
        f"/v1/plans/{plan_id}/activate", json={"note": "vigente"}, headers=h("clave-gestor")
    )
    assert active.status_code == 200
    assert active.json()["is_current"] is True

    current = client.get("/v1/plans/current", headers=h("clave-lectura"))
    assert current.status_code == 200
    assert current.json()["plan_id"] == plan_id

    assignments = client.get(f"/v1/plans/{plan_id}/assignments?limit=3", headers=h("clave-lectura"))
    assert assignments.json()["total"] > 0
    expl = client.get(
        f"/v1/plans/{plan_id}/explanations?status=scheduled&limit=2", headers=h("clave-lectura")
    )
    assert expl.status_code == 200
    audit = client.get(f"/v1/plans/{plan_id}/reviews", headers=h("clave-lectura")).json()
    assert [r["action"] for r in audit["items"]] == ["approve", "activate"]
    assert [r["role"] for r in audit["items"]] == ["revisor", "gestor"]


def test_openapi_documents_security(make_client) -> None:  # type: ignore[no-untyped-def]
    spec = make_client().get("/openapi.json").json()
    scheme = spec["components"]["securitySchemes"]
    assert any(s["type"] == "apiKey" and s["name"] == "X-API-Key" for s in scheme.values())


def test_four_eyes_and_single_current(make_client) -> None:  # type: ignore[no-untyped-def]
    import uuid

    import pytest
    from api.auth import Role, User
    from api.plans import InvalidTransition, PermissionDenied
    from shared.db.enums import ReviewStatus

    client = make_client()
    store = client.app.state.services.store  # type: ignore[attr-defined]
    ids = []
    for _ in range(2):
        job = client.post(
            "/v1/schedule-runs", json={"policy": "priority"}, headers=h("clave-gestor")
        ).json()
        ids.append(
            uuid.UUID(
                client.get(f"/v1/schedule-runs/{job['job_id']}", headers=h("clave-gestor")).json()[
                    "plan_id"
                ]
            )
        )

    # Un usuario con rol revisor que pidió el plan no puede revisarlo.
    with pytest.raises(PermissionDenied):
        store.review(ids[0], User("gestora.test", Role.REVISOR), ReviewStatus.APPROVED, None)

    for plan_id in ids:
        store.review(plan_id, User("revisor.test", Role.REVISOR), ReviewStatus.APPROVED, None)
    gestor = User("gestora.test", Role.GESTOR)
    store.activate(ids[0], gestor, None)
    with pytest.raises(InvalidTransition):  # ya es el vigente
        store.activate(ids[0], gestor, None)
    store.activate(ids[1], gestor, None)
    assert [p.is_current for p in (store.get(ids[0]), store.get(ids[1]))] == [False, True]
    assert store.list_plans(current=True).total == 1
    actions = [r.action.value for r in store.reviews(ids[0])]
    assert actions == ["approve", "activate", "deactivate"]
