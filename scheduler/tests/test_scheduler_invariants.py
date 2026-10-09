"""Invariantes del plan sobre instancias aleatorias pequeñas (hypothesis).

Las comprobaciones recalculan todo desde las tablas de entrada, sin usar el modelo: compatibilidad,
capacidad, una cita por entrada y por paciente y día, riesgo exacto del sobrecupo, el
sobrecupo solo agrega y el plan no es peor que la política voraz en orden lexicográfico.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from scheduler.config import GroupLimitsConfig, OverbookingConfig, SolverConfig
from scheduler.plan import SchedulePlan
from scheduler.risk import overflow_risk
from scheduler_test_support import (
    AS_OF,
    CNE_SPEC,
    HORIZON_START,
    IQ_SPEC,
    B,
    E,
    build_instance,
    utc,
)

from scheduler import SchedulerConfig, SchedulingInstance, greedy_schedule, solve

KNOWN_STATUSES = {
    "scheduled",
    "scheduled_overbooked",
    "no_compatible_block",
    "not_candidate",
    "capacity_taken",
    "patient_conflict",
    "not_selected",
}
KNOWN_CAUSES = {
    "no_block_in_horizon",
    "duration_exceeds_blocks",
    "deadline_before_first_block",
    "lead_time",
    "capacity_taken",
    "patient_conflict",
    "solver_limit",
    "decomposition",
    "overbooking_interaction",
}


@st.composite
def crowded(draw: st.DrawFn) -> tuple[SchedulingInstance, float]:
    """Una cola CNE con más demanda que cupos y p alta: ejercita el sobrecupo."""
    blocks = []
    for k in range(draw(st.integers(1, 3))):
        start = HORIZON_START + timedelta(days=draw(st.integers(1, 12)))
        dur = draw(st.sampled_from([40, 60, 80]))
        blocks.append(B(f"S{k}", utc(start.year, start.month, start.day), dur, CNE_SPEC, 20))
    entries: list[E] = []
    probs: dict[str, float] = {}
    n = draw(st.integers(4, 14))
    for k in range(n):
        deadline = AS_OF + timedelta(days=draw(st.integers(5, 30))) if draw(st.booleans()) else None
        entries.append(
            E(
                f"e{k}",
                draw(st.sampled_from(["p1", "p2", "p3", "p4"])),
                AS_OF - timedelta(days=draw(st.integers(30, 900))),
                deadline,
                patient_id=f"pat{draw(st.integers(0, n - 1))}",
                groups={"age_group": draw(st.sampled_from(["20_44", "65_plus"]))},
            )
        )
        probs[f"e{k}"] = draw(st.floats(0.25, 0.85))
    return build_instance(entries, blocks, probs), draw(st.sampled_from([0.2, 0.4, 0.6]))


@st.composite
def instances(draw: st.DrawFn) -> tuple[SchedulingInstance, float]:
    if draw(st.booleans()):
        return draw(crowded())
    n_blocks = draw(st.integers(1, 5))
    blocks: list[B] = []
    for k in range(n_blocks):
        day = draw(st.integers(0, 13))
        start = HORIZON_START + timedelta(days=day)
        is_or = draw(st.booleans())
        service = draw(st.integers(1, 2))
        if is_or:
            dur = draw(st.sampled_from([120, 240, 360]))
            blocks.append(
                B(f"S{k}", utc(start.year, start.month, start.day), dur, IQ_SPEC, None, service)
            )
        else:
            dur = draw(st.sampled_from([40, 60, 100]))
            blocks.append(
                B(f"S{k}", utc(start.year, start.month, start.day), dur, CNE_SPEC, 20, service)
            )
    n_entries = draw(st.integers(1, 10))
    n_patients = draw(st.integers(1, n_entries))
    entries: list[E] = []
    probs: dict[str, float] = {}
    for k in range(n_entries):
        is_iq = draw(st.booleans())
        deadline_kind = draw(st.sampled_from(["none", "none", "overdue", "soon", "later"]))
        deadline = {
            "none": None,
            "overdue": AS_OF - timedelta(days=draw(st.integers(1, 400))),
            "soon": AS_OF + timedelta(days=draw(st.integers(1, 20))),
            "later": AS_OF + timedelta(days=draw(st.integers(21, 120))),
        }[deadline_kind]
        entry_date = AS_OF - timedelta(days=draw(st.integers(1, 1500)))
        if deadline is not None and deadline < entry_date:
            deadline = entry_date
        entries.append(
            E(
                f"e{k}",
                draw(st.sampled_from(["p1", "p2", "p3", "p4"])),
                entry_date,
                deadline,
                patient_id=f"pat{draw(st.integers(0, n_patients - 1))}",
                specialty=IQ_SPEC if is_iq else CNE_SPEC,
                duration=draw(st.sampled_from([30, 60, 90, 150, 300])) if is_iq else 20,
                service=draw(st.integers(1, 2)),
                groups={"age_group": draw(st.sampled_from(["0_14", "45_64", "65_plus"]))},
            )
        )
        probs[f"e{k}"] = draw(st.floats(0.02, 0.8))
    alpha = draw(st.sampled_from([0.1, 0.3, 0.6]))
    return build_instance(entries, blocks, probs), alpha


def _config(alpha: float, **kw: object) -> SchedulerConfig:
    base = {
        "horizon_weeks": 2,
        "overbooking": OverbookingConfig(alpha=alpha, max_fraction=0.5),
        "group_limits": GroupLimitsConfig(dimensions=("age_group",), min_group_n=1),
        "time_limit_s": 5.0,
        "solver": SolverConfig(num_workers=1),
    }
    base.update(kw)
    return SchedulerConfig.model_validate(base)


def check_plan(inst: SchedulingInstance, cfg: SchedulerConfig, plan: SchedulePlan) -> None:
    """Invariantes recalculados desde la instancia."""
    entries = {e.entry_id: e for e in inst.entries}
    blocks = {b.slot_id: b for b in inst.blocks}
    horizon_end = inst.horizon_start + timedelta(days=7 * cfg.horizon_weeks)
    rows = list(plan.assignments.iter_rows(named=True))
    ids = [r["entry_id"] for r in rows]
    assert len(ids) == len(set(ids)), "una entrada aparece dos veces"
    patient_days = [(r["patient_id"], blocks[r["slot_id"]].local_date) for r in rows]
    assert len(patient_days) == len(set(patient_days)), "un paciente con dos citas el mismo día"
    by_block: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        e = entries[r["entry_id"]]
        b = blocks[r["slot_id"]]
        by_block[b.slot_id].append(r)
        assert b.specialty_code == e.specialty_code
        assert b.health_service_code == e.health_service_code
        assert inst.horizon_start <= b.local_date < horizon_end
        obligated = e.is_ges and e.ges_deadline is not None and e.ges_deadline < horizon_end
        lead = cfg.ges_min_lead_days if obligated else cfg.min_lead_days
        assert b.local_date >= inst.as_of + timedelta(days=lead)
        assert r["lead_days"] == (b.local_date - inst.as_of).days
        if not b.is_cne:
            assert e.duration_min + cfg.or_turnover_min <= math.floor(
                cfg.or_max_fill * b.duration_min
            )
    for slot, members in by_block.items():
        b = blocks[slot]
        if b.is_cne:
            assert b.unit_min is not None
            cap = b.duration_min // b.unit_min
            n = len(members)
            flags = sum(1 for m in members if m["is_overbooked"])
            assert flags == max(0, n - cap)
            if n > cap:
                assert plan.policy == "optimized" and cfg.overbooking.enabled
                assert n - cap <= math.floor(cfg.overbooking.max_fraction * cap)
                lo, hi = cfg.overbooking.p_clip_low, cfg.overbooking.p_clip_high
                probs = [min(hi, max(lo, inst.noshow[(str(m["entry_id"]), slot)])) for m in members]
                assert overflow_risk(probs, cap) <= cfg.overbooking.alpha + 1e-12
                assert all(m["phase_added"] == "3b" for m in members if m["is_overbooked"])
        else:
            used = sum(
                entries[str(m["entry_id"])].duration_min + cfg.or_turnover_min for m in members
            )
            assert used <= math.floor(cfg.or_max_fill * b.duration_min)
            assert not any(m["is_overbooked"] for m in members)
    assert plan.explanations.height == len(inst.entries)
    assert set(plan.explanations["status"].unique()) <= KNOWN_STATUSES
    unmet = plan.ges.filter(~plan.ges["met"])
    assert set(unmet["cause"].to_list()) <= KNOWN_CAUSES
    assert unmet["text"].str.contains("No se cumple").all()


def _lex(plan: SchedulePlan, inst: SchedulingInstance) -> tuple[int, int, int]:
    """(p1 agendados, GES cumplidas, suma de coeficientes): orden de la verificación §9.5."""
    q1 = set(inst.yield_priorities)
    rows = plan.assignments
    prio = {e.entry_id: e.clinical_priority for e in inst.entries}
    n_q1 = sum(1 for e in rows["entry_id"] if prio[e] in q1)
    return (n_q1, int(plan.ges["met"].sum()), int(rows["coef"].sum()))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances())
def test_plan_invariants(data: tuple[SchedulingInstance, float]) -> None:
    inst, alpha = data
    cfg = _config(alpha)
    plan = solve(inst, cfg)
    check_plan(inst, cfg, plan)
    event(f"sobrecupos={min(2, int(plan.assignments['is_overbooked'].sum()))}")
    event(f"GES incumplidas={min(2, int((~plan.ges['met']).sum()))}")
    for order in ("priority", "fifo"):
        check_plan(inst, cfg, greedy_schedule(inst, cfg, order))  # type: ignore[arg-type]
    base = greedy_schedule(inst, cfg, "priority")
    if plan.solver_status == "OPTIMAL" and plan.report["summary"]["not_candidate"] == 0:
        assert _lex(plan, inst) >= _lex(base, inst)
        # §15.2: con Q1 no vacío, ningún p1 queda fuera si cabe sin sobrecupo.
        q1 = {e.entry_id for e in inst.entries if e.clinical_priority in inst.yield_priorities}
        statuses = dict(plan.explanations.select("entry_id", "status").iter_rows())
        for entry_id in q1:
            assert statuses[entry_id] != "not_selected", entry_id


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances())
def test_overbooking_disabled_never_exceeds_capacity(
    data: tuple[SchedulingInstance, float],
) -> None:
    inst, alpha = data
    cfg = _config(alpha, overbooking=OverbookingConfig(enabled=False))
    plan = solve(inst, cfg)
    check_plan(inst, cfg, plan)
    assert not plan.assignments["is_overbooked"].any()
    assert (plan.assignments["phase_added"] == "3a").all()
    assert all(p["name"] != "3b" for s in plan.report["solver"]["subproblems"] for p in s["phases"])


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances())
def test_phases_up_to_3a_do_not_depend_on_noshow(data: tuple[SchedulingInstance, float]) -> None:
    """§15.4: con y sin sobrecupo, y con otras p, las fases 1-3a dan lo mismo."""
    inst, alpha = data
    with_ob = solve(inst, _config(alpha))
    off = OverbookingConfig(enabled=False, alpha=alpha, max_fraction=0.5)
    without = solve(inst, _config(alpha, overbooking=off))
    shifted = SchedulingInstance(
        as_of=inst.as_of,
        horizon_start=inst.horizon_start,
        entries=inst.entries,
        blocks=inst.blocks,
        noshow={k: min(0.9, v + 0.05) for k, v in inst.noshow.items()},
        groups=inst.groups,
        rules_digest=inst.rules_digest,
        rules_version=inst.rules_version,
        yield_priorities=inst.yield_priorities,
        seed=inst.seed,
    )
    other_p = solve(shifted, _config(alpha))

    def s0(plan: SchedulePlan) -> set[tuple[str, str]]:
        rows = plan.assignments.filter(plan.assignments["phase_added"] == "3a")
        return set(rows.select("entry_id", "slot_id").iter_rows())

    def fixed(plan: SchedulePlan) -> list[tuple[object, object, object]]:
        return [(s["f1"], s["f2"], s["z0"]) for s in plan.report["solver"]["subproblems"]]

    assert fixed(with_ob) == fixed(without) == fixed(other_p)
    # Las entradas de S0 son las mismas; la fase 3b solo puede moverlas de bloque.
    assert {e for e, _ in s0(with_ob)} == {e for e, _ in s0(without)} == {e for e, _ in s0(other_p)}


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances())
def test_deterministic(data: tuple[SchedulingInstance, float]) -> None:
    inst, alpha = data
    cfg = _config(alpha)
    a = solve(inst, cfg)
    b = solve(inst, cfg)
    assert a.assignments.equals(b.assignments)
    assert a.ges.equals(b.ges)


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(instances(), st.sampled_from([0.0, 0.2, 0.5]))
def test_absolute_group_limits(data: tuple[SchedulingInstance, float], cap: float) -> None:
    inst, alpha = data
    cfg = _config(
        alpha,
        group_limits=GroupLimitsConfig(
            dimensions=("age_group",), mode="absolute", max_share=cap, min_group_n=1
        ),
    )
    plan = solve(inst, cfg)
    check_plan(inst, cfg, plan)
    # Con un solo componente por servicio, el tope por subproblema implica el tope por servicio.
    blocks = {b.slot_id: b for b in inst.blocks}
    overbooked = {b["slot_id"] for b in plan.report["overbooking"]["blocks"]}
    groups = {pid: g.get("age_group") for pid, g in inst.groups.items()}
    per: dict[tuple[int, str | None], list[bool]] = defaultdict(list)
    for r in plan.assignments.iter_rows(named=True):
        b = blocks[r["slot_id"]]
        if b.is_cne:
            per[(b.health_service_code, groups.get(r["patient_id"]))].append(
                r["slot_id"] in overbooked
            )
    for flags in per.values():
        assert sum(flags) <= cap * len(flags) + 1e-9
