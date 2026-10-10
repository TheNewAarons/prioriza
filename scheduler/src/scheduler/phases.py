"""Orquestación: filtro, descomposición, fases lexicográficas y frontera (formulación §8).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
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
    cap_units,
    coef_sum,
    objective_value,
    overbook_levels,
    overbooking_fill,
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
    select_candidates,
)

PHASE_SHARES = {"1": 0.10, "2": 0.10, "3a": 0.325, "3b": 0.325, "4": 0.15}
STATUS_RANK = {"OPTIMAL": 0, "FEASIBLE": 1, "UNKNOWN": 2}
# Libros del presupuesto (§8.5): las fases 1-3a ("base") no dependen de p ni del interruptor de
# sobrecupo; las 3b y 4 ("rest") sí. Cada libro reparte y arrastra solo su propio tiempo, así que
# el presupuesto de la fase 3a (y con él S0 si termina por tiempo) nunca depende de p.
LEDGER = {"1": "base", "2": "base", "3a": "base", "3b": "rest", "4": "rest"}
BASE_SHARE = PHASE_SHARES["1"] + PHASE_SHARES["2"] + PHASE_SHARES["3a"]
REST_SHARE = PHASE_SHARES["3b"] + PHASE_SHARES["4"]


@dataclass(frozen=True)
class Budget:
    """Presupuesto de un subproblema en sus dos libros (fases 1-3a y fases 3b-4)."""

    base: float
    rest: float

    @property
    def total(self) -> float:
        """Suma de los dos libros."""
        return self.base + self.rest

    def scaled(self, factor: float) -> Budget:
        """Mismo reparto por libro, multiplicado por ``factor``."""
        return Budget(self.base * factor, self.rest * factor)

    @staticmethod
    def split(total: float) -> Budget:
        """Reparte ``total`` entre los libros según ``PHASE_SHARES``."""
        return Budget(total * BASE_SHARE, total * REST_SHARE)


@dataclass
class SubResult:
    """Resultado de un subproblema: fases, soluciones y valores fijados."""

    sub: Sub
    ctx: SubContext
    budget: float  # total de los dos libros
    greedy: frozenset[int]
    phases: list[PhaseOutcome] = field(default_factory=list)
    fairness_passes: list[dict[str, Any]] = field(default_factory=list)
    final: frozenset[int] = frozenset()
    s0: frozenset[int] = frozenset()
    # Agendados al cerrar la fase 3b (``S0`` si no hubo 3b): la fase 4 los fija exactos (§8.1).
    s3: frozenset[int] = frozenset()
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

    def ran_3b(self) -> bool:
        """La fase 3b (sobrecupo) corrió en este subproblema."""
        return self.phase("3b") is not None

    def spent(self, deterministic: bool, ledger: str | None = None) -> float:
        """Tiempo gastado (determinista o de reloj), total o de un libro."""
        return sum(
            (p.deterministic_time if deterministic else p.wall_time_s)
            for p in self.phases
            if ledger is None or LEDGER[p.name] == ledger
        )


@dataclass
class SolveOutput:
    """Salida de ``run_optimized``: preparado, subproblemas y advertencias globales."""

    prep: Prepared
    subs: list[SubResult]
    warnings: list[str]
    frontier: dict[str, Any]
    # Subproblemas de la primera pasada que la expansión de frontera reemplazó: no aportan al
    # plan, pero su tiempo de solver cuenta en el informe.
    discarded: list[SubResult] = field(default_factory=list)
    # Bloque ``solver.budget`` del informe (presupuesto global, §8.5).
    budget: dict[str, Any] = field(default_factory=dict)

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
    """Ejecuta las fases de un subproblema con reparto y arrastre del presupuesto (§8.5).

    Cada fase recibe su parte de ``PHASE_SHARES`` dentro de su libro más lo que las fases
    anteriores del mismo libro no gastaron. Lo que la fase 3a no gasta no pasa a la 3b: vuelve
    al libro base de la pasada y lo usan las fases 1-3a de los componentes siguientes.
    """

    def __init__(
        self,
        ctx: SubContext,
        result: SubResult,
        budget: Budget,
        seed: int,
        warm: frozenset[int] | None = None,
    ) -> None:
        self.ctx = ctx
        self.result = result
        self.budget = budget
        self.seed = seed
        self.carry = {"base": 0.0, "rest": 0.0}
        self.current = result.greedy
        self.source = "voraz"
        # Pistas alternativas sin sobrecupo: se usan si cumplen lo fijado y son mejores.
        self.alternatives: list[tuple[frozenset[int], str]] = [(result.greedy, "voraz")]
        if warm is not None:
            self.alternatives.append((warm, "primera pasada"))

    def _part(self, name: str, share: float) -> float:
        """``share`` (fracción de ``PHASE_SHARES``) en unidades del libro de la fase."""
        if LEDGER[name] == "base":
            return share / BASE_SHARE * self.budget.base
        return share / REST_SHARE * self.budget.rest

    def run(self, spec: PhaseSpec, share: float) -> PhaseOutcome:
        ledger = LEDGER[spec.name]
        budget = self._part(spec.name, share) + self.carry[ledger]
        budget = max(budget, 0.01)
        hint, source = self.current, self.source
        h_val = objective_value(self.ctx, spec.objective, hint)
        for alt, alt_source in self.alternatives:
            if alt is hint or not satisfies(self.ctx, spec, alt):
                continue
            a_val = objective_value(self.ctx, spec.objective, alt)
            if _better(spec.objective, a_val, h_val):
                hint, source, h_val = alt, alt_source, a_val
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
        self.carry[ledger] = max(0.0, budget - used)
        self.result.phases.append(out)
        self.current = out.solution
        self.source = "fase anterior"
        return out

    def start_from(self, solution: frozenset[int], source: str) -> None:
        """Fija la pista de la próxima fase."""
        self.current = solution
        self.source = source

    def skip(self, name: str, share: float) -> None:
        """La parte de una fase que no corre pasa a la siguiente fase de su libro."""
        self.carry[LEDGER[name]] += self._part(name, share)


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


def solve_sub(
    prep: Prepared, sub: Sub, budget: Budget | float, warm: frozenset[int] | None = None
) -> SubResult:
    """Fases 0 a 4 de un subproblema (§8.1).

    ``budget`` es el presupuesto por libro; un número se reparte según ``PHASE_SHARES``.
    ``warm`` es una solución sin sobrecupo de una pasada anterior (expansión de frontera); se
    ofrece como pista en cada fase en la que cumple lo fijado y mejora a la pista vigente.
    """
    if not isinstance(budget, Budget):
        budget = Budget.split(budget)
    cfg = prep.config
    ctx = SubContext.build(prep, sub)
    pairs = set(sub.pairs)
    greedy = canonicalize(
        ctx, greedy_assign(prep, sub.entries, "priority", pairs), overbooking=False
    )
    result = SubResult(sub=sub, ctx=ctx, budget=budget.total, greedy=greedy)
    if warm is not None:
        warm = canonicalize(ctx, frozenset(p for p in warm if p in pairs), overbooking=False)
    runner = _PhaseRunner(ctx, result, budget, prep.instance.seed, warm)
    fill = cfg.solver.overbooking_hint
    fix = Fixings()

    # Fase 1: cesión a p1.
    if any(i in prep.q1 for i in sub.entries):
        out = runner.run(PhaseSpec("1", "q1", False, fix), PHASE_SHARES["1"])
        result.f1 = int(out.objective)
        fix = Fixings(q1_min=result.f1)
    else:
        runner.skip("1", PHASE_SHARES["1"])

    # Fase 2: GES.
    if any(sub.is_obligated(prep, i) for i in sub.entries):
        out = runner.run(PhaseSpec("2", "ges", False, fix), PHASE_SHARES["2"])
        result.f2 = int(out.objective)
        fix = Fixings(q1_min=fix.q1_min, v_max=result.f2)
    else:
        runner.skip("2", PHASE_SHARES["2"])

    # Fase 3a: puntaje sin sobrecupo. Su presupuesto no depende de p ni del interruptor de
    # sobrecupo (§8.5): si no hay fase 3b, su parte pasa a la fase 4 (libro "rest").
    do_3b = cfg.overbooking.enabled and bool(ctx.eligible)
    out = runner.run(PhaseSpec("3a", "score", False, fix), PHASE_SHARES["3a"])
    if not do_3b:
        runner.skip("3b", PHASE_SHARES["3b"])
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
        if fill:
            runner.start_from(overbooking_fill(ctx, sol_3a, caps), "voraz con sobrecupo")
        out = runner.run(PhaseSpec("3b", "score", True, fix3b, caps), half)
        share, shares, totals = exposure_shares(prep, out.solution, ctx.entry_groups)
        result.fairness_passes.append(
            _pass_info(1, caps, share, shares, totals, limited, out.objective)
        )
        if limited and gl.mode == "relative":
            bound = share + gl.max_gap_pp / 100.0
            if any(shares.get(q, 0.0) > bound + 1e-12 for q in limited):
                caps = dict.fromkeys(limited, bound)
                # 3a cumple cualquier tope (exposición 0); la voraz agrega respetando los topes.
                if fill:
                    runner.start_from(overbooking_fill(ctx, sol_3a, caps), "voraz con sobrecupo")
                else:
                    runner.start_from(sol_3a, "fase 3a")
                out = runner.run(PhaseSpec("3b", "score", True, fix3b, caps), half)
                share, shares, totals = exposure_shares(prep, out.solution, ctx.entry_groups)
                result.fairness_passes.append(
                    _pass_info(2, caps, share, shares, totals, limited, out.objective)
                )
            else:
                runner.skip("3b", half)
        result.z3 = int(out.objective)

    # Agendados al cerrar la 3b (o S0 sin 3b): la fase 4 solo puede moverlos de bloque.
    result.s3 = frozenset(assigned_entries(prep, runner.current))

    # Fase 4: equilibrio como desempate.
    if ctx.balance_groups:
        tol = cfg.weights.balance_tolerance
        fix4 = Fixings(
            q1_min=fix.q1_min,
            v_max=fix.v_max,
            s0=fix.s0,
            coef_min=math.ceil((1.0 - tol) * result.z3),
            overbook_levels=overbook_levels(prep, runner.current) if do_3b else None,
            assigned_exact=result.s3,
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
        slack = cap_units(caps[q]) * n - UTIL_SCALE * exposed
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
        # Las fases 1 y 2 se resuelven sin brecha; la 3a, con ``relative_gap_limit``, y CP-SAT
        # declara OPTIMAL al alcanzarla. Solo es error si el óptimo de 3a está probado (brecha 0)
        # o si la pérdida está en p1 o GES; dentro de la brecha relativa es una advertencia.
        phase_3a = r.phase("3a")
        exact_3a = phase_3a is not None and phase_3a.gap == 0.0
        if r.all_optimal() and (exact_3a or plan_vec[:2] < greedy_vec[:2]):
            raise RuntimeError(msg + " con todas las fases en OPTIMAL (error de implementación)")
        if r.all_optimal():
            msg += " (dentro de la brecha relativa de la fase 3a)"
        r.warnings.append("worse_than_baseline: " + msg)


def _week_index(prep: Prepared, b: int) -> int:
    return (prep.block(b).local_date - prep.instance.horizon_start).days // 7


def _solve_component(
    prep: Prepared,
    comp: list[int],
    label: str,
    budget: Budget,
    warm: frozenset[int] | None = None,
) -> list[SubResult]:
    """Resuelve un componente; respaldo por especialidad y luego por semana (§8.3).

    ``warm`` (pista de una pasada anterior) solo se usa si el componente se resuelve entero.
    """
    cfg = prep.config
    n_pairs = sum(len(prep.pairs_of_entry.get(i, [])) for i in comp)
    if cfg.decomposition != "specialty" and n_pairs <= cfg.max_pairs_per_subproblem:
        return [solve_sub(prep, Sub.build(prep, label, comp), budget, warm)]

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
        part_budget = budget.scaled(len(pairs) / max(1, n_pairs))
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
            r = solve_sub(prep, sub, budget.scaled(len(wp) / max(1, n_pairs)))
            record(r)
            remaining -= assigned_entries(prep, r.final)
    return results


def _base_solution(results: Iterable[SubResult]) -> frozenset[int]:
    """Unión de las soluciones de la fase 3a (sin sobrecupo) de los subproblemas."""
    out: set[int] = set()
    for r in results:
        ph = r.phase("3a")
        out.update(ph.solution if ph is not None else r.final)
    return frozenset(out)


def _frontier_queues(prep: Prepared, solution: frozenset[int]) -> set[QueueKey]:
    """Colas donde el filtro de candidatos pudo ser activo (§8.2).

    ``solution`` es la de la fase 3a, sin sobrecupo: así la frontera, y con ella los
    candidatos y las fases 1-3a, no dependen de p ni del interruptor de sobrecupo.

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


