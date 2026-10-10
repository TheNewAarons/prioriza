"""Exportar, comparar y explicar planes (P18-D).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red: la corrida sintética viene del fixture
de sesión `run_dir`.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import replace
from typing import Any

import polars as pl
import pytest
from api.compare import verdict
from api.export import HEADERS, cell, neutralize
from fastapi.testclient import TestClient
from shared.disclaimer import DISCLAIMER
from test_api_endpoints import GESTOR, LECTURA, make_plan


def parse(text: str) -> tuple[list[str], list[list[str]]]:
    """Lector CSV que salta las líneas `#`, como documenta la API."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    rows = list(csv.reader(io.StringIO("\n".join(lines))))
    return rows[0], rows[1:]


# ------------------------------------------------------------------ exportar


def test_export_csv_content_and_headers(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    r = client.get(f"/v1/plans/{plan_id}/export?format=csv", headers=LECTURA)
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    lines = r.text.splitlines()
    assert lines[0] == f"# aviso: {DISCLAIMER}"
    assert lines[1].startswith(f"# plan: {plan_id}; estado de revisión: pending")
    header, rows = parse(r.text)
    assert tuple(header) == HEADERS
    total = client.get(f"/v1/plans/{plan_id}/assignments?limit=1", headers=LECTURA).json()["total"]
    assert len(rows) == total == int(r.headers["x-total-rows"]) == int(r.headers["x-exported-rows"])
    assert all(len(row) == len(HEADERS) for row in rows)
    assert not any(ln.startswith("# truncado") for ln in lines)
    # Sin atributos protegidos ni datos personales: solo ids sintéticos.
    assert not {"sexo", "edad", "comuna", "previsión", "nombre", "rut"} & {
        h.lower() for h in header
    }


def test_export_default_format_and_unknown_format(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    assert client.get(f"/v1/plans/{plan_id}/export", headers=LECTURA).status_code == 200
    assert client.get(f"/v1/plans/{plan_id}/export?format=xlsx", headers=LECTURA).status_code == 422


def test_export_requires_key_and_known_plan(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    assert client.get(f"/v1/plans/{plan_id}/export").status_code == 401
    missing = client.get(f"/v1/plans/{uuid.uuid4()}/export", headers=LECTURA)
    assert missing.status_code == 404


def test_export_limit_offset_and_truncation_notice(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    url = f"/v1/plans/{plan_id}/export"
    full = client.get(url, headers=LECTURA)
    _, all_rows = parse(full.text)
    part = client.get(f"{url}?limit=5&offset=2", headers=LECTURA)
    _, rows = parse(part.text)
    assert rows == all_rows[2:7]
    assert part.headers["x-exported-rows"] == "5"
    assert part.headers["x-total-rows"] == str(len(all_rows))
    assert any(
        ln.startswith("# truncado: se exportaron 5 filas desde la 3")
        for ln in part.text.splitlines()
    )
    past = client.get(f"{url}?offset=999999", headers=LECTURA)
    assert past.status_code == 200
    assert parse(past.text)[1] == []
    assert past.headers["x-total-rows"] == str(len(all_rows))


def test_export_cap_is_enforced(make_client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRIORIZA_API_MAX_EXPORT_ROWS", "7")
    client = make_client()
    plan_id = make_plan(client)
    r = client.get(f"/v1/plans/{plan_id}/export", headers=LECTURA)
    assert r.headers["x-exported-rows"] == "7"
    assert "# truncado" in r.text
    over = client.get(f"/v1/plans/{plan_id}/export?limit=8", headers=LECTURA)
    assert over.status_code == 422
    assert "7" in over.json()["detail"]


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("=1+1", "'=1+1"),
        ("+cmd", "'+cmd"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("normal", "normal"),
        ("a=b", "a=b"),
        ("", ""),
    ],
)
def test_formula_neutralization(raw: str, safe: str) -> None:
    assert neutralize(raw) == safe
    assert cell(raw) == safe


def test_cell_formats() -> None:
    assert cell(None) == ""
    assert cell(True) == "sí"
    assert cell(False) == "no"
    assert cell(0.25) == "0.25"
    assert cell(5) == "5"


def test_export_neutralizes_formulas_in_stored_rows(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    store = client.app.state.services.store  # type: ignore[attr-defined]
    stored = store._plans[uuid.UUID(plan_id)]
    stored.assignments = stored.assignments.with_columns(specialty_code=pl.lit('=HYPERLINK("x")'))
    _, rows = parse(client.get(f"/v1/plans/{plan_id}/export", headers=LECTURA).text)
    assert {r[3] for r in rows} == {'\'=HYPERLINK("x")'}


# ------------------------------------------------------------------ comparar


def two_plans(client: TestClient) -> tuple[str, str]:
    return make_plan(client, "fifo"), make_plan(client, "priority")


def test_compare_plans(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    a, b = two_plans(client)
    r = client.get(f"/v1/plans/compare?a={a}&b={b}", headers=LECTURA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["a"]["plan_id"] == a
    assert body["b"]["policy"] == "priority"
    assert body["a"]["review_status"] == body["b"]["review_status"] == "pending"
    metrics = {m["key"]: m for m in body["metrics"]}
    assert {"scheduled", "q1_scheduled", "ges_met", "ges_unmet", "overbooked_flags"} <= set(metrics)
    plan_a = client.get(f"/v1/plans/{a}", headers=LECTURA).json()
    plan_b = client.get(f"/v1/plans/{b}", headers=LECTURA).json()
    sched = metrics["scheduled"]
    assert sched["a"] == plan_a["summary"]["scheduled"]
    assert sched["b"] == plan_b["summary"]["scheduled"]
    assert sched["diff"] == sched["b"] - sched["a"]
    assert metrics["overbooked_flags"]["better"] == "none"
    for m in body["metrics"]:
        if m["diff"] is not None and m["direction"] != "neutral":
            expected = (
                "tie"
                if m["diff"] == 0
                else ("b" if (m["diff"] > 0) == (m["direction"] == "higher_is_better") else "a")
            )
            assert m["better"] == expected
    assert body["equity"], "la equidad por grupo debe venir tal cual salió del plan"
    eq = body["equity"][0]
    assert {"dimension", "value", "key", "a", "b", "diff", "better"} <= set(eq)


def test_compare_shows_unfavourable_result(make_client) -> None:  # type: ignore[no-untyped-def]
    """Si B es peor en una métrica, `better` es `a`: no se oculta."""
    client = make_client()
    a, b = two_plans(client)
    store = client.app.state.services.store  # type: ignore[attr-defined]
    stored = store._plans[uuid.UUID(b)]
    report: dict[str, Any] = {**stored.record.report}
    report["summary"] = {**report["summary"], "scheduled": 0}
    report["ges"] = {**report["ges"], "unmet": 10**6}
    stored.record = replace(stored.record, report=report)
    body = client.get(f"/v1/plans/compare?a={a}&b={b}", headers=LECTURA).json()
    metrics = {m["key"]: m for m in body["metrics"]}
    assert metrics["scheduled"]["better"] == "a"
    assert metrics["scheduled"]["diff"] < 0
    assert metrics["ges_unmet"]["better"] == "a"


def test_compare_errors(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    a, b = two_plans(client)
    assert client.get(f"/v1/plans/compare?a={a}&b={b}").status_code == 401
    same = client.get(f"/v1/plans/compare?a={a}&b={a}", headers=LECTURA)
    assert same.status_code == 422
    missing = client.get(f"/v1/plans/compare?a={a}&b={uuid.uuid4()}", headers=LECTURA)
    assert missing.status_code == 404
    assert client.get(f"/v1/plans/compare?a={a}", headers=LECTURA).status_code == 422
    assert client.get(f"/v1/plans/compare?a=x&b={b}", headers=LECTURA).status_code == 422
    store = client.app.state.services.store  # type: ignore[attr-defined]
    stored = store._plans[uuid.UUID(b)]
    stored.record = replace(stored.record, run_id="otra-corrida")
    other = client.get(f"/v1/plans/compare?a={a}&b={b}", headers=LECTURA)
    assert other.status_code == 422
    assert "corridas distintas" in other.json()["detail"]


def test_compare_route_does_not_clash_with_plan_id(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    a, _ = two_plans(client)
    assert client.get(f"/v1/plans/{a}", headers=LECTURA).status_code == 200


def test_verdict_rules() -> None:
    assert verdict(1, 2, "higher_is_better") == "b"
    assert verdict(2, 1, "higher_is_better") == "a"
    assert verdict(1, 2, "lower_is_better") == "a"
    assert verdict(2, 2, "lower_is_better") == "tie"
    assert verdict(1, 2, "neutral") == "none"
    assert verdict(None, 2, "higher_is_better") == "none"


# ------------------------------------------------------------------ por qué este cupo


def first_entry(client: TestClient, plan_id: str, status: str) -> str:
    page = client.get(
        f"/v1/plans/{plan_id}/explanations?status={status}&limit=1", headers=LECTURA
    ).json()
    assert page["items"], status
    return str(page["items"][0]["entry_id"])


def test_entry_reason_scheduled(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    entry = first_entry(client, plan_id, "scheduled")
    r = client.get(f"/v1/plans/{plan_id}/entries/{entry}/reason", headers=LECTURA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["entry_id"] == entry
    assert body["status"] == "scheduled"
    assert body["policy"] == "fifo"
    assert body["phase"] == "fifo"
    assert body["assignment"]["entry_id"] == entry
    assert body["assignment"]["is_overbooked"] is False
    assert "Agendada" in body["text"]
    score = body["score"]
    assert score is not None
    assert score["rank"] >= 1
    assert score["components"]
    assert body["block_load"] is None  # fifo no guarda carga de sobrecupo


def test_entry_reason_not_scheduled_has_no_assignment(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    allx = client.get(f"/v1/plans/{plan_id}/explanations?limit=500", headers=LECTURA).json()
    other = next(i for i in allx["items"] if i["status"] != "scheduled")
    body = client.get(
        f"/v1/plans/{plan_id}/entries/{other['entry_id']}/reason", headers=LECTURA
    ).json()
    assert body["assignment"] is None
    assert body["phase"] is None
    assert body["status"] == other["status"]
    assert body["text"] == other["text"]


def test_entry_reason_ges_and_errors(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    ges = client.get(f"/v1/plans/{plan_id}/ges?limit=1", headers=LECTURA).json()
    assert ges["items"]
    entry = ges["items"][0]["entry_id"]
    body = client.get(f"/v1/plans/{plan_id}/entries/{entry}/reason", headers=LECTURA).json()
    assert body["ges"]["entry_id"] == entry
    assert body["ges"]["ges_deadline"] == ges["items"][0]["ges_deadline"]
    url = f"/v1/plans/{plan_id}/entries/{entry}/reason"
    assert client.get(url).status_code == 401
    unknown = client.get(f"/v1/plans/{plan_id}/entries/no-existe/reason", headers=LECTURA)
    assert unknown.status_code == 404
    no_plan = client.get(f"/v1/plans/{uuid.uuid4()}/entries/{entry}/reason", headers=LECTURA)
    assert no_plan.status_code == 404


def test_entry_reason_phase_and_block_load_for_optimized(make_client) -> None:  # type: ignore[no-untyped-def]
    """Con política optimizada la fase sale de `detail` y la carga del bloque, del informe."""
    client = make_client()
    plan_id = make_plan(client)
    entry = first_entry(client, plan_id, "scheduled")
    store = client.app.state.services.store  # type: ignore[attr-defined]
    stored = store._plans[uuid.UUID(plan_id)]
    slot = stored.assignments.filter(stored.assignments["entry_id"] == entry)["slot_id"][0]
    report = {
        **stored.record.report,
        "overbooking": {
            "blocks": [
                {
                    "slot_id": slot,
                    "capacity": 4,
                    "scheduled": 5,
                    "overbooked": 1,
                    "risk_exact": 0.07,
                }
            ]
        },
    }
    stored.record = replace(stored.record, policy="optimized", report=report)
    stored.explanations = stored.explanations.with_columns(
        detail=pl.when(pl.col("entry_id") == entry)
        .then(pl.lit("added_by_overbooking"))
        .otherwise(pl.col("detail"))
    )
    body = client.get(f"/v1/plans/{plan_id}/entries/{entry}/reason", headers=LECTURA).json()
    assert body["phase"] == "3b"
    assert body["block_load"] == {
        "capacity": 4,
        "scheduled": 5,
        "overbooked": 1,
        "risk_exact": 0.07,
    }


def test_gestor_can_also_read_new_endpoints(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = make_plan(client)
    assert client.get(f"/v1/plans/{plan_id}/export", headers=GESTOR).status_code == 200
