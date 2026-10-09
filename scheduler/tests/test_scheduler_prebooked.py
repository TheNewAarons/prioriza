"""Bloques con citas previas y políticas de referencia sin p (revisión de P8).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

from datetime import date

from scheduler.config import SolverConfig
from scheduler.prepare import prepare
from scheduler_test_support import AS_OF, CNE_SPEC, IQ_SPEC, B, E, build_instance, utc

from scheduler import SchedulerConfig, greedy_schedule, solve

CFG = SchedulerConfig(horizon_weeks=2, solver=SolverConfig(num_workers=1))


def _entries(n: int) -> list[E]:
    return [E(f"e{k}", "p3", AS_OF.replace(year=2024, month=k + 1, day=1)) for k in range(n)]


def test_prebooked_units_reduce_capacity_and_shift_sequence() -> None:
    """Sesión de 4 cupos con 2 tomados: se agendan 2 y empiezan en la tercera posición."""
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20, prebooked=2)]
    inst = build_instance(_entries(5), blocks, dict.fromkeys((f"e{k}" for k in range(5)), 0.9))
    plan = solve(inst, CFG)
    rows = plan.assignments.sort("scheduled_start")
    assert rows.height == 2
    assert not rows["is_overbooked"].any()  # con citas previas no se sobreagenda
    starts = rows["scheduled_start"].to_list()
    assert starts[0] == utc(2025, 10, 14, 12, 10)  # 11:30 + 2 cupos de 20 min


def test_frozen_overbooked_session_has_zero_residual() -> None:
    """Una sesión congelada con sobrecupo (más citas que cupos) no rompe ``prepare``."""
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20, prebooked=5)]
    inst = build_instance(_entries(3), blocks, dict.fromkeys((f"e{k}" for k in range(3)), 0.9))
    prep = prepare(inst, CFG)
    assert prep.capacity[0] == 0 and prep.overbook_max[0] == 0
    assert solve(inst, CFG).assignments.height == 0


def test_prebooked_minutes_in_operating_room() -> None:
    """Pabellón de 360 min (306 planificables) con 200 tomados: cabe una cirugía de 60."""
    entries = [
        E(f"s{k}", "p3", date(2024, k + 1, 1), specialty=IQ_SPEC, duration=60) for k in range(3)
    ]
    blocks = [B("OR1", utc(2025, 10, 14), 360, IQ_SPEC, None, prebooked=200)]
    plan = solve(build_instance(entries, blocks), CFG)
    assert plan.assignments.height == 1
    assert plan.assignments["scheduled_start"][0] == utc(2025, 10, 14, 14, 50)  # 11:30 + 200 min


def test_greedy_policies_do_not_need_noshow() -> None:
    """``fifo`` y ``priority`` no sobreagendan: corren sin tabla de p con la config por defecto."""
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20)]
    inst = build_instance(_entries(6), blocks)
    for order in ("fifo", "priority"):
        plan = greedy_schedule(inst, CFG, order)  # type: ignore[arg-type]
        assert plan.assignments.height == 4
        assert not plan.assignments["is_overbooked"].any()
        assert plan.report["review_status"] == "pending"