# ------------------------------------------------------------------ presupuesto global (§8.5)

LIMIT_STATUSES = ("FEASIBLE", "UNKNOWN")


def _n_pairs(prep: Prepared, comp: Iterable[int]) -> int:
    return sum(len(prep.pairs_of_entry.get(i, [])) for i in comp)


@dataclass
class _Task:
    """Componente por resolver en una pasada, con su etiqueta y su pista de primera pasada."""

    key: tuple[int, ...]
    label: str
    warm: frozenset[int] | None = None


@dataclass
class _PassResult:
    """Resultado de una pasada: soluciones por componente, gasto por libro y omitidos."""

    allotted: Budget
    solved: dict[tuple[int, ...], list[SubResult]] = field(default_factory=dict)
    spent_base: float = 0.0
    spent_rest: float = 0.0
    skipped: list[_Task] = field(default_factory=list)

    @property
    def spent(self) -> float:
        """Gasto total de la pasada."""
        return self.spent_base + self.spent_rest


def _share_of(left: float, n_left: int, minimum: float, pairs: int, pairs_left: int) -> float:
    """Mínimo más la parte proporcional a ``pairs`` del saldo sobre los mínimos que faltan."""
    extra = max(0.0, left - n_left * minimum)
    return minimum + extra * pairs / max(1, pairs_left)


