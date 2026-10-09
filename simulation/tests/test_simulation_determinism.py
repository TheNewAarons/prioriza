"""Determinismo de la simulación (P10-T4): misma semilla ⇒ mismo resultado, semillas
distintas ⇒ llegadas distintas, números aleatorios comunes entre políticas y orden de
réplicas irrelevante.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

from typing import Any

import pytest
from simulation.config import POLICIES, SimulationConfig
from simulation.engine import simulate
from simulation.metrics import PolicyResult
from simulation.report import run_experiment
from simulation_test_support import fake_prediction, make_world


def _strip_scheduler_timing(scheduler: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el bloque ``scheduler`` sin los campos de tiempo real (no deterministas)."""
    out = dict(scheduler)
    out.pop("wall_time_total", None)
    weekly = []
    for row in scheduler.get("weekly") or []:
        row_copy = dict(row)
        row_copy.pop("wall_time_s", None)
        weekly.append(row_copy)
    if weekly:
        out["weekly"] = weekly
    return out


def _assert_result_equal(a: PolicyResult, b: PolicyResult, *, policy: str) -> None:
    """Compara eventos, series, resumen, grupos y scheduler (salvo tiempos reales)."""
    assert a.events == b.events, f"{policy}: events distintos"
    assert a.weekly == b.weekly, f"{policy}: weekly distinta"
    assert a.summary == b.summary, f"{policy}: summary distinto"
    assert a.groups == b.groups, f"{policy}: groups distintos"
    assert _strip_scheduler_timing(a.scheduler) == _strip_scheduler_timing(b.scheduler), (
        f"{policy}: scheduler distinto (salvo tiempos)"
    )


@pytest.mark.parametrize("policy", POLICIES)
def test_same_seed_gives_identical_result(monkeypatch: pytest.MonkeyPatch, policy: str) -> None:
    """Correr dos veces con la misma semilla reproduce el resultado exacto."""
    fake_prediction(monkeypatch, 0.3)
    world = make_world(
        n_stock=20,
        sessions_per_week=1.0,
        arrivals_per_week=4.0,
        intercept=-5.0,
        ges_every=3,
    )
    config = SimulationConfig(weeks=4, replica_seeds=(201,))
    first = simulate(world, policy, config, 201)
    second = simulate(world, policy, config, 201)
    _assert_result_equal(first, second, policy=policy)


def test_different_seeds_give_different_arrivals() -> None:
    """Semillas distintas ⇒ llegadas distintas (causa ``arrival`` en los eventos)."""
    world = make_world(n_stock=8, sessions_per_week=1.0, arrivals_per_week=6.0)
    config = SimulationConfig(weeks=4, replica_seeds=(301,))
    a = simulate(world, "priority", config, 301)
    b = simulate(world, "priority", config, 302)
    arrivals_a = [(day, eid) for day, eid, _, _, c in a.events if c == "arrival"]
    arrivals_b = [(day, eid) for day, eid, _, _, c in b.events if c == "arrival"]
    assert a.summary["arrivals_total"] != b.summary["arrivals_total"] or arrivals_a != arrivals_b


def test_same_seed_gives_same_arrivals_across_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con la misma semilla, las cuatro políticas ven exactamente las mismas llegadas."""
    fake_prediction(monkeypatch, 0.2)
    world = make_world(
        n_stock=15,
        sessions_per_week=1.0,
        arrivals_per_week=5.0,
        intercept=0.0,
    )
    config = SimulationConfig(weeks=4, replica_seeds=(401,))
    results = {p: simulate(world, p, config, 401) for p in POLICIES}
    reference = results[POLICIES[0]]
    ref_arrivals = {(day, eid) for day, eid, _, _, c in reference.events if c == "arrival"}
    ref_stock = {(day, eid) for day, eid, frm, _, c in reference.events if c == "stock"}
    for policy, r in results.items():
        arrivals = {(day, eid) for day, eid, _, _, c in r.events if c == "arrival"}
        stock = {(day, eid) for day, eid, frm, _, c in r.events if c == "stock"}
        assert arrivals == ref_arrivals, f"{policy}: llegadas distintas"
        assert stock == ref_stock, f"{policy}: stock inicial distinto"
        assert r.summary["arrivals_total"] == reference.summary["arrivals_total"]


def test_run_experiment_is_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_experiment`` dos veces con la misma config ⇒ payload idéntico salvo reloj."""
    fake_prediction(monkeypatch, 0.25)
    world = make_world(
        n_stock=12,
        sessions_per_week=1.0,
        arrivals_per_week=3.0,
        intercept=-2.0,
        ges_every=4,
    )
    config = SimulationConfig(weeks=3, replica_seeds=(501, 502))
    first = run_experiment(world, config)
    second = run_experiment(world, config)

    # Las únicas claves que pueden cambiar son las de reloj/tiempo.
    def _strip(payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        out.pop("generated_at", None)
        out.pop("timing", None)
        # Dentro de cada réplica, el scheduler también trae wall_time.
        replicas = []
        for replica in out["replicas"]:
            policies = {}
            for name, block in replica["policies"].items():
                block_copy = dict(block)
                if "scheduler" in block_copy:
                    block_copy["scheduler"] = _strip_scheduler_timing(block_copy["scheduler"])
                policies[name] = block_copy
            replicas.append({**replica, "policies": policies})
        out["replicas"] = replicas
        return out

    assert _strip(first) == _strip(second)


def test_replica_seed_order_does_not_change_per_seed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El orden de ``replica_seeds`` no cambia el resultado de cada semilla."""
    fake_prediction(monkeypatch, 0.3)
    world = make_world(
        n_stock=10,
        sessions_per_week=1.0,
        arrivals_per_week=3.0,
        intercept=0.0,
    )
    cfg_ab = SimulationConfig(weeks=3, replica_seeds=(101, 102))
    cfg_ba = SimulationConfig(weeks=3, replica_seeds=(102, 101))
    payload_ab = run_experiment(world, cfg_ab)
    payload_ba = run_experiment(world, cfg_ba)

    by_seed_ab: dict[int, dict[str, Any]] = {
        r["seed"]: r["policies"] for r in payload_ab["replicas"]
    }
    by_seed_ba: dict[int, dict[str, Any]] = {
        r["seed"]: r["policies"] for r in payload_ba["replicas"]
    }
    assert set(by_seed_ab) == set(by_seed_ba) == {101, 102}
    for seed in (101, 102):
        for policy in POLICIES:
            sum_ab = by_seed_ab[seed][policy]["summary"]
            sum_ba = by_seed_ba[seed][policy]["summary"]
            assert sum_ab == sum_ba, f"seed {seed}, policy {policy}: summary distinto"
