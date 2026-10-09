"""Orquestación: filtro, descomposición, fases lexicográficas y frontera (formulación §8).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from scheduler.config import SchedulerConfig
from scheduler.cpsat import (
    UTIL_SCALE,
    Fixings,
    GroupKey,
    PhaseOutcome,
    PhaseSpec,
    Sub,
    SubContext,
    assigned_entries,
    block_loads,
    canonicalize,
    coef_sum,
    objective_value,
    overbook_levels,
    satisfies,
    solve_phase,
    unmet_ges,
)
from scheduler.greedy import greedy_assign
from scheduler.instance import SchedulingInstance
from scheduler.prepare import (
    Prepared,
    QueueKey,
    components,
    prepare,
    round_half_up,
    select_candidates,
)

PHASE_SHARES = {"1": 0.10, "2": 0.10, "3a": 0.325, "3b": 0.325, "4": 0.15}
STATUS_RANK = {"OPTIMAL": 0, "FEASIBLE": 1, "UNKNOWN": 2}


@dataclass
class SubResult:
    """Resultado de un subproblema: fases, soluciones y valores fijados."""

    sub: Sub
    ctx: SubContext
    budget: float
    greedy: frozenset[int]
    phases: list[PhaseOutcome] = field(default_factory=list)
    fairness_passes: list[dict[str, Any]] = field(default_factory=list)
    final: frozenset[int] = frozenset()
    s0: frozenset[int] = frozenset()
    f1: int | None = None
    f2: int | None = None
    z0: int = 0
    z3: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def added(self) -> set[int]:
        """Entradas agregadas por el sobreagendamiento (fase 3b): agendadas fuera de ``S0``."""
        return assigned_entries(self.ctx.prep, self.final) - self.s0

    def phase(self, name: str) -> PhaseOutcome | None:
        """Última fase con ese nombre (en 3b, la pasada que quedó)."""
        found = [p for p in self.phases if p.name == name]
        return found[-1] if found else None

    def all_optimal(self) -> bool:
        """Todas las fases terminaron en ``OPTIMAL``."""
        return all(p.status == "OPTIMAL" for p in self.phases)


@dataclass
class SolveOutput:
    """Salida de ``run_optimized``: preparado, subproblemas y advertencias globales."""

    prep: Prepared
    subs: list[SubResult]
    warnings: list[str]
    frontier: dict[str, Any]

    @property
    def solution(self) -> frozenset[int]:
        """Unión de las soluciones finales de los subproblemas."""
        out: set[int] = set()
        for r in self.subs:
            out |= r.final
        return frozenset(out)


def _better(objective: str, a: float, b: float) -> bool:
    """``a`` mejor que ``b`` para el objetivo de la fase."""
    if objective in ("q1", "score"):
        return a > b
    return a < b


class _PhaseRunner:
    """Ejecuta las fases de un subproblema con reparto y arrastre del presupuesto (§8.5)."""

    def __init__(self, ctx: SubContext, result: SubResult, seed: int) -> None:
        self.ctx = ctx
        self.result = result
        self.seed = seed
        self.carry = 0.0
        self.current = result.greedy

    def run(self, spec: PhaseSpec, share: float) -> PhaseOutcome:
        budget = share * self.result.budget + self.carry
        budget = max(budget, 0.01)
        hint, source = self.current, "fase anterior" if self.result.phases else "voraz"
        greedy = self.result.greedy
        if hint is not greedy and satisfies(self.ctx, spec, greedy):
            g_val = objective_value(self.ctx, spec.objective, greedy)
            h_val = objective_value(self.ctx, spec.objective, hint)
            if _better(spec.objective, g_val, h_val):
                hint, source = greedy, "voraz"
        hint = canonicalize(self.ctx, hint, spec.overbooking)
        value = objective_value(self.ctx, spec.objective, hint)
        if value == _trivial_bound(self.ctx, spec):
            # La pista ya alcanza la cota trivial: es óptima y no hace falta CP-SAT (el
            # presolve puede gastar todo el presupuesto antes de registrar la pista).
            out = PhaseOutcome(
                name=spec.name,
                status="OPTIMAL",
                objective=float(value),
                bound=float(value),
                gap=0.0,
                wall_time_s=0.0,
                deterministic_time=0.0,
                budget=budget,
                num_variables=0,
                num_constraints=0,
                solution=hint,
                hint_source=source + " (cota trivial)",
            )
        else:
            out = solve_phase(self.ctx, spec, hint, source, budget, self.seed)
        cfg = self.ctx.prep.config
        used = out.deterministic_time if cfg.solver.deterministic else out.wall_time_s
        self.carry = max(0.0, budget - used)
        self.result.phases.append(out)
        self.current = out.solution
        return out

    def skip(self, share: float) -> None:
        self.carry += share * self.result.budget


def _trivial_bound(ctx: SubContext, spec: PhaseSpec) -> int | None:
    """Cota que ninguna solución puede superar, cuando es evidente (§8.1); ``None`` si no hay."""
    prep = ctx.prep
    if spec.objective == "q1":
        return sum(1 for i in ctx.sub.entries if i in prep.q1)
    if spec.objective == "ges":
        return sum(
            1 for g in ctx.sub.entries if ctx.sub.is_obligated(prep, g) and g in prep.ges_presolve
        )
    if spec.objective == "balance":
        return 0
    return None


def _limited_groups(ctx: SubContext) -> list[GroupKey]:
    """Grupos con al menos ``min_group_n`` candidatos con pares CNE (§6.5)."""
    prep = ctx.prep
    counts: dict[GroupKey, int] = defaultdict(int)
    for i in ctx.sub.entries:
        if any(prep.block(prep.pair_block[p]).is_cne for p in ctx.pairs_by_entry.get(i, [])):
            for q in ctx.entry_groups.get(i, ()):
                counts[q] += 1
    n_min = prep.config.group_limits.min_group_n
    return sorted(q for q, n in counts.items() if n >= n_min)


def exposure_shares(
    prep: Prepared, solution: frozenset[int], entry_groups: dict[int, tuple[GroupKey, ...]]
) -> tuple[float, dict[GroupKey, float], dict[GroupKey, int]]:
    """Proporción global y por grupo de agendados CNE en bloques con sobrecupo (§6.5)."""
    levels = overbook_levels(prep, solution)
    total = exposed = 0
    g_total: dict[GroupKey, int] = defaultdict(int)
    g_exp: dict[GroupKey, int] = defaultdict(int)
    for p in solution:
        b = prep.pair_block[p]
        if not prep.block(b).is_cne:
            continue
        hit = b in levels
        total += 1
        exposed += hit
        for q in entry_groups.get(prep.pair_entry[p], ()):
            g_total[q] += 1
            g_exp[q] += hit
    share = exposed / total if total else 0.0
    return share, {q: g_exp[q] / n for q, n in g_total.items() if n}, dict(g_total)


def solve_sub(prep: Prepared, sub: Sub, budget: float) -> SubResult:
    """Fases 0 a 4 de un subproblema (§8.1)."""
    cfg = prep.config
    ctx = SubContext.build(prep, sub)
    greedy = canonicalize(
        ctx, greedy_assign(prep, sub.entries, "priority", set(sub.pairs)), overbooking=False
    )
    result = SubResult(sub=sub, ctx=ctx, budget=budget, greedy=greedy)
    runner = _PhaseRunner(ctx, result, prep.instance.seed)
    fix = Fixings()

    # Fase 1: cesión a p1.
    if any(i in prep.q1 for i in sub.entries):
        out = runner.run(PhaseSpec("1", "q1", False, fix), PHASE_SHARES["1"])
        result.f1 = int(out.objective)
        fix = Fixings(q1_min=result.f1)
    else:
        runner.skip(PHASE_SHARES["1"])

    # Fase 2: GES.
    if any(sub.is_obligated(prep, i) for i in sub.entries):
        out = runner.run(PhaseSpec("2", "ges", False, fix), PHASE_SHARES["2"])
        result.f2 = int(out.objective)
        fix = Fixings(q1_min=fix.q1_min, v_max=result.f2)
    else:
        runner.skip(PHASE_SHARES["2"])

    # Fase 3a: puntaje sin sobrecupo.
    do_3b = cfg.overbooking.enabled and bool(ctx.eligible)
    share_3a = PHASE_SHARES["3a"] if do_3b else PHASE_SHARES["3a"] + PHASE_SHARES["3b"]
    out = runner.run(PhaseSpec("3a", "score", False, fix), share_3a)
    result.z0 = result.z3 = int(out.objective)
    result.s0 = frozenset(assigned_entries(prep, out.solution))
    fix = Fixings(q1_min=fix.q1_min, v_max=fix.v_max, s0=result.s0)
    caps: dict[GroupKey, float] | None = None

    # Fase 3b: sobrecupo que solo agrega (R12, R13) y límites por grupo (R14, R15).
    if do_3b:
        fix3b = fix
        gl = cfg.group_limits
        limited = _limited_groups(ctx) if gl.enabled else []
        if limited and gl.mode == "absolute":
            assert gl.max_share is not None
            caps = dict.fromkeys(limited, gl.max_share)
        half = PHASE_SHARES["3b"] / 2 if limited and gl.mode == "relative" else PHASE_SHARES["3b"]
        sol_3a = out.solution
        out = runner.run(PhaseSpec("3b", "score", True, fix3b, caps), half)
        share, shares, totals = exposure_shares(prep, out.solution, ctx.entry_groups)
        result.fairness_passes.append(
            _pass_info(1, caps, share, shares, totals, limited, out.objective)
        )
        if limited and gl.mode == "relative":
            bound = share + gl.max_gap_pp / 100.0
            if any(shares.get(q, 0.0) > bound + 1e-12 for q in limited):
                caps = dict.fromkeys(limited, bound)
                runner.current = sol_3a  # 3a cumple cualquier tope: exposición 0
                out = runner.run(PhaseSpec("3b", "score", True, fix3b, caps), half)
                share, shares, totals = exposure_shares(prep, out.solution, ctx.entry_groups)
                result.fairness_passes.append(
                    _pass_info(2, caps, share, shares, totals, limited, out.objective)
                )
            else:
                runner.skip(half)
        result.z3 = int(out.objective)

    # Fase 4: equilibrio como desempate.
    if ctx.balance_groups:
        tol = cfg.weights.balance_tolerance
        fix4 = Fixings(
            q1_min=fix.q1_min,
            v_max=fix.v_max,
            s0=fix.s0,
            coef_min=math.ceil((1.0 - tol) * result.z3),
            overbook_levels=overbook_levels(prep, runner.current) if do_3b else None,
        )
        runner.run(PhaseSpec("4", "balance", do_3b, fix4, caps), PHASE_SHARES["4"])
    result.final = runner.current

    _check_against_greedy(result)
    return result


def _pass_info(
    n: int,
    caps: dict[GroupKey, float] | None,
    share: float,
    shares: dict[GroupKey, float],
    totals: dict[GroupKey, int],
    limited: list[GroupKey],
    objective: float,
) -> dict[str, Any]:
    return {
        "pass": n,
        "caps": None if caps is None else {f"{d}={v}": r for (d, v), r in sorted(caps.items())},
        "share_global": share,
        "objective": objective,
        "groups": [_group_info(q, caps, shares, totals) for q in limited],
    }


def _group_info(
    q: GroupKey,
    caps: dict[GroupKey, float] | None,
    shares: dict[GroupKey, float],
    totals: dict[GroupKey, int],
) -> dict[str, Any]:
    """Proporción expuesta del grupo y, con tope, la holgura de R15 (activo si < 1000)."""
    n = totals.get(q, 0)
    share = shares.get(q, 0.0)
    info: dict[str, Any] = {"dimension": q[0], "value": q[1], "scheduled_cne": n, "share": share}
    if caps is not None and q in caps:
        exposed = round(share * n)
        slack = round_half_up(UTIL_SCALE * caps[q]) * n - UTIL_SCALE * exposed
        info.update(cap=caps[q], r15_slack=slack, binding=slack < UTIL_SCALE)
    return info


def _check_against_greedy(r: SubResult) -> None:
    """Verificación §9.5: el plan no es peor que la voraz en orden lexicográfico."""
    prep = r.ctx.prep
    g = r.greedy
    greedy_vec = (
        len(assigned_entries(prep, g) & prep.q1),
        -len(unmet_ges(prep, r.sub, g)),
        coef_sum(prep, g),
    )
    plan_vec = (
        r.f1 if r.f1 is not None else greedy_vec[0],
        -r.f2 if r.f2 is not None else greedy_vec[1],
        r.z0,
    )
    if plan_vec < greedy_vec:
        msg = (
            f"subproblema {r.sub.label}: plan {plan_vec} peor que la voraz {greedy_vec} "
            "en orden lexicográfico"
        )
        if r.all_optimal():
            raise RuntimeError(msg + " con todas las fases en OPTIMAL (error de implementación)")
        r.warnings.append("worse_than_baseline: " + msg)


def _week_index(prep: Prepared, b: int) -> int:
    return (prep.block(b).local_date - prep.instance.horizon_start).days // 7


def _solve_component(prep: Prepared, comp: list[int], label: str, budget: float) -> list[SubResult]:
    """Resuelve un componente; respaldo por especialidad y luego por semana (§8.3)."""
    cfg = prep.config
    n_pairs = sum(len(prep.pairs_of_entry.get(i, [])) for i in comp)
    if cfg.decomposition != "specialty" and n_pairs <= cfg.max_pairs_per_subproblem:
        return [solve_sub(prep, Sub.build(prep, label, comp), budget)]

    results: list[SubResult] = []
    busy: set[tuple[str, date]] = set()

    def free(pid: int) -> bool:
        e = prep.entry(prep.pair_entry[pid])
        return (e.patient_id, prep.block(prep.pair_block[pid]).local_date) not in busy

    def record(r: SubResult) -> None:
        results.append(r)
        for pid in r.final:
            e = prep.entry(prep.pair_entry[pid])
            busy.add((e.patient_id, prep.block(prep.pair_block[pid]).local_date))

    by_spec: dict[str, list[int]] = defaultdict(list)
    for i in comp:
        by_spec[prep.entry(i).specialty_code].append(i)
    for spec_code in sorted(by_spec):
        ents = by_spec[spec_code]
        pairs = [p for i in ents for p in prep.pairs_of_entry.get(i, []) if free(p)]
        part_budget = budget * len(pairs) / max(1, n_pairs)
        if len(pairs) <= cfg.max_pairs_per_subproblem:
            sub = Sub.build(prep, f"{label}/{spec_code}", ents, pairs, "by_specialty")
            if sub.pairs:
                record(solve_sub(prep, sub, part_budget))
            continue
        remaining = set(ents)
        weeks = sorted({_week_index(prep, prep.pair_block[p]) for p in pairs})
        for w in weeks:
            wp = [
                p
                for i in sorted(remaining)
                for p in prep.pairs_of_entry.get(i, [])
                if _week_index(prep, prep.pair_block[p]) == w and free(p)
            ]
            later = {
                prep.pair_entry[p]
                for i in remaining
                for p in prep.ges_satisfying.get(i, [])
                if _week_index(prep, prep.pair_block[p]) > w
            }
            obligated = frozenset(i for i in remaining if i in prep.obligation and i not in later)
            sub = Sub.build(
                prep, f"{label}/{spec_code}/w{w}", sorted(remaining), wp, "by_week", obligated
            )
            if not sub.pairs:
                continue
            r = solve_sub(prep, sub, budget * len(wp) / max(1, n_pairs))
            record(r)
            remaining -= assigned_entries(prep, r.final)
    return results


def _frontier_queues(prep: Prepared, solution: frozenset[int]) -> set[QueueKey]:
    """Colas donde el filtro de candidatos pudo ser activo (§8.2).

    Dos señales: (a) se agendó alguna entrada del último 10 % de candidatos; (b) queda
    capacidad libre en un bloque que una entrada descartada podría usar (su paciente no tiene
    otra cita ese día). La (b) detecta colas donde los candidatos no alcanzan, por ejemplo
    porque varias entradas del mismo paciente compiten por el mismo día (R4).
    """
    assigned = assigned_entries(prep, solution)
    hit = {q for q, tail in prep.frontier_tail.items() if tail & assigned}
    loads = block_loads(prep, solution)
    busy = {
        (prep.entry(prep.pair_entry[p]).patient_id, prep.block(prep.pair_block[p]).local_date)
        for p in solution
    }
    for i, (q, _) in prep.filtered_out.items():
        if q in hit:
            continue
        patient = prep.entry(i).patient_id
        for p in prep.pairs_of_entry.get(i, []):
            b = prep.pair_block[p]
            free = prep.capacity[b] - loads.get(b, 0)
            if free >= prep.pair_load(p) and (patient, prep.block(b).local_date) not in busy:
                hit.add(q)
                break
    return hit


def run_optimized(instance: SchedulingInstance, config: SchedulerConfig) -> SolveOutput:
    """Política ``optimized``: filtro, componentes, fases y comprobación de frontera."""
    prep = prepare(instance, config)
    select_candidates(prep, config.candidate_margin)
    comps = components(prep, prep.candidates)
    total_pairs = sum(len(prep.pairs_of_entry.get(i, [])) for c in comps for i in c)

    def budget_of(comp: list[int]) -> float:
        n = sum(len(prep.pairs_of_entry.get(i, [])) for i in comp)
        return max(1.0, config.time_limit_s * n / max(1, total_pairs))

    def label_of(comp: list[int]) -> str:
        services = sorted({prep.entry(i).health_service_code for i in comp})
        specs = sorted({prep.entry(i).specialty_code for i in comp})
        head = "+".join(str(s) for s in services)
        return f"{head}:{specs[0]}" if len(specs) == 1 else f"{head}"

    solved: dict[tuple[int, ...], list[SubResult]] = {}
    for n, comp in enumerate(comps):
        solved[tuple(comp)] = _solve_component(
            prep, comp, f"c{n}[{label_of(comp)}]", budget_of(comp)
        )
    warnings: list[str] = []
    solution = frozenset(p for rs in solved.values() for r in rs for p in r.final)
    hit = _frontier_queues(prep, solution)
    frontier: dict[str, Any] = {
        "reached": sorted(f"{q[0]}|{q[1]}" for q in hit),
        "expanded": False,
        "still_reached": [],
    }
    if hit:
        warnings.append(f"candidate_frontier_reached en {len(hit)} colas")
    if hit and config.expand_on_frontier:
        margins = {q: 2.0 * config.candidate_margin for q in hit}
        select_candidates(prep, config.candidate_margin, margins)
        new_comps = components(prep, prep.candidates)
        resolved: dict[tuple[int, ...], list[SubResult]] = {}
        for n, comp in enumerate(new_comps):
            key = tuple(comp)
            if key in solved:
                resolved[key] = solved[key]
            else:
                resolved[key] = _solve_component(
                    prep, comp, f"c{n}x[{label_of(comp)}]", budget_of(comp)
                )
        solved = resolved
        solution = frozenset(p for rs in solved.values() for r in rs for p in r.final)
        still = _frontier_queues(prep, solution) & hit
        frontier["expanded"] = True
        frontier["still_reached"] = sorted(f"{q[0]}|{q[1]}" for q in still)
        if still:
            warnings.append(
                f"candidate_frontier_reached persiste tras duplicar el margen en {len(still)} colas"
            )
    subs = [r for rs in solved.values() for r in rs]
    for r in subs:
        warnings.extend(f"{r.sub.label}: {w}" for w in r.warnings)
    return SolveOutput(prep=prep, subs=subs, warnings=warnings, frontier=frontier)