def _run_pass(prep: Prepared, tasks: list[_Task], pool: Budget, can_skip: bool) -> _PassResult:
    """Resuelve los componentes de una pasada repartiendo ``pool`` (§8.5).

    Orden: pares ascendentes (desempate: orden de ``tasks``), para que lo que los componentes
    chicos no gastan pase a los grandes. En cada libro, cada componente recibe un mínimo
    (``min(min_component_budget·parte del libro, 0,2·saldo inicial del libro/n)``) y el resto del
    saldo del libro se reparte en proporción a sus pares entre los componentes que faltan: lo no
    gastado se redistribuye. En la primera pasada (``can_skip = False``) el mínimo se da siempre;
    en la expansión de frontera, si el saldo del libro base no alcanza su mínimo, los
    componentes que faltan se omiten (conservan la primera pasada). La decisión usa solo el libro
    base, así que no depende de p. Todo depende solo del tiempo que reporta CP-SAT: en modo
    determinista es reproducible.
    """
    out = _PassResult(allotted=pool)
    if not tasks:
        return out
    cfg = prep.config
    det = cfg.solver.deterministic
    pairs = {t.key: _n_pairs(prep, t.key) for t in tasks}
    order = sorted(range(len(tasks)), key=lambda k: (pairs[tasks[k].key], k))
    # Mínimo por libro con el saldo de cada libro: el del libro base no ve el gasto de 3b-4.
    floor = Budget.split(cfg.solver.min_component_budget)
    minimum = Budget(
        min(floor.base, 0.2 * pool.base / len(tasks)),
        min(floor.rest, 0.2 * pool.rest / len(tasks)),
    )
    pairs_left = sum(pairs.values())
    for pos, k in enumerate(order):
        task = tasks[k]
        n_left = len(order) - pos
        left_base = pool.base - out.spent_base
        left_rest = pool.rest - out.spent_rest
        if can_skip and (left_base <= 0.0 or left_base < minimum.base):
            out.skipped.extend(tasks[j] for j in order[pos:])
            break
        n = pairs[task.key]
        budget = Budget(
            _share_of(left_base, n_left, minimum.base, n, pairs_left),
            _share_of(left_rest, n_left, minimum.rest, n, pairs_left),
        )
        results = _solve_component(prep, list(task.key), task.label, budget, task.warm)
        out.solved[task.key] = results
        out.spent_base += sum(r.spent(det, "base") for r in results)
        out.spent_rest += sum(r.spent(det, "rest") for r in results)
        pairs_left -= n
    return out


