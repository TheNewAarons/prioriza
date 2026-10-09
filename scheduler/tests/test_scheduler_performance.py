"""Técnicas de rendimiento del programador (formulación §8.6) y benchmark.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Las técnicas (poda de niveles de sobrecupo, cota del objetivo con la pista, pistas voraces,
simetrías y arranque en caliente de la frontera) no pueden cambiar el valor óptimo de ninguna
fase: con brecha 0 y sin límites de equidad relativos (cuyos topes dependen de la primera
pasada de 3b), el plan con todas las técnicas y sin ninguna tiene los mismos valores por fase
y subproblema.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from ortools.sat.python import cp_model
from scheduler.bench import VARIANTS, compare, plan_metrics
from scheduler.config import GroupLimitsConfig, SolverConfig
from scheduler.cpsat import (
    Fixings,
    PhaseSpec,
    Sub,
    SubContext,
    SubModel,
    assigned_entries,
    canonicalize,
    overbook_levels,
    overbooking_fill,
)
from scheduler.greedy import greedy_assign
from scheduler.prepare import prepare, select_candidates
from scheduler.risk import overflow_risk
from scheduler_test_support import AS_OF, CNE_SPEC, B, E, build_instance, example_instance, utc
from test_scheduler_invariants import _config, check_plan, crowded, instances

from scheduler import SchedulerConfig, SchedulingInstance, greedy_schedule, solve

EXACT = {"relative_gap_limit": 0.0, "num_workers": 1}


def _per_sub(plan: object) -> list[tuple[object, ...]]:
    """(etiqueta, F1, F2, Z0, Z3, objetivo de la fase 4) por subproblema."""
    subs = plan.report["solver"]["subproblems"]  # type: ignore[attr-defined]
    out = []
    for s in subs:
        phase4 = [p["objective"] for p in s["phases"] if p["name"] == "4"]
        out.append((s["label"], s["f1"], s["f2"], s["z0"], s["z3"], phase4[-1:]))
    return sorted(out)


def _all_optimal(*plans: object) -> bool:
    return all(
        p["status"] == "OPTIMAL"
        for plan in plans
        for sp in plan.report["solver"]["subproblems"]  # type: ignore[attr-defined]
        for p in sp["phases"]
    )


GROUP_MODES = {
    "disabled": GroupLimitsConfig(enabled=False),
    "absolute": GroupLimitsConfig(
        dimensions=("age_group",), mode="absolute", max_share=0.3, min_group_n=1
    ),
}


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances(), st.sampled_from(sorted(GROUP_MODES)))
def test_techniques_do_not_change_optimum(
    data: tuple[SchedulingInstance, float], mode: str
) -> None:
    inst, alpha = data
    groups = GROUP_MODES[mode]
    on = _config(alpha, group_limits=groups, solver=SolverConfig(**EXACT))
    off = _config(alpha, group_limits=groups, solver=SolverConfig(**EXACT, **VARIANTS["none"]))
    plan_on, plan_off = solve(inst, on), solve(inst, off)
    check_plan(inst, on, plan_on)
    check_plan(inst, off, plan_off)
    if _all_optimal(plan_on, plan_off):
        event("compared")
        assert _per_sub(plan_on) == _per_sub(plan_off)
    else:
        event("not all optimal")


def test_techniques_compare_on_fixed_instance() -> None:
    """La comparación de arriba ocurre al menos en una instancia con sobrecupo y GES."""
    inst = example_instance()
    on = _config(0.5, group_limits=GROUP_MODES["disabled"], solver=SolverConfig(**EXACT))
    off = on.model_copy(update={"solver": SolverConfig(**EXACT, **VARIANTS["none"])})
    plan_on, plan_off = solve(inst, on), solve(inst, off)
    assert _all_optimal(plan_on, plan_off)
    assert _per_sub(plan_on) == _per_sub(plan_off)


def test_warm_start_on_frontier_expansion() -> None:
    """Margen chico: la frontera se expande, se informa la pasada descartada; mismo óptimo."""
    # e0-e8 son del mismo paciente: con un solo día, R4 deja agendar a uno y sobra capacidad
    # que las descartadas e10 y e11 podrían usar (señal b de la frontera, §8.2; K_q = 5, m = 2).
    entries = [
        E(f"e{k}", "p3", AS_OF.replace(year=2024, month=k + 1, day=1), patient_id=f"pat{max(k, 8)}")
        for k in range(12)
    ]
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20)]
    inst = build_instance(entries, blocks, dict.fromkeys((e.entry_id for e in entries), 0.1))
    plans = []
    for warm in (True, False):
        cfg = SchedulerConfig(
            horizon_weeks=2,
            solver=SolverConfig(**EXACT, warm_start_frontier=warm),
        )
        plan = solve(inst, cfg)
        assert plan.report["frontier"]["expanded"]
        assert plan.report["solver"]["time"]["discarded_first_pass"]["subproblems"] == 1
        plans.append(plan)
    assert _all_optimal(*plans)
    assert [r[1:] for r in _per_sub(plans[0])] == [r[1:] for r in _per_sub(plans[1])]


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(crowded())
def test_overbooking_fill_is_feasible_for_phase_3b(data: tuple[SchedulingInstance, float]) -> None:
    inst, alpha = data
    cfg = _config(alpha, group_limits=GroupLimitsConfig(dimensions=("age_group",), min_group_n=1))
    prep = prepare(inst, cfg)
    select_candidates(prep, cfg.candidate_margin)
    sub = Sub.build(prep, "t", sorted(prep.candidates))
    ctx = SubContext.build(prep, sub)
    base = canonicalize(ctx, greedy_assign(prep, sub.entries, "priority", set(sub.pairs)), False)
    s0 = frozenset(assigned_entries(prep, base))
    for caps in (None, {("age_group", "65_plus"): 0.3, ("age_group", "20_44"): 0.3}):
        filled = canonicalize(ctx, overbooking_fill(ctx, base, caps), True)
        assert s0 <= assigned_entries(prep, filled)
        # R1, R4 y riesgo exacto de cada bloque con sobrecupo.
        entries = [prep.pair_entry[p] for p in filled]
        assert len(entries) == len(set(entries))
        days = [
            (prep.entry(prep.pair_entry[p]).patient_id, prep.block(prep.pair_block[p]).local_date)
            for p in filled
        ]
        assert len(days) == len(set(days))
        members: dict[int, list[int]] = defaultdict(list)
        for p in filled:
            members[prep.pair_block[p]].append(p)
        for b, o in overbook_levels(prep, filled).items():
            assert o <= prep.overbook_max[b]
            probs = [prep.pair_p[p] or 0.0 for p in members[b]]
            assert overflow_risk(probs, prep.capacity[b]) <= alpha + 1e-12
        # El modelo de la fase 3b acepta la pista tal cual (R7-R15 lineales).
        sm = SubModel(ctx, PhaseSpec("3b", "score", True, Fixings(s0=s0), caps))
        for p, var in sm.x.items():
            sm.model.add(var == int(p in filled))
        status = cp_model.CpSolver().solve(sm.model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_level_pruning_drops_unreachable_levels() -> None:
    """Con p baja ningún conjunto cumple R10: el bloque no es elegible; con p alta sí."""
    entries = [E(f"e{k}", "p4", AS_OF.replace(year=2024)) for k in range(6)]
    blocks = [B("S1", utc(2025, 10, 14), 80, CNE_SPEC, 20)]  # C_b = 4, O_b = 1
    for p, expected in ((0.05, False), (0.8, True)):
        inst = build_instance(entries, blocks, dict.fromkeys((e.entry_id for e in entries), p))
        for prune in (True, False):
            cfg = SchedulerConfig(
                horizon_weeks=2, solver=SolverConfig(prune_overbooking_levels=prune)
            )
            prep = prepare(inst, cfg)
            ctx = SubContext.build(prep, Sub.build(prep, "t", sorted(prep.pairs_of_entry)))
            # Sin poda el nivel 1 siempre se crea (comportamiento anterior a §8.6).
            assert prep.overbook_max[0] == 1
            assert (0 in ctx.levels) == (expected or not prune)


def test_report_includes_solver_time_and_techniques() -> None:
    entries = [E(f"e{k}", "p3", AS_OF.replace(year=2024)) for k in range(6)]
    blocks = [B("S1", utc(2025, 10, 14), 40, CNE_SPEC, 20)]
    inst = build_instance(entries, blocks, dict.fromkeys((e.entry_id for e in entries), 0.6))
    plan = solve(inst, SchedulerConfig(horizon_weeks=2))
    solver = plan.report["solver"]
    assert set(solver["time"]) == {"plan", "discarded_first_pass"}
    tech = solver["subproblems"][0]["techniques"]
    assert tech["overbooking_levels_kept"] <= tech["overbooking_levels_nominal"]
    greedy = plan_metrics(greedy_schedule(inst, SchedulerConfig(horizon_weeks=2)))
    cmp_ = compare(plan_metrics(plan), greedy)
    assert cmp_["optimized_not_worse_lexicographic"]
    assert cmp_["delta"]["scheduled"] == plan.report["summary"]["scheduled"] - greedy["scheduled"]


def test_bench_cli_small(tmp_path: Path) -> None:
    """El benchmark escribe el informe con una celda chica (sin ablación)."""
    import json

    from scheduler.bench import app
    from typer.testing import CliRunner

    out = tmp_path / "bench.json"
    result = CliRunner().invoke(
        app,
        [
            "--sizes",
            "1000",
            "--weeks",
            "2",
            "--no-ablation",
            "--repeats",
            "1",
            "--time-limit",
            "2",
            "--work-dir",
            str(tmp_path / "bench"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    cell = payload["cells"][0]
    assert payload["disclaimer"].startswith("Herramienta de investigación")
    assert cell["size"] == 1000 and cell["horizon_weeks"] == 2
    assert set(cell["optimized"]) == {"all"}
    assert cell["problem"]["pairs_compatible"] <= cell["problem"]["pairs_same_queue"]
    assert cell["problem"]["pairs_same_queue"] <= cell["problem"]["pairs_all"]
    assert cell["optimized_vs_priority"]["optimized_not_worse_lexicographic"]
