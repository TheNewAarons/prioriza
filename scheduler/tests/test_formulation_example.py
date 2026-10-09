"""El ejemplo resuelto a mano de la formulación (§13) y sus dos variantes."""

from __future__ import annotations

from datetime import date

from scheduler.config import GroupLimitsConfig, OverbookingConfig, SolverConfig
from scheduler_test_support import example_instance, plan_map

from scheduler import SchedulerConfig, greedy_schedule, solve

CONFIG = SchedulerConfig(
    overbooking=OverbookingConfig(alpha=0.25, max_fraction=0.5),
    solver=SolverConfig(num_workers=1),
)


def _sub(plan_report: dict) -> dict:  # type: ignore[type-arg]
    subs = plan_report["solver"]["subproblems"]
    assert len(subs) == 1
    return subs[0]  # type: ignore[no-any-return]


def test_example_plan_and_objectives() -> None:
    plan = solve(example_instance(), CONFIG)
    assert plan_map(plan) == {"B1": {"A", "D"}, "B2": {"C", "E", "F"}}
    sub = _sub(plan.report)
    assert sub["f1"] == 1
    assert sub["f2"] == 0
    assert sub["z0"] == 16_216
    assert sub["z3"] == 16_787
    assert plan.objective_value == 16_787
    assert plan.solver_status == "OPTIMAL"
    phases = [p["name"] for p in sub["phases"]]
    assert phases == ["1", "2", "3a", "3b", "4"]
    assert sub["phases"][-1]["objective"] == 500  # BAL = 1500 - 1000


def test_example_coefficients() -> None:
    plan = solve(example_instance(), CONFIG)
    coef = dict(plan.assignments.select("entry_id", "coef").iter_rows())
    assert coef == {"A": 5_235, "D": 3_419, "C": 3_549, "E": 4_013, "F": 571}


def test_example_postprocess() -> None:
    plan = solve(example_instance(), CONFIG)
    rows = {r["entry_id"]: r for r in plan.assignments.iter_rows(named=True)}
    assert [e for e, r in rows.items() if r["is_overbooked"]] == ["F"]
    assert rows["F"]["phase_added"] == "3b"
    assert {rows[e]["phase_added"] for e in "ACDE"} == {"3a"}
    # B2 empieza 11:30 UTC (08:30 local): E en 0, C en 1 y F comparte la posición 1.
    assert rows["E"]["scheduled_start"].strftime("%H:%M") == "11:30"
    assert rows["C"]["scheduled_start"].strftime("%H:%M") == "11:50"
    assert rows["F"]["scheduled_start"].strftime("%H:%M") == "11:50"
    assert rows["A"]["scheduled_start"].strftime("%H:%M") == "11:30"
    assert rows["D"]["scheduled_start"].strftime("%H:%M") == "11:50"
    blocks = plan.report["overbooking"]["blocks"]
    assert len(blocks) == 1 and blocks[0]["slot_id"] == "B2"
    assert abs(blocks[0]["risk_exact"] - 0.2475) < 1e-12
    ges = {r["entry_id"]: r for r in plan.ges.iter_rows(named=True)}
    assert ges["D"]["met"] and ges["D"]["scheduled_date"] == date(2025, 10, 7)
    assert ges["E"]["met"] and ges["E"]["on_time"]


def test_example_variant_group_limit_blocks_overbooking() -> None:
    cfg = CONFIG.model_copy(
        update={
            "group_limits": GroupLimitsConfig(
                dimensions=("age_group",), mode="relative", max_gap_pp=10.0, min_group_n=1
            )
        }
    )
    plan = solve(example_instance(groups=True), cfg)
    assert plan_map(plan) == {"B1": {"A", "D"}, "B2": {"C", "E"}}
    sub = _sub(plan.report)
    assert sub["z3"] == 16_216
    passes = sub["fairness_passes"]
    assert len(passes) == 2
    first = {g["value"]: g["share"] for g in passes[0]["groups"]}
    assert abs(passes[0]["share_global"] - 0.6) < 1e-12
    assert first["65_plus"] == 1.0
    assert all(abs(c - 0.7) < 1e-12 for c in passes[1]["caps"].values())
    assert not plan.assignments["is_overbooked"].any()


def test_example_variant_infeasible_ges_is_reported() -> None:
    plan = solve(example_instance(e_deadline=date(2025, 10, 5)), CONFIG)
    assert plan_map(plan) == {"B1": {"D", "E"}, "B2": {"A", "C", "F"}}
    # El plazo nuevo sube el puntaje P4 de E (rampa GES 13,75): s_E = 4.571.
    assert plan.objective_value == 17_271
    coef = dict(plan.assignments.select("entry_id", "coef").iter_rows())
    assert coef["E"] == 4_563
    ges = {r["entry_id"]: r for r in plan.ges.iter_rows(named=True)}
    assert not ges["E"]["met"]
    assert ges["E"]["cause"] == "deadline_before_first_block"
    assert ges["E"]["days_late"] == 2
    assert "Plazo GES 2025-10-05" in ges["E"]["text"]
    assert "2025-10-07, 2 días fuera de plazo" in ges["E"]["text"]
    assert plan.report["ges"]["unmet_by_cause"] == {"deadline_before_first_block": 1}


def test_example_greedy_baseline_is_dominated() -> None:
    inst = example_instance()
    base = greedy_schedule(inst, CONFIG, "priority")
    assert plan_map(base) == {"B1": {"A", "D"}, "B2": {"E", "C"}}
    fifo = greedy_schedule(inst, CONFIG, "fifo")
    # Orden de llegada: C, D, F, A llenan los cupos y E (GES) queda fuera.
    assert plan_map(fifo) == {"B1": {"C", "D"}, "B2": {"F", "A"}}
    ges = {r["entry_id"]: r for r in fifo.ges.iter_rows(named=True)}
    assert not ges["E"]["met"]
    assert ges["E"]["cause"] == "capacity_taken"
    assert "1 p1 (cesión)" in ges["E"]["text"]