def _restore_filter(
    prep: Prepared,
    skipped: Iterable[tuple[int, ...]],
    old_candidates: frozenset[int],
    old_filtered: dict[int, tuple[QueueKey, int]],
    old_tail: dict[QueueKey, frozenset[int]],
    old_cutoff: dict[QueueKey, int],
) -> None:
    """Devuelve al filtro de la primera pasada las entradas de componentes omitidos.

    Las entradas que solo entraron con el margen duplicado y cuyo componente no se resolvió de
    nuevo nunca estuvieron en un modelo: vuelven a ``filtered_out`` (``not_candidate``). En las
    colas sin otras entradas nuevas resueltas, la cola de frontera y el corte vuelven a los de la
    primera pasada, así que la comprobación de frontera las sigue viendo alcanzadas.
    """
    back = {i for key in skipped for i in key if i not in old_candidates}
    if not back:
        return
    prep.candidates = frozenset(prep.candidates - back)
    filtered = dict(prep.filtered_out)
    for i in sorted(back):
        filtered[i] = old_filtered[i]
    prep.filtered_out = filtered
    still_new = {prep.queue[i] for i in prep.candidates - old_candidates}
    tail = dict(prep.frontier_tail)
    cutoff = dict(prep.queue_cutoff)
    for q in sorted({prep.queue[i] for i in back} - still_new):
        cutoff[q] = old_cutoff[q]
        if q in old_tail:
            tail[q] = old_tail[q]
        else:
            tail.pop(q, None)
    prep.frontier_tail = tail
    prep.queue_cutoff = cutoff


