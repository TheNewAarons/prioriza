"""Citas ya confirmadas en R4 (M-03) y fase 4 con agendados fijos (M-04).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import polars as pl
import pytest
from scheduler.adapters import busy_from_appointments
from scheduler.config import OverbookingConfig, SolverConfig
from scheduler.cpsat import assigned_entries
from scheduler.greedy import greedy_assign
from scheduler.phases import run_optimized
from scheduler.plan import _build
from scheduler.prepare import PATIENT_DAY_BUSY, prepare
from scheduler_test_support import (
    CNE_SPEC,
    HORIZON_START,
    IQ_SPEC,
    B,
    E,
    build_instance,
    utc,
)

from scheduler import SchedulerConfig, SchedulingInstance, greedy_schedule, solve

CFG = SchedulerConfig(horizon_weeks=2, solver=SolverConfig(num_workers=1))
TUE = date(2025, 10, 14)
THU = date(2025, 10, 16)


def _two_days() -> list[B]:
    return [
        B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20),
        B("S2", utc(2025, 10, 16), 80, CNE_SPEC, 20),
    ]


def _probs(entries: list[E]) -> dict[str, float]:
    return dict.fromkeys((e.entry_id for e in entries), 0.3)


# ------------------------------------------------------------------ instancia y adaptador


def _from_frames_with_busy(busy: pl.DataFrame) -> SchedulingInstance:
    """``from_frames`` de una instancia mínima válida con la tabla ``busy`` dada."""
    base = build_instance([E("e0", "p3", date(2024, 1, 1), patient_id="pa")], _two_days())
    return SchedulingInstance.from_frames(
        as_of=base.as_of,
        horizon_start=base.horizon_start,
        entries=pl.DataFrame([dataclasses.asdict(e) for e in base.entries]),
        blocks=pl.DataFrame([dataclasses.asdict(b) for b in base.blocks]),
        rules_digest=base.rules_digest,
        rules_version=base.rules_version,
        busy=busy,
    )


def test_from_frames_reads_busy_and_rejects_datetimes() -> None:
    inst = _from_frames_with_busy(pl.DataFrame({"patient_id": ["pa"], "local_date": [TUE]}))
    assert inst.busy_patient_days == frozenset({("pa", TUE)})
    with pytest.raises(ValueError, match="debe ser una fecha"):
        _from_frames_with_busy(
            pl.DataFrame({"patient_id": ["pa"], "local_date": [datetime(2025, 10, 14, tzinfo=UTC)]})
        )
    with pytest.raises(ValueError, match="faltan columnas en busy"):
        _from_frames_with_busy(pl.DataFrame({"patient_id": ["pa"]}))
    with pytest.raises(ValueError, match="busy_patient_days"):
        dataclasses.replace(inst, busy_patient_days=frozenset({("pa", "2025-10-14")}))


def test_busy_from_appointments_uses_local_date_and_filters() -> None:
    """Solo citas ``scheduled`` que no son historial, por fecha local, dentro del horizonte."""
    appt = pl.DataFrame(
        {
            "patient_id": ["p1", "p1", "p2", "p3", "p4", "p5"],
            "scheduled_start": [
                datetime(2025, 10, 14, 11, 30, tzinfo=UTC),
                datetime(2025, 10, 14, 15, 0, tzinfo=UTC),  # mismo día local: una sola fila
                datetime(2025, 10, 14, 2, 0, tzinfo=UTC),  # 23:00 del 13 en Santiago
                datetime(2025, 10, 14, 11, 30, tzinfo=UTC),
                datetime(2025, 10, 14, 11, 30, tzinfo=UTC),
                datetime(2025, 10, 25, 11, 30, tzinfo=UTC),  # fuera del horizonte
            ],
            "status": ["scheduled", "scheduled", "scheduled", "scheduled", "attended", "scheduled"],
            "origin": ["scheduler", "scheduler", "waitlist", "history", "scheduler", "scheduler"],
        }
    )
    busy = busy_from_appointments(appt, HORIZON_START, date(2025, 10, 20))
    assert busy.rows() == [("p1", TUE), ("p2", date(2025, 10, 13))]
    assert busy.schema == pl.Schema({"patient_id": pl.String, "local_date": pl.Date})


# ------------------------------------------------------------------ preparación y causas


def test_prepare_drops_busy_days_and_counts_pairs() -> None:
    entries = [E("e0", "p3", date(2024, 1, 1), patient_id="pa")]
    inst = build_instance(entries, _two_days(), _probs(entries), busy=[("pa", TUE)])
    prep = prepare(inst, CFG)
    assert [prep.block(prep.pair_block[p]).slot_id for p in prep.pairs_of_entry[0]] == ["S2"]
    assert prep.first_date[0] == THU
    assert prep.pairs_dropped_busy == 1
    plan = solve(inst, CFG)
    assert plan.assignments["slot_id"].to_list() == ["S2"]
    assert plan.report["summary"]["pairs_dropped_patient_day_busy"] == 1


def test_entry_with_every_day_busy_reports_cause() -> None:
    entries = [E("e0", "p3", date(2024, 1, 1), patient_id="pa"), E("e1", "p4", date(2024, 2, 1))]
    inst = build_instance(entries, _two_days(), _probs(entries), busy=[("pa", TUE), ("pa", THU)])
    prep = prepare(inst, CFG)
    assert prep.no_pair_reason[0] == PATIENT_DAY_BUSY
    plan = solve(inst, CFG)
    row = plan.explanations.filter(pl.col("entry_id") == "e0").row(0, named=True)
    assert row["status"] == "no_compatible_block" and row["detail"] == PATIENT_DAY_BUSY
    assert "cita confirmada" in row["text"]
    assert plan.assignments["entry_id"].to_list() == ["e1"]


def test_ges_losing_its_deadline_blocks_to_busy_days_is_presolved() -> None:
    """GES con plazo el 15: su único bloque a tiempo (14) está ocupado; queda el 16, tarde."""
    entries = [
        E("g", "p2", date(2025, 6, 1), date(2025, 10, 15), patient_id="pg"),
        E("o", "p3", date(2025, 1, 1), date(2025, 9, 1), patient_id="po"),  # vencida
    ]
    busy = [("pg", TUE), ("po", TUE), ("po", THU)]
    inst = build_instance(entries, _two_days(), _probs(entries), busy=busy)
    prep = prepare(inst, CFG)
    assert prep.ges_presolve == {0: PATIENT_DAY_BUSY, 1: PATIENT_DAY_BUSY}
    assert prep.first_date[0] == THU
    # El atraso se mide desde el primer bloque posible (§6.6): agendarla el 16 no castiga.
    assert prep.pair_delay_days[prep.pairs_of_entry[0][0]] == 0
    for plan in (solve(inst, CFG), greedy_schedule(inst, CFG)):
        ges = {r["entry_id"]: r for r in plan.ges.iter_rows(named=True)}
        assert ges["g"]["cause"] == PATIENT_DAY_BUSY and not ges["g"]["met"]
        assert ges["g"]["scheduled_date"] == THU
        assert ges["o"]["cause"] == PATIENT_DAY_BUSY and ges["o"]["scheduled_date"] is None
        assert "cita confirmada" in ges["g"]["text"]


def test_all_policies_avoid_busy_days() -> None:
    """Dos entradas del mismo paciente, cupo de sobra: ninguna cae en su día ocupado."""
    entries = [
        E("a", "p3", date(2024, 1, 1), patient_id="pa"),
        E("b", "p3", date(2024, 2, 1), patient_id="pa"),
        E("c", "p4", date(2024, 3, 1), patient_id="pc"),
    ]
    blocks = [*_two_days(), B("S3", utc(2025, 10, 17), 80, CNE_SPEC, 20)]
    inst = build_instance(entries, blocks, _probs(entries), busy=[("pa", TUE), ("pc", THU)])
    local = {b.slot_id: b.local_date for b in inst.blocks}
    for plan in (solve(inst, CFG), greedy_schedule(inst, CFG, "fifo"), greedy_schedule(inst, CFG)):
        days = [
            (r["patient_id"], local[r["slot_id"]]) for r in plan.assignments.iter_rows(named=True)
        ]
        assert len(days) == 3 and len(set(days)) == 3
        assert not set(days) & inst.busy_patient_days


def test_assembler_rejects_assignment_on_busy_day() -> None:
    """Una solución armada sin ver las citas previas no pasa la verificación R4."""
    entries = [E("e0", "p3", date(2024, 1, 1), patient_id="pa")]
    inst = build_instance(entries, _two_days(), _probs(entries))
    prep = prepare(inst, CFG)
    solution = greedy_assign(prep, prep.pairs_of_entry, "priority")
    assert prep.block(prep.pair_block[next(iter(solution))]).local_date == TUE
    prep.instance = dataclasses.replace(inst, busy_patient_days=frozenset({("pa", TUE)}))
    with pytest.raises(RuntimeError, match="cita confirmada"):
        _build(prep, solution, "priority", None, [], None)


# ------------------------------------------------------------------ M-04


def _packing_instance() -> SchedulingInstance:
    """Dos pabellones de 306 min planificables y cargas 100, 150, 200 y 150 (d + 30).

    La voraz pone 100 + 150 en X y 200 en Y; la cuarta no cabe. Reordenando (100 + 200 en X,
    150 + 150 en Y) caben las cuatro y la utilización queda pareja.
    """
    durations = [70, 120, 170, 120]
    entries = [
        E(f"a{k}", "p3", date(2024, k + 1, 1), specialty=IQ_SPEC, duration=d)
        for k, d in enumerate(durations)
    ]
    blocks = [
        B("X", utc(2025, 10, 14), 360, IQ_SPEC, None),
        B("Y", utc(2025, 10, 15), 360, IQ_SPEC, None),
    ]
    return build_instance(entries, blocks)


M04_CFG = SchedulerConfig(
    horizon_weeks=2,
    overbooking=OverbookingConfig(enabled=False),
    solver=SolverConfig(relative_gap_limit=1.0),
)


def test_phase4_cannot_add_patients_regression_m04() -> None:
    """Con brecha 1,0 la 3a se queda con la voraz; antes la fase 4 agregaba a ``a3`` como "3b".

    El equilibrio solo puede mover bloques: el plan final tiene exactamente S0 (sin 3b) y
    ninguna etiqueta "3b".
    """
    inst = _packing_instance()
    out = run_optimized(inst, M04_CFG)
    (r,) = out.subs
    assert r.phase("4") is not None and r.phase("3b") is None
    assert len(r.s0) == 3
    assert assigned_entries(out.prep, r.final) == r.s0 == r.s3
    plan = solve(inst, M04_CFG)
    assert set(plan.assignments["phase_added"]) == {"3a"}
    assert plan.report["summary"]["added_by_overbooking"] == 0
    assert plan.report["summary"]["scheduled"] == 3


def test_assembler_checks_s3_and_s0() -> None:
    """Soluciones manipuladas: agendados distintos de S3, o fuera de S0 sin fase 3b."""
    inst = _packing_instance()

    def rebuild() -> None:
        _build(out.prep, out.solution, "optimized", out.subs, [], out.frontier, out.discarded)

    out = run_optimized(inst, M04_CFG)
    (r,) = out.subs
    r.s3 = frozenset(sorted(r.s3)[1:])
    with pytest.raises(RuntimeError, match="conjunto de agendados"):
        rebuild()

    out = run_optimized(inst, M04_CFG)
    (r,) = out.subs
    r.s0 = frozenset(sorted(r.s0)[1:])
    with pytest.raises(RuntimeError, match="fuera de S0 sin fase 3b"):
        rebuild()
