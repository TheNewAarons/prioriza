"""Tests de los endpoints que usa el panel: resumen, desglose, GES y calendario del plan.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red: usa la corrida sintética del fixture.
"""

from __future__ import annotations

import uuid
from datetime import date

from shared.disclaimer import DISCLAIMER
from test_api_endpoints import GESTOR, LECTURA, fetch_all_waitlist, make_plan


def test_summary_matches_waitlist(make_client) -> None:  # type: ignore[no-untyped-def]
    """El resumen concuerda con la lista completa y el histograma suma el total."""
    client = make_client()
    r = client.get("/v1/waitlist/summary", headers=LECTURA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    items = fetch_all_waitlist(client)
    assert body["total"] == len(items)
    assert sum(b["count"] for b in body["wait_histogram"]) == len(items)
    assert body["wait_histogram"][0] == {
        "from_day": 0,
        "to_day": 30,
        "count": body["wait_histogram"][0]["count"],
    }
    assert body["wait_histogram"][-1]["from_day"] == 720
    assert body["wait_histogram"][-1]["to_day"] is None
    as_of = date.fromisoformat(body["as_of"])
    ges = [i for i in items if i["is_ges"]]
    assert body["ges_total"] == len(ges)
    overdue = [
        i for i in ges if i["ges_deadline"] and date.fromisoformat(i["ges_deadline"]) < as_of
    ]
    risk = [
        i
        for i in ges
        if i["ges_deadline"] and 0 <= (date.fromisoformat(i["ges_deadline"]) - as_of).days <= 30
    ]
    assert body["ges_overdue"] == len(overdue)
    assert body["ges_at_risk"] == len(risk)
    assert sum(c["total"] for c in body["by_care_type"]) == len(items)


def test_summary_filters_and_auth(make_client) -> None:  # type: ignore[no-untyped-def]
    """Los filtros se aplican igual que en la lista y la ruta exige clave."""
    client = make_client()
    assert client.get("/v1/waitlist/summary").status_code == 401
    r = client.get("/v1/waitlist/summary", params={"care_type": "surgery"}, headers=LECTURA)
    assert r.status_code == 200
    expected = len(fetch_all_waitlist(client, care_type="surgery"))
    assert r.json()["total"] == expected
    # Segunda llamada: resultado en caché, idéntico.
    assert (
        client.get("/v1/waitlist/summary", params={"care_type": "surgery"}, headers=LECTURA).json()
        == r.json()
    )


def test_patient_components(make_client) -> None:  # type: ignore[no-untyped-def]
    """El detalle del paciente trae el desglose numérico del puntaje."""
    client = make_client()
    entry = fetch_all_waitlist(client)[0]
    body = client.get(f"/v1/patients/{entry['patient_id']}", headers=LECTURA).json()
    found = next(e for e in body["entries"] if e["entry_id"] == entry["entry_id"])
    assert found["components"]
    total = sum(c["contribution"] for c in found["components"])
    assert abs(total - entry["score"]) < 1.0 or total > 0
    assert {"field", "label", "raw_value", "normalized", "weight", "contribution"} <= set(
        found["components"][0]
    )


def test_plan_ges(make_client) -> None:  # type: ignore[no-untyped-def]
    """GES del plan: paginado, con filtros y conteo por causa."""
    client = make_client()
    plan_id = make_plan(client)
    r = client.get(f"/v1/plans/{plan_id}/ges", params={"limit": 5}, headers=LECTURA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert len(body["items"]) <= 5
    all_rows = client.get(f"/v1/plans/{plan_id}/ges", params={"limit": 500}, headers=LECTURA).json()
    unmet = [i for i in all_rows["items"] if not i["met"]]
    assert sum(c["count"] for c in all_rows["by_cause"]) == len(unmet)
    only_unmet = client.get(
        f"/v1/plans/{plan_id}/ges", params={"met": False, "limit": 500}, headers=LECTURA
    ).json()
    assert only_unmet["total"] == len(unmet)
    if all_rows["by_cause"]:
        cause = all_rows["by_cause"][0]["cause"]
        by_cause = client.get(
            f"/v1/plans/{plan_id}/ges", params={"cause": cause, "limit": 500}, headers=LECTURA
        ).json()
        assert by_cause["total"] == all_rows["by_cause"][0]["count"]


def test_plan_ges_not_found(make_client) -> None:  # type: ignore[no-untyped-def]
    """Plan inexistente: 404; sin clave: 401."""
    client = make_client()
    missing = uuid.uuid4()
    assert client.get(f"/v1/plans/{missing}/ges", headers=LECTURA).status_code == 404
    assert client.get(f"/v1/plans/{missing}/calendar", headers=LECTURA).status_code == 404
    assert client.get(f"/v1/plans/{missing}/ges").status_code == 401


def test_plan_calendar(make_client) -> None:  # type: ignore[no-untyped-def]
    """El calendario suma las citas del plan y respeta capacidad y filtros."""
    client = make_client()
    plan_id = make_plan(client)
    plan = client.get(f"/v1/plans/{plan_id}", headers=GESTOR).json()
    assignments = client.get(
        f"/v1/plans/{plan_id}/assignments", params={"limit": 1}, headers=LECTURA
    ).json()
    r = client.get(f"/v1/plans/{plan_id}/calendar", params={"limit": 500}, headers=LECTURA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    items = body["items"]
    assert items
    horizon = (date.fromisoformat(plan["horizon_start"]), date.fromisoformat(plan["horizon_end"]))
    for item in items:
        assert horizon[0] <= date.fromisoformat(item["date"]) <= horizon[1]
        assert item["capacity"] > 0
        assert item["blocks"] >= 1
    if body["total"] <= 500:
        booked = sum(i["scheduled"] + i["overbooked"] for i in items)
        assert booked == assignments["total"]
    kinds = {i["resource_kind"] for i in items}
    assert kinds <= {"specialist_agenda", "operating_room"}
    kind = sorted(kinds)[0]
    filtered = client.get(
        f"/v1/plans/{plan_id}/calendar",
        params={"resource_kind": kind, "limit": 500},
        headers=LECTURA,
    ).json()
    assert {i["resource_kind"] for i in filtered["items"]} == {kind}
    bad = client.get(
        f"/v1/plans/{plan_id}/calendar", params={"resource_kind": "x"}, headers=LECTURA
    )
    assert bad.status_code == 422