def run_optimized(instance: SchedulingInstance, config: SchedulerConfig) -> SolveOutput:
    """Política ``optimized``: filtro, componentes, fases y comprobación de frontera.

    ``config.time_limit_s`` es el presupuesto ``B`` de todo el plan (§8.5): la primera pasada
    recibe ``first_pass_share·B`` (todo ``B`` si no hay expansión de frontera) y la expansión,
    lo que quede en cada libro.
    """
    prep = prepare(instance, config)
    select_candidates(prep, config.candidate_margin)
    comps = components(prep, prep.candidates)
    total = Budget.split(config.time_limit_s)
    expand = config.expand_on_frontier
    first_pool = total.scaled(config.solver.first_pass_share) if expand else total

    def label_of(comp: list[int]) -> str:
        services = sorted({prep.entry(i).health_service_code for i in comp})
        specs = sorted({prep.entry(i).specialty_code for i in comp})
        head = "+".join(str(s) for s in services)
        return f"{head}:{specs[0]}" if len(specs) == 1 else f"{head}"

    first = _run_pass(
        prep,
        [_Task(tuple(c), f"c{n}[{label_of(c)}]") for n, c in enumerate(comps)],
        first_pool,
        can_skip=False,
    )
    # Orden del informe: el de los componentes, no el de resolución.
    solved = {tuple(c): first.solved[tuple(c)] for c in comps}
    warnings: list[str] = []
    discarded: list[SubResult] = []
    hit = _frontier_queues(prep, _base_solution(r for rs in solved.values() for r in rs))
    frontier: dict[str, Any] = {
        "reached": sorted(f"{q[0]}|{q[1]}" for q in hit),
        "expanded": False,
        "still_reached": [],
    }
    second = _PassResult(allotted=Budget(0.0, 0.0))
    if hit:
        warnings.append(f"candidate_frontier_reached en {len(hit)} colas")
    if hit and expand:
        saved = (prep.candidates, prep.filtered_out, prep.frontier_tail, prep.queue_cutoff)
        margins = {q: 2.0 * config.candidate_margin for q in hit}
        select_candidates(prep, config.candidate_margin, margins)
        new_comps = components(prep, prep.candidates)
        # Cada componente anterior queda dentro de uno nuevo (los candidatos solo crecen).
        first_pass = {i: key for key in solved for i in key}
        olds: dict[tuple[int, ...], list[tuple[int, ...]]] = {}
        tasks: list[_Task] = []
        for n, comp in enumerate(new_comps):
            key = tuple(comp)
            if key in solved:
                continue
            old = sorted({first_pass[i] for i in comp if i in first_pass})
            olds[key] = old
            warm: frozenset[int] | None = None
            if config.solver.warm_start_frontier:
                warm = frozenset(
                    p
                    for k in old
                    for r in solved[k]
                    if (ph := r.phase("3a")) is not None
                    for p in ph.solution
                )
            tasks.append(_Task(key, f"c{n}x[{label_of(comp)}]", warm))
        pool = Budget(
            max(0.0, total.base - first.spent_base), max(0.0, total.rest - first.spent_rest)
        )
        second = _run_pass(prep, tasks, pool, can_skip=True)
        resolved: dict[tuple[int, ...], list[SubResult]] = {}
        for comp in new_comps:
            key = tuple(comp)
            if key in solved:
                resolved[key] = solved[key]
            elif key in second.solved:
                discarded.extend(r for k in olds[key] for r in solved[k])
                resolved[key] = second.solved[key]
            else:
                # Sin presupuesto para resolverlo de nuevo: queda la primera pasada.
                for k in olds[key]:
                    resolved[k] = solved[k]
        if second.skipped:
            _restore_filter(prep, (t.key for t in second.skipped), *saved)
            warnings.append(
                f"frontier_expansion_skipped_budget: {len(second.skipped)} componentes conservan "
                "la primera pasada por falta de presupuesto"
            )
        solved = resolved
        base = _base_solution(r for rs in solved.values() for r in rs)
        still = _frontier_queues(prep, base) & hit
        frontier["expanded"] = True
        frontier["still_reached"] = sorted(f"{q[0]}|{q[1]}" for q in still)
        frontier["skipped_components"] = [t.label for t in second.skipped]
        if still:
            warnings.append(
                f"candidate_frontier_reached persiste tras duplicar el margen en {len(still)} colas"
            )
    subs = [r for rs in solved.values() for r in rs]
    budget = _budget_report(prep, first, second, subs, discarded)
    if budget["exhausted"]:
        warnings.append(
            f"time_budget_exhausted: {budget['phases_ended_by_limit']} fases terminaron por el "
            f"límite de tiempo y {budget['frontier']['components_skipped']} componentes no se "
            f"resolvieron de nuevo (presupuesto {config.time_limit_s:g}, unidad "
            f"{budget['unit']})"
        )
    for r in subs:
        warnings.extend(f"{r.sub.label}: {w}" for w in r.warnings)
    return SolveOutput(
        prep=prep,
        subs=subs,
        warnings=warnings,
        frontier=frontier,
        discarded=discarded,
        budget=budget,
    )


