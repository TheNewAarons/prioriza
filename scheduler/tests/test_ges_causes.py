"""Casos infactibles: cada causa de GES incumplida (§7) y los errores de datos se informan."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest
from scheduler.config import OverbookingConfig, SolverConfig
from scheduler.plan import SchedulePlan
from scheduler_test_support import AS_OF, IQ_SPEC, B, E, build_instance, utc

from scheduler import SchedulerConfig, SchedulingInstance, solve

CFG = SchedulerConfig(
    horizon_weeks=2,
    overbooking=OverbookingConfig(enabled=False),
    solver=SolverConfig(num_workers=1),
)


def _ges(plan: SchedulePlan, entry_id: str) -> dict[str, object]:
    rows = [r for r in plan.ges.iter_rows(named=True) if r["entry_id"] == entry_id]
    assert len(rows) == 1
    return rows[0]


def _explanation(plan: SchedulePlan, entry_id: str) -> dict[str, object]:
    rows = [r for r in plan.explanations.iter_rows(named=True) if r["entry_id"] == entry_id]
    assert len(rows) == 1
    return rows[0]


def test_no_block_in_horizon() -> None:
    inst = build_instance(
        [E("g", "p2", date(2025, 6, 1), date(2025, 10, 10), specialty="cne_medical:sin_oferta")],
        [B("S1", utc(2025, 10, 8))],
    )
    plan = solve(inst, CFG)
    row = _ges(plan, "g")
    assert row["met"] is False
    assert row["cause"] == "no_block_in_horizon"
    assert "no hay ningún bloque de su especialidad" in str(row["text"])
    assert "Queda sin agendar" in str(row["text"])
    assert _explanation(plan, "g")["status"] == "no_compatible_block"


def test_duration_exceeds_blocks() -> None:
    inst = build_instance(
        [E("g", "p2", date(2025, 6, 1), date(2025, 10, 10), specialty=IQ_SPEC, duration=300)],
        [B("OR1", utc(2025, 10, 8), 360, IQ_SPEC, None)],  # 0,85·360 = 306 < 300 + 30
    )
    plan = solve(inst, CFG)
    assert _ges(plan, "g")["cause"] == "duration_exceeds_blocks"
    assert _explanation(plan, "g")["detail"] == "duration_exceeds_blocks"


def test_deadline_before_first_block() -> None:
    inst = build_instance(
        [E("g", "p2", date(2025, 6, 1), date(2025, 10, 8))],
        [B("S1", utc(2025, 10, 9))],
    )
    plan = solve(inst, CFG)
    row = _ges(plan, "g")
    assert row["cause"] == "deadline_before_first_block"
    assert row["scheduled_date"] == date(2025, 10, 9)
    assert row["days_late"] == 1
    assert "1 día fuera de plazo" in str(row["text"])


def test_lead_time() -> None:
    # Con as_of 2025-10-05 y aviso GES de 2 días, el bloque del 2025-10-06 no sirve.
    as_of = date(2025, 10, 5)
    inst = build_instance(
        [E("g", "p2", date(2025, 6, 1), date(2025, 10, 6))],
        [B("S1", utc(2025, 10, 6)), B("S2", utc(2025, 10, 9))],
        as_of=as_of,
    )
    plan = solve(inst, CFG)
    row = _ges(plan, "g")
    assert row["cause"] == "lead_time"
    assert row["scheduled_date"] == date(2025, 10, 9)


def test_capacity_taken_reports_occupants() -> None:
    # Un solo cupo antes del plazo y dos GES con el mismo plazo: una queda fuera.
    deadline = date(2025, 10, 10)
    inst = build_instance(
        [
            E("g1", "p2", date(2025, 1, 1), deadline),
            E("g2", "p2", date(2025, 6, 1), deadline),
        ],
        [B("S1", utc(2025, 10, 8), duration=20)],
    )
    plan = solve(inst, CFG)
    rows = {e: _ges(plan, e) for e in ("g1", "g2")}
    unmet = [e for e, r in rows.items() if not r["met"]]
    assert unmet == ["g2"]  # g1 tiene más espera: mayor puntaje
    assert rows["g2"]["cause"] == "capacity_taken"
    assert "1 GES con plazo anterior o igual" in str(rows["g2"]["text"])
    assert plan.report["ges"]["unmet_by_cause"] == {"capacity_taken": 1}
    assert _explanation(plan, "g2")["status"] == "capacity_taken"


def test_patient_conflict() -> None:
    # Mismo paciente, dos GES de especialidades distintas con bloques el mismo único día.
    deadline = date(2025, 10, 10)
    other = "cne_medical:z"
    inst = build_instance(
        [
            E("g1", "p2", date(2025, 1, 1), deadline, patient_id="P"),
            E("g2", "p3", date(2025, 6, 1), deadline, patient_id="P", specialty=other),
        ],
        [B("S1", utc(2025, 10, 8)), B("S2", utc(2025, 10, 8, 17), specialty=other)],
    )
    plan = solve(inst, CFG)
    rows = {e: _ges(plan, e) for e in ("g1", "g2")}
    assert sum(1 for r in rows.values() if not r["met"]) == 1
    cause = next(r["cause"] for r in rows.values() if not r["met"])
    assert cause == "patient_conflict"
    assert plan.assignments.height == 1


def test_p1_yield_beats_ges() -> None:
    # Cesión a p1 (§8.1, fase 1): el p1 sin GES toma el único cupo y la GES p3 se informa.
    inst = build_instance(
        [E("p1", "p1", date(2025, 9, 1)), E("g", "p3", date(2025, 6, 1), date(2025, 10, 10))],
        [B("S1", utc(2025, 10, 8), duration=20)],
    )
    plan = solve(inst, CFG)
    assert plan.assignments["entry_id"].to_list() == ["p1"]
    row = _ges(plan, "g")
    assert row["cause"] == "capacity_taken"
    assert "1 p1 (cesión)" in str(row["text"])


def test_corrupt_block_kind_is_an_error() -> None:
    inst = build_instance([E("a", "p2", date(2025, 6, 1))], [B("S1", utc(2025, 10, 8))])
    bad = replace(inst.blocks[0], resource_kind="operating_room", unit_min=None)
    corrupt = SchedulingInstance(
        as_of=inst.as_of,
        horizon_start=inst.horizon_start,
        entries=inst.entries,
        blocks=(bad,),
        noshow={},
        groups={},
        rules_digest=inst.rules_digest,
        rules_version=inst.rules_version,
    )
    with pytest.raises(ValueError, match="dato corrupto"):
        solve(corrupt, CFG)


def test_missing_noshow_probability_is_an_error() -> None:
    inst = build_instance([E("a", "p2", date(2025, 6, 1))], [B("S1", utc(2025, 10, 8))])
    with pytest.raises(ValueError, match="falta p de inasistencia"):
        solve(inst, SchedulerConfig(horizon_weeks=2))


def test_negative_residual_capacity_is_an_error() -> None:
    """En pabellón no hay sobrecupo: más minutos tomados que planificables es un dato corrupto.

    En CNE una sesión congelada con sobrecupo sí puede pasarse (residual 0, ver
    ``test_scheduler_prebooked.py``).
    """
    entry = E("a", "p2", date(2025, 6, 1), specialty=IQ_SPEC, duration=60)
    inst = build_instance([entry], [B("OR1", utc(2025, 10, 8), 360, IQ_SPEC, None)])
    over = replace(inst.blocks[0], prebooked_min=400)
    bad = SchedulingInstance(
        as_of=inst.as_of,
        horizon_start=inst.horizon_start,
        entries=inst.entries,
        blocks=(over,),
        noshow={},
        groups={},
        rules_digest=inst.rules_digest,
        rules_version=inst.rules_version,
    )
    with pytest.raises(ValueError, match="capacidad residual negativa"):
        solve(bad, CFG)


def test_overdue_ges_met_by_scheduling_and_late_days_reported() -> None:
    inst = build_instance(
        [E("g", "p3", date(2025, 1, 1), AS_OF - timedelta(days=30))],
        [B("S1", utc(2025, 10, 8))],
    )
    plan = solve(inst, CFG)
    row = _ges(plan, "g")
    assert row["obligation"] == "overdue"
    assert row["met"] is True and row["on_time"] is False
    assert row["days_late"] == (date(2025, 10, 8) - (AS_OF - timedelta(days=30))).days
    assert "vencido antes del horizonte" in str(row["text"])


def _forced_plan(phase2_status: str, decomposition: str = "component", with_3b: bool = False):
    """Plan armado a mano: una GES con cupo libre queda sin agendar (para las causas finales)."""
    from scheduler.cpsat import PhaseOutcome, Sub, SubContext
    from scheduler.phases import SubResult
    from scheduler.plan import _build
    from scheduler.prepare import prepare, select_candidates

    inst = build_instance(
        [E("g", "p2", date(2025, 6, 1), date(2025, 10, 10))], [B("S1", utc(2025, 10, 8))]
    )
    prep = prepare(inst, CFG)
    select_candidates(prep, CFG.candidate_margin)
    sub = Sub.build(prep, "forzado", [0], decomposition=decomposition)
    ctx = SubContext.build(prep, sub)

    def outcome(name: str, status: str) -> PhaseOutcome:
        return PhaseOutcome(name, status, 0.0, None, None, 0.0, 0.0, 1.0, 0, 0, frozenset(), "x")

    phases = [outcome("2", phase2_status)] + ([outcome("3b", "OPTIMAL")] if with_3b else [])
    result = SubResult(sub=sub, ctx=ctx, budget=1.0, greedy=frozenset(), phases=phases)
    return lambda: _build(prep, frozenset(), "optimized", [result], [], None)


def test_solver_limit_decomposition_and_overbooking_interaction_causes() -> None:
    plan = _forced_plan("FEASIBLE")()
    assert _ges(plan, "g")["cause"] == "solver_limit"
    plan = _forced_plan("OPTIMAL", decomposition="by_week")()
    assert _ges(plan, "g")["cause"] == "decomposition"
    plan = _forced_plan("OPTIMAL", with_3b=True)()
    assert _ges(plan, "g")["cause"] == "overbooking_interaction"


def test_unexplained_unmet_ges_raises() -> None:
    with pytest.raises(RuntimeError, match="error de implementación"):
        _forced_plan("OPTIMAL")()
