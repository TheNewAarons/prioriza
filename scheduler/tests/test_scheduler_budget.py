"""Presupuesto global de tiempo (formulación §8.5) y propiedad de R4 con citas previas y S3.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from scheduler.config import OverbookingConfig, SolverConfig
from scheduler.cpsat import assigned_entries
from scheduler.phases import run_optimized
from scheduler.plan import SchedulePlan, _build
from scheduler_test_support import (
    AS_OF,
    CNE_SPEC,
    HORIZON_START,
    IQ_SPEC,
    B,
    E,
    build_instance,
    example_instance,
    utc,
)
from test_scheduler_invariants import check_plan

from scheduler import SchedulerConfig, SchedulingInstance, greedy_schedule, solve

BUDGET_KEYS = {
    "unit",
    "total",
    "first_pass",
    "frontier",
    "spent",
    "exhausted",
    "phases_ended_by_limit",
    "overrun",
}


def _budget(plan: SchedulePlan) -> dict[str, Any]:
    budget = plan.report["solver"]["budget"]
    assert isinstance(budget, dict)
    return budget


def test_budget_block_on_easy_instance() -> None:
    plan = solve(example_instance(), SchedulerConfig(time_limit_s=120.0))
    b = _budget(plan)
    assert set(b) == BUDGET_KEYS
    assert b["unit"] == "deterministic" and b["total"] == 120.0
    first = b["first_pass"]
    assert first["allotted"] == pytest.approx(0.75 * 120.0)
    assert first["phases_1_3a"]["allotted"] + first["phases_3b_4"]["allotted"] == pytest.approx(
        first["allotted"]
    )
    assert b["spent"] == pytest.approx(first["spent"] + b["frontier"]["spent"])
    assert first["spent"] == pytest.approx(
        first["phases_1_3a"]["spent"] + first["phases_3b_4"]["spent"]
    )
    assert b["frontier"]["allotted"] == 0.0 and b["frontier"]["components_skipped"] == 0
    assert not b["exhausted"] and b["phases_ended_by_limit"] == 0 and b["overrun"] == 0.0
    assert plan.report["reproducible"] is True
    assert not any("time_budget_exhausted" in w for w in plan.report["warnings"])
    greedy = greedy_schedule(example_instance())
    assert greedy.report["solver"]["budget"] is None and greedy.report["reproducible"] is True


def test_whole_budget_goes_to_first_pass_without_frontier_expansion() -> None:
    plan = solve(example_instance(), SchedulerConfig(expand_on_frontier=False))
    assert _budget(plan)["first_pass"]["allotted"] == pytest.approx(120.0)


def _services(
    sizes: tuple[int, ...], per_block: int = 1, duration: int = 40, p: float = 0.6
) -> SchedulingInstance:
    """Un servicio por tamaño (componentes independientes): ``n`` sesiones y ``per_block·n``
    entradas, cada una de un paciente distinto."""
    entries: list[E] = []
    blocks: list[B] = []
    for svc, n in enumerate(sizes, start=1):
        entries += [
            E(f"s{svc}e{k}", "p3", date(2024, 1 + k % 12, 1 + k // 12), service=svc)
            for k in range(per_block * n)
        ]
        blocks += [
            B(f"s{svc}b{k}", utc(2025, 10, 7 + k), duration, CNE_SPEC, 20, service=svc)
            for k in range(n)
        ]
    return build_instance(entries, blocks, dict.fromkeys((e.entry_id for e in entries), p))


def test_leftover_flows_to_larger_components() -> None:
    """Los componentes chicos van primero; lo que no gastan pasa a los grandes (§8.5)."""
    cfg = SchedulerConfig(horizon_weeks=2, time_limit_s=10.0)
    out = run_optimized(_services((1, 3, 6)), cfg)
    subs = sorted(out.subs, key=lambda r: len(r.sub.pairs))
    assert [len(r.sub.pairs) for r in subs] == [1, 9, 36]
    det = cfg.solver.deterministic
    minimum = min(cfg.solver.min_component_budget, 0.2 * 7.5 / 3)
    assert all(r.budget >= minimum - 1e-12 for r in subs)
    # El último recibe todo el saldo de la primera pasada (7,5 = 0,75·10).
    assert subs[-1].budget == pytest.approx(7.5 - sum(r.spent(det) for r in subs[:-1]))
    assert subs[0].budget < subs[1].budget < subs[-1].budget


def test_phase_3a_budget_does_not_depend_on_overbooking() -> None:
    """El libro de las fases 1-3a no ve el gasto de 3b y 4: su presupuesto no depende de p."""

    def budgets_3a(plan: SchedulePlan) -> list[tuple[str, float]]:
        return [
            (s["label"], p["budget"])
            for s in plan.report["solver"]["subproblems"]
            for p in s["phases"]
            if p["name"] in ("1", "2", "3a")
        ]

    # Sesiones de 4 cupos (O_b = 1) y 6 entradas por sesión con p = 0,7: hay sobrecupo.
    inst = _services((2, 3, 4), per_block=6, duration=80, p=0.7)
    cfg = SchedulerConfig(horizon_weeks=2, time_limit_s=2.0)
    on = solve(inst, cfg)
    off = solve(inst, cfg.model_copy(update={"overbooking": OverbookingConfig(enabled=False)}))
    assert on.report["summary"]["overbooked_flags"] > 0
    assert budgets_3a(on) == budgets_3a(off)
    phases_3b = [p for s in on.report["solver"]["subproblems"] for p in s["phases"]]
    assert any(p["name"] == "3b" and p["deterministic_time"] > 0 for p in phases_3b)


def _frontier_instance(p: float = 0.1) -> SchedulingInstance:
    """e0-e8 del mismo paciente y un solo día: la frontera se expande (ver §8.2, señal b)."""
    entries = [
        E(f"e{k}", "p3", AS_OF.replace(year=2024, month=k + 1, day=1), patient_id=f"pat{max(k, 8)}")
        for k in range(12)
    ]
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20)]
    return build_instance(entries, blocks, dict.fromkeys((e.entry_id for e in entries), p))


# 2e-6: con un solo saldo, los 2,09e-6 que gasta la 3b harían omitir la expansión solo con
# sobrecupo; con dos libros la decisión es la misma con y sin sobrecupo.
@pytest.mark.parametrize("time_limit", [1e-9, 2e-6, 0.015, 0.03, 120.0])
def test_frontier_pass_does_not_depend_on_overbooking(time_limit: float) -> None:
    """Con la frontera expandida y presupuestos que atan, ni la decisión de omitir ni el
    presupuesto de las fases 1-3a de la segunda pasada cambian con el sobrecupo."""

    def base_view(plan: SchedulePlan) -> tuple[object, ...]:
        b = _budget(plan)
        phases = [
            (s["label"], p["name"], p["budget"], p["objective"])
            for s in plan.report["solver"]["subproblems"]
            for p in s["phases"]
            if p["name"] in ("1", "2", "3a")
        ]
        return (
            plan.report["frontier"],
            b["first_pass"]["phases_1_3a"],
            b["frontier"]["phases_1_3a"],
            b["frontier"]["components_skipped"],
            phases,
        )

    inst = _frontier_instance(p=0.8)
    cfg = SchedulerConfig(horizon_weeks=2, time_limit_s=time_limit)
    on = solve(inst, cfg)
    off = solve(inst, cfg.model_copy(update={"overbooking": OverbookingConfig(enabled=False)}))
    assert on.report["frontier"]["expanded"]
    assert base_view(on) == base_view(off)


def test_frontier_expansion_skipped_when_budget_is_spent() -> None:
    """Sin saldo tras la primera pasada, el componente conserva su solución y se avisa."""
    inst = _frontier_instance()
    cfg = SchedulerConfig(
        horizon_weeks=2, time_limit_s=1e-9, solver=SolverConfig(first_pass_share=1.0)
    )
    plan = solve(inst, cfg)
    check_plan(inst, cfg, plan)
    b = _budget(plan)
    assert b["frontier"]["components_skipped"] == 1 and b["exhausted"]
    assert plan.report["frontier"]["skipped_components"] == ["c0x[1:cne_medical:x]"]
    assert plan.report["frontier"]["still_reached"] == plan.report["frontier"]["reached"]
    warnings = " ".join(plan.report["warnings"])
    assert "frontier_expansion_skipped_budget" in warnings and "time_budget_exhausted" in warnings
    # Las entradas que solo entraban con el margen duplicado vuelven a ser no candidatas.
    status = dict(plan.explanations.select("entry_id", "status").iter_rows())
    assert status["e10"] == status["e11"] == "not_candidate"
    assert plan.report["summary"]["not_candidate"] == 2
    # Con presupuesto, la expansión corre y no omite nada.
    full = solve(inst, SchedulerConfig(horizon_weeks=2))
    assert _budget(full)["frontier"]["components_skipped"] == 0
    assert _budget(full)["frontier"]["allotted"] > 0.25 * 120.0


def test_tight_budget_ends_by_limit_and_warns() -> None:
    rng = random.Random(3)
    entries = [
        E(
            f"x{k}",
            rng.choice(["p2", "p3", "p4"]),
            AS_OF - timedelta(days=rng.randint(10, 900)),
            patient_id=f"q{rng.randint(0, 50)}",
        )
        for k in range(80)
    ]
    blocks = [
        B(f"S{k}", utc(2025, 10, 7 + k % 10), 240, CNE_SPEC, 20, resource_id=f"R{k % 4}")
        for k in range(12)
    ]
    inst = build_instance(entries, blocks, {e.entry_id: rng.uniform(0.1, 0.6) for e in entries})
    cfg = SchedulerConfig(horizon_weeks=2, time_limit_s=1e-6)
    plan = solve(inst, cfg)
    check_plan(inst, cfg, plan)
    b = _budget(plan)
    assert b["exhausted"] and b["phases_ended_by_limit"] >= 1
    assert b["overrun"] > 0.0  # cada fase recibe al menos 0,01 y CP-SAT revisa por lotes
    assert any(w.startswith("time_budget_exhausted") for w in plan.report["warnings"])
    assert _budget(solve(inst, cfg)) == b


def test_wall_clock_mode_is_marked_not_reproducible() -> None:
    cfg = SchedulerConfig(solver=SolverConfig(deterministic=False, num_workers=1))
    plan = solve(example_instance(), cfg)
    assert plan.report["reproducible"] is False
    assert _budget(plan)["unit"] == "seconds"


# ------------------------------------------------------------------ propiedad


@st.composite
def busy_instances(draw: st.DrawFn) -> SchedulingInstance:
    """1-4 pacientes, hasta 6 entradas, hasta 5 bloques en 3 días y días ocupados al azar."""
    days = [HORIZON_START + timedelta(days=d) for d in (1, 2, 3)]
    blocks: list[B] = []
    for k in range(draw(st.integers(1, 5))):
        day = draw(st.sampled_from(days))
        start = utc(day.year, day.month, day.day, 11 + k % 3)
        if draw(st.integers(0, 2)) > 0:
            dur = draw(st.sampled_from([40, 60]))
            blocks.append(B(f"S{k}", start, dur, CNE_SPEC, 20, resource_id=f"R{k}"))
        else:
            blocks.append(B(f"S{k}", start, 360, IQ_SPEC, None, resource_id=f"R{k}"))
    n_patients = draw(st.integers(1, 4))
    entries: list[E] = []
    for k in range(draw(st.integers(1, 6))):
        is_iq = draw(st.integers(0, 2)) == 0
        deadline = draw(
            st.sampled_from([None, None, AS_OF - timedelta(days=20), HORIZON_START + timedelta(2)])
        )
        entries.append(
            E(
                f"e{k}",
                draw(st.sampled_from(["p1", "p2", "p3", "p4"])),
                AS_OF - timedelta(days=draw(st.integers(30, 900))),
                deadline,
                patient_id=f"pat{draw(st.integers(0, n_patients - 1))}",
                specialty=IQ_SPEC if is_iq else CNE_SPEC,
                duration=draw(st.sampled_from([60, 120, 200])) if is_iq else 20,
                groups={"age_group": draw(st.sampled_from(["20_44", "65_plus"]))},
            )
        )
    pairs = [(f"pat{p}", d) for p in range(n_patients) for d in days]
    rate = draw(st.sampled_from([0, 4]))  # sin días ocupados, o cada día con probabilidad 1/4
    busy = [pair for pair in pairs if rate and draw(st.integers(1, rate)) == 1]
    probs = {e.entry_id: draw(st.floats(0.3, 0.9)) for e in entries}
    return build_instance(entries, blocks, probs, busy=busy)


def _no_wall(value: Any) -> Any:
    """El informe sin tiempos de reloj (lo único que puede cambiar entre corridas)."""
    if isinstance(value, dict):
        return {k: _no_wall(v) for k, v in value.items() if k != "wall_time_s"}
    if isinstance(value, list):
        return [_no_wall(v) for v in value]
    return value


PROPERTY_CFG = SchedulerConfig(
    horizon_weeks=1,
    overbooking=OverbookingConfig(alpha=0.5, max_fraction=0.5),
    time_limit_s=5.0,
)


@settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(busy_instances())
def test_busy_days_and_s3_property(inst: SchedulingInstance) -> None:
    """Ningún (paciente, día) repetido ni ocupado; agendados = S3; dos corridas, mismo plan."""
    local = {b.slot_id: b.local_date for b in inst.blocks}
    out = run_optimized(inst, PROPERTY_CFG)
    plans = {
        "optimized": _build(
            out.prep,
            out.solution,
            "optimized",
            out.subs,
            out.warnings,
            out.frontier,
            out.discarded,
            out.budget,
        ),
        "fifo": greedy_schedule(inst, PROPERTY_CFG, "fifo"),
        "priority": greedy_schedule(inst, PROPERTY_CFG, "priority"),
    }
    for plan in plans.values():
        check_plan(inst, PROPERTY_CFG, plan)
        days = [
            (r["patient_id"], local[r["slot_id"]]) for r in plan.assignments.iter_rows(named=True)
        ]
        assert len(days) == len(set(days))
        assert not set(days) & inst.busy_patient_days
    s3: set[int] = set()
    for r in out.subs:
        final = assigned_entries(out.prep, r.final)
        assert final == r.s3 and r.s0 <= r.s3
        if not r.ran_3b():
            assert r.s3 == r.s0
        s3 |= r.s3
    entry_ids = {out.prep.entry(i).entry_id for i in s3}
    assert set(plans["optimized"].assignments["entry_id"]) == entry_ids
    event(f"pares descartados por día ocupado={min(2, out.prep.pairs_dropped_busy)}")
    event(f"con 3b={any(r.ran_3b() for r in out.subs)}")
    again = solve(inst, PROPERTY_CFG)
    assert again.assignments.equals(plans["optimized"].assignments)
    assert again.ges.equals(plans["optimized"].ges)
    assert _no_wall(again.report) == _no_wall(plans["optimized"].report)