def _pass_report(p: _PassResult) -> dict[str, Any]:
    return {
        "allotted": p.allotted.total,
        "spent": p.spent,
        "phases_1_3a": {"allotted": p.allotted.base, "spent": p.spent_base},
        "phases_3b_4": {"allotted": p.allotted.rest, "spent": p.spent_rest},
    }


def _budget_report(
    prep: Prepared,
    first: _PassResult,
    second: _PassResult,
    subs: list[SubResult],
    discarded: list[SubResult],
) -> dict[str, Any]:
    """Bloque ``solver.budget`` del informe (§8.5); sin tiempo de reloj en modo determinista.

    ``exhausted``: el presupuesto limitó el resultado (alguna fase terminó por tiempo, en
    ``FEASIBLE`` o ``UNKNOWN``, o la expansión de frontera omitió componentes).
    """
    cfg = prep.config
    total = cfg.time_limit_s
    spent = first.spent + second.spent
    by_limit = sum(1 for r in [*subs, *discarded] for p in r.phases if p.status in LIMIT_STATUSES)
    return {
        "unit": "deterministic" if cfg.solver.deterministic else "seconds",
        "total": total,
        "first_pass": _pass_report(first),
        "frontier": {**_pass_report(second), "components_skipped": len(second.skipped)},
        "spent": spent,
        "exhausted": by_limit > 0 or bool(second.skipped),
        "phases_ended_by_limit": by_limit,
        # CP-SAT revisa el límite por lotes: el gasto puede superar el presupuesto.
        "overrun": max(0.0, spent - total),
    }
