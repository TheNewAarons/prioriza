"""Invariantes de permisos de los planes (P12-T2).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Sin red ni datos reales.

Invariantes, en cualquier secuencia de acciones de cualquier usuario:
1. Un plan no aprobado nunca está vigente.
2. Solo el rol revisor aprueba o rechaza, y nunca un plan que pidió el mismo usuario.
3. La decisión de revisión es final.
4. Hay a lo más un plan vigente por corrida sintética.
5. La auditoría explica el estado: cada aprobación, rechazo, activación y desactivación queda
   registrada con el usuario y el rol que la hicieron, y nada cambia sin registro.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest
from api.auth import Role, User
from api.plans import (
    ASSIGNMENT_COLUMNS,
    EXPLANATION_COLUMNS,
    InvalidTransition,
    MemoryPlanStore,
    NewPlan,
    PermissionDenied,
    PlanRecord,
)
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)
from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan
from shared.db.enums import ReviewAction, ReviewStatus

# La misma persona puede tener una clave de gestor y otra de revisor: los cuatro ojos se
# comparan por nombre de usuario, no por rol.
USERS = [
    User("ana", Role.GESTOR),
    User("beto", Role.GESTOR),
    User("carla", Role.REVISOR),
    User("ana", Role.REVISOR),
    User("dani", Role.LECTURA),
]
RUNS = ["run-a", "run-b"]


def _empty_plan() -> SchedulePlan:
    return SchedulePlan(
        policy="fifo",
        assignments=pl.DataFrame(
            {c: [] for c in ASSIGNMENT_COLUMNS},
            schema={
                "entry_id": pl.String,
                "patient_id": pl.String,
                "slot_id": pl.String,
                "specialty_code": pl.String,
                "scheduled_start": pl.Datetime("us", "UTC"),
                "duration_min": pl.Int64,
                "lead_days": pl.Int64,
                "is_overbooked": pl.Boolean,
                "predicted_noshow_prob": pl.Float64,
            },
        ),
        explanations=pl.DataFrame(
            {c: [] for c in EXPLANATION_COLUMNS},
            schema=dict.fromkeys(EXPLANATION_COLUMNS, pl.String),
        ),
        ges=pl.DataFrame(),
        standby=pl.DataFrame(),
        report={"review_status": "pending"},
        solver_status="NOT_APPLICABLE",
        objective_value=None,
        gap=None,
    )


def new_plan(run_id: str, requested_by: str) -> NewPlan:
    """Plan vacío: las reglas no dependen del contenido."""
    instance = cast(SchedulingInstance, SimpleNamespace(horizon_start=date(2025, 10, 6)))
    return NewPlan(
        run_id=run_id,
        plan=_empty_plan(),
        instance=instance,
        horizon_end_exclusive=date(2025, 11, 3),
        requested_by=requested_by,
        config={"policy": "fifo"},
    )


def check_invariants(store: MemoryPlanStore) -> None:
    """Invariantes 1-5 sobre el estado completo del almacén."""
    plans: list[PlanRecord] = store.list_plans(limit=10_000).items
    current_by_run = Counter(p.run_id for p in plans if p.is_current)
    assert all(n <= 1 for n in current_by_run.values()), current_by_run
    for p in plans:
        log = store.reviews(p.id)
        decisions = [r for r in log if r.action in (ReviewAction.APPROVE, ReviewAction.REJECT)]
        # 1. vigente ⇒ aprobado
        if p.is_current:
            assert p.review_status is ReviewStatus.APPROVED
        # 2. y 3. a lo más una decisión, de un revisor distinto del solicitante
        assert len(decisions) <= 1
        for r in decisions:
            assert r.role == Role.REVISOR.value
            assert r.user_name != p.requested_by
        # 5. el estado de revisión sale de la auditoría
        expected = {
            ReviewAction.APPROVE: ReviewStatus.APPROVED,
            ReviewAction.REJECT: ReviewStatus.REJECTED,
        }
        assert p.review_status is (
            expected[decisions[0].action] if decisions else ReviewStatus.PENDING
        )
        # activar y desactivar: solo gestor, solo sobre planes aprobados, y alternando
        toggles = [r for r in log if r.action in (ReviewAction.ACTIVATE, ReviewAction.DEACTIVATE)]
        for r in toggles:
            assert r.role == Role.GESTOR.value
        if toggles:
            assert p.review_status is ReviewStatus.APPROVED
            assert decisions and decisions[0].created_at < toggles[0].created_at
        actions = [r.action for r in toggles]
        assert all(
            a is (ReviewAction.ACTIVATE if i % 2 == 0 else ReviewAction.DEACTIVATE)
            for i, a in enumerate(actions)
        ), actions
        assert p.is_current == (bool(actions) and actions[-1] is ReviewAction.ACTIVATE)


class PlanMachine(RuleBasedStateMachine):
    """Secuencias arbitrarias de pedir, revisar y activar, contra un oráculo independiente."""

    plans = Bundle("plans")

    @initialize()
    def setup(self) -> None:
        self.store = MemoryPlanStore()
        # Oráculo: estado esperado por plan, calculado sin usar el dominio.
        self.expected: dict[uuid.UUID, dict[str, Any]] = {}

    @rule(
        target=plans,
        run_id=st.sampled_from(RUNS),
        requester=st.sampled_from([u for u in USERS if u.role is Role.GESTOR]),
    )
    def request(self, run_id: str, requester: User) -> uuid.UUID:
        rec = self.store.add(new_plan(run_id, requester.name))
        assert rec.review_status is ReviewStatus.PENDING and not rec.is_current
        self.expected[rec.id] = {
            "run": run_id,
            "by": requester.name,
            "status": ReviewStatus.PENDING,
            "current": False,
        }
        return rec.id

    @rule(
        plan_id=plans,
        actor=st.sampled_from(USERS),
        decision=st.sampled_from([ReviewStatus.APPROVED, ReviewStatus.REJECTED]),
    )
    def review(self, plan_id: uuid.UUID, actor: User, decision: ReviewStatus) -> None:
        exp = self.expected[plan_id]
        allowed = actor.role is Role.REVISOR and actor.name != exp["by"]
        pending = exp["status"] is ReviewStatus.PENDING
        if not allowed:
            with pytest.raises(PermissionDenied):
                self.store.review(plan_id, actor, decision, None)
        elif not pending:
            with pytest.raises(InvalidTransition):
                self.store.review(plan_id, actor, decision, None)
        else:
            rec = self.store.review(plan_id, actor, decision, "ok")
            exp["status"] = decision
            assert rec.review_status is decision
        assert self.store.get(plan_id).review_status is exp["status"]

    @rule(plan_id=plans, actor=st.sampled_from(USERS))
    def activate(self, plan_id: uuid.UUID, actor: User) -> None:
        exp = self.expected[plan_id]
        if actor.role is not Role.GESTOR:
            with pytest.raises(PermissionDenied):
                self.store.activate(plan_id, actor, None)
        elif exp["status"] is not ReviewStatus.APPROVED or exp["current"]:
            with pytest.raises(InvalidTransition):
                self.store.activate(plan_id, actor, None)
        else:
            self.store.activate(plan_id, actor, None)
            for other in self.expected.values():
                if other["run"] == exp["run"]:
                    other["current"] = False
            exp["current"] = True
        assert self.store.get(plan_id).is_current is exp["current"]

    @invariant()
    def matches_oracle_and_invariants(self) -> None:
        for plan_id, exp in self.expected.items():
            rec = self.store.get(plan_id)
            assert rec.review_status is exp["status"]
            assert rec.is_current is exp["current"]
        check_invariants(self.store)


PlanMachine.TestCase.settings = settings(max_examples=150, stateful_step_count=30, deadline=None)
test_plan_state_machine = PlanMachine.TestCase


# --- Mismas reglas por HTTP -------------------------------------------------------------

HEADERS = {
    "gestor": {"X-API-Key": "clave-gestor"},
    "gestor2": {"X-API-Key": "clave-gestor-2"},
    "revisor": {"X-API-Key": "clave-revisor"},
    "lectura": {"X-API-Key": "clave-lectura"},
}


def _new_plan_id(client: Any) -> str:
    r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers=HEADERS["gestor"])
    assert r.status_code == 202, r.text
    job = client.get(r.headers["Location"], headers=HEADERS["lectura"]).json()
    assert job["status"] == "succeeded", job
    return str(job["plan_id"])


def _plan(client: Any, plan_id: str) -> dict[str, Any]:
    r = client.get(f"/v1/plans/{plan_id}", headers=HEADERS["lectura"])
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


def test_only_gestor_requests_schedules(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    for who in ("revisor", "lectura"):
        r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers=HEADERS[who])
        assert r.status_code == 403, who
    assert client.get("/v1/plans", headers=HEADERS["lectura"]).json()["total"] == 0


def test_only_revisor_reviews(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = _new_plan_id(client)
    for who in ("gestor", "gestor2", "lectura"):
        for decision in ("approved", "rejected"):
            r = client.post(
                f"/v1/plans/{plan_id}/review", json={"decision": decision}, headers=HEADERS[who]
            )
            assert r.status_code == 403, (who, decision)
    plan = _plan(client, plan_id)
    assert plan["review_status"] == "pending" and plan["is_current"] is False
    assert (
        client.get(f"/v1/plans/{plan_id}/reviews", headers=HEADERS["lectura"]).json()["items"] == []
    )


@pytest.mark.parametrize("decision", [None, "rejected"])
def test_unapproved_plan_never_becomes_current(make_client, decision: str | None) -> None:  # type: ignore[no-untyped-def]
    """Pendiente o rechazado: ningún rol lo deja vigente, ni `/plans/current` lo devuelve."""
    client = make_client()
    plan_id = _new_plan_id(client)
    if decision:
        r = client.post(
            f"/v1/plans/{plan_id}/review", json={"decision": decision}, headers=HEADERS["revisor"]
        )
        assert r.status_code == 200
    for who in HEADERS:
        r = client.post(f"/v1/plans/{plan_id}/activate", headers=HEADERS[who])
        assert r.status_code == (409 if who.startswith("gestor") else 403), (who, r.text)
    assert _plan(client, plan_id)["is_current"] is False
    assert client.get("/v1/plans/current", headers=HEADERS["lectura"]).status_code == 404
    listed = client.get("/v1/plans", params={"current": True}, headers=HEADERS["lectura"]).json()
    assert listed["total"] == 0


def test_decision_is_final_and_audited(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    plan_id = _new_plan_id(client)
    url = f"/v1/plans/{plan_id}/review"
    reviewer = HEADERS["revisor"]
    assert client.post(url, json={"decision": "rejected"}, headers=reviewer).status_code == 200
    assert client.post(url, json={"decision": "approved"}, headers=reviewer).status_code == 409
    log = client.get(f"/v1/plans/{plan_id}/reviews", headers=HEADERS["lectura"]).json()["items"]
    assert [(r["action"], r["user_name"], r["role"]) for r in log] == [
        ("reject", "revisor.test", "revisor")
    ]
    assert _plan(client, plan_id)["review_status"] == "rejected"


def test_approved_plan_becomes_current_only_by_gestor(make_client) -> None:  # type: ignore[no-untyped-def]
    client = make_client()
    first, second = _new_plan_id(client), _new_plan_id(client)
    for plan_id in (first, second):
        r = client.post(
            f"/v1/plans/{plan_id}/review", json={"decision": "approved"}, headers=HEADERS["revisor"]
        )
        assert r.status_code == 200
    for who in ("revisor", "lectura"):
        assert client.post(f"/v1/plans/{first}/activate", headers=HEADERS[who]).status_code == 403
    assert client.post(f"/v1/plans/{first}/activate", headers=HEADERS["gestor2"]).status_code == 200
    assert client.post(f"/v1/plans/{second}/activate", headers=HEADERS["gestor"]).status_code == 200
    # Un solo vigente: el segundo reemplaza al primero y la desactivación queda registrada.
    assert _plan(client, first)["is_current"] is False
    assert _plan(client, second)["is_current"] is True
    current = client.get("/v1/plans/current", headers=HEADERS["lectura"]).json()
    assert current["plan_id"] == second
    log = client.get(f"/v1/plans/{first}/reviews", headers=HEADERS["lectura"]).json()["items"]
    assert [(r["action"], r["user_name"]) for r in log] == [
        ("approve", "revisor.test"),
        ("activate", "gestor.dos"),
        ("deactivate", "gestora.test"),
    ]


def test_every_v1_route_requires_a_valid_key(make_client) -> None:  # type: ignore[no-untyped-def]
    """Sin clave o con una clave desconocida, toda ruta `/v1` responde 401."""
    client = make_client()
    spec = client.get("/openapi.json").json()
    fake = "00000000-0000-0000-0000-000000000000"
    checked = 0
    for path, methods in spec["paths"].items():
        if not path.startswith("/v1"):
            continue
        url = path.replace("{plan_id}", fake).replace("{job_id}", fake)
        url = url.replace("{patient_id}", "nadie")
        for method in methods:
            for headers in ({}, {"X-API-Key": "clave-inventada"}):
                r = client.request(method.upper(), url, headers=headers, json={})
                assert r.status_code == 401, (method, path, headers, r.status_code)
                checked += 1
            assert methods[method].get("security"), (method, path)
    assert checked >= 2 * 14
