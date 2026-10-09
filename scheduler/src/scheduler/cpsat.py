"""Modelo CP-SAT de un subproblema y resolución de una fase.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Implementa las variables (§5), las restricciones R1-R15 (§6), los objetivos de cada fase
(§6.6 y §8.1), las simetrías (§8.4) y los parámetros del solver (§8.5) de
``docs/scheduler-formulation.md``. El modelo se reconstruye en cada fase: es barato frente
a la búsqueda y deja cada fase autocontenida.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Literal

from ortools.sat.python import cp_model

from scheduler.config import SchedulerConfig
from scheduler.prepare import Prepared, round_half_up
from scheduler.risk import chernoff_theta, coef_one, coef_theta, rhs_one, rhs_theta

GroupKey = tuple[str, str]  # (dimensión, valor)
Objective = Literal["q1", "ges", "score", "balance"]
UTIL_SCALE = 1000


@dataclass(frozen=True)
class Sub:
    """Subproblema: entradas candidatas, sus pares y los bloques que tocan."""

    label: str
    entries: tuple[int, ...]
    pairs: tuple[int, ...]
    blocks: tuple[int, ...]
    decomposition: str = "component"
    obligated: frozenset[int] | None = None  # None: toda GES obligada de ``entries``

    @staticmethod
    def build(
        prep: Prepared,
        label: str,
        entries: list[int],
        pairs: list[int] | None = None,
        decomposition: str = "component",
        obligated: frozenset[int] | None = None,
    ) -> Sub:
        """Subproblema con los pares dados (por defecto, todos los de ``entries``)."""
        if pairs is None:
            pairs = [p for i in sorted(entries) for p in prep.pairs_of_entry.get(i, [])]
        with_pairs = sorted({prep.pair_entry[p] for p in pairs})
        blocks = sorted({prep.pair_block[p] for p in pairs})
        return Sub(label, tuple(with_pairs), tuple(pairs), tuple(blocks), decomposition, obligated)

    def is_obligated(self, prep: Prepared, g: int) -> bool:
        """``g`` tiene obligación GES en este subproblema (R5/R6)."""
        return g in prep.obligation and (self.obligated is None or g in self.obligated)


@dataclass(frozen=True)
class Fixings:
    """Lo que las fases anteriores dejaron fijo (§8.1)."""

    q1_min: int | None = None
    v_max: int | None = None
    s0: frozenset[int] | None = None
    coef_min: int | None = None
    overbook_levels: Mapping[int, int] | None = None


@dataclass(frozen=True)
class PhaseSpec:
    """Definición de una fase: objetivo, sobrecupo, fijaciones y topes por grupo."""

    name: str
    objective: Objective
    overbooking: bool
    fix: Fixings = Fixings()
    group_caps: Mapping[GroupKey, float] | None = None


@dataclass(frozen=True)
class PhaseOutcome:
    """Resultado de una fase."""

    name: str
    status: str
    objective: float
    bound: float | None
    gap: float | None
    wall_time_s: float
    deterministic_time: float
    budget: float
    num_variables: int
    num_constraints: int
    solution: frozenset[int]
    hint_source: str


@dataclass
class SubContext:
    """Datos del subproblema reutilizados entre fases (índices, elegibilidad y simetrías)."""

    prep: Prepared
    sub: Sub
    pairs_by_entry: dict[int, list[int]] = field(default_factory=dict)
    pairs_by_block: dict[int, list[int]] = field(default_factory=dict)
    patient_day_pairs: list[list[int]] = field(default_factory=list)
    eligible: dict[int, float] = field(default_factory=dict)  # bloque -> p media
    entry_groups: dict[int, tuple[GroupKey, ...]] = field(default_factory=dict)
    # Clases de simetría sin p (fases sin sobrecupo) y con p (fases 3b y 4 con sobrecupo).
    # Las clases con p refinan a las sin p, así que una solución de la fase 3a cumple ambas.
    block_classes: dict[bool, list[list[int]]] = field(default_factory=dict)
    entry_classes: dict[bool, list[list[int]]] = field(default_factory=dict)
    balance_groups: list[list[int]] = field(default_factory=list)

    @staticmethod
    def build(prep: Prepared, sub: Sub) -> SubContext:
        """Precalcula índices, elegibilidad para sobrecupo y clases de simetría."""
        ctx = SubContext(prep, sub)
        cfg = prep.config
        by_entry: dict[int, list[int]] = defaultdict(list)
        by_block: dict[int, list[int]] = defaultdict(list)
        for p in sub.pairs:
            by_entry[prep.pair_entry[p]].append(p)
            by_block[prep.pair_block[p]].append(p)
        ctx.pairs_by_entry = dict(by_entry)
        ctx.pairs_by_block = dict(by_block)

        by_patient: dict[str, list[int]] = defaultdict(list)
        for i in sub.entries:
            by_patient[prep.entry(i).patient_id].append(i)
        for entries in by_patient.values():
            if len(entries) < 2:
                continue
            by_day: dict[date, list[int]] = defaultdict(list)
            for i in entries:
                for p in by_entry.get(i, []):
                    by_day[prep.block(prep.pair_block[p]).local_date].append(p)
            ctx.patient_day_pairs.extend(
                ps for ps in by_day.values() if len({prep.pair_entry[p] for p in ps}) >= 2
            )

        if cfg.overbooking.enabled:
            for b in sub.blocks:
                ps = by_block[b]
                if not prep.block(b).is_cne or prep.overbook_max[b] < 1:
                    continue
                if all(prep.pair_load(p) == 1 and prep.pair_p[p] is not None for p in ps):
                    probs = [prep.pair_p[p] or 0.0 for p in ps]
                    ctx.eligible[b] = sum(probs) / len(probs)

        dims = cfg.group_limits.dimensions
        for i in sub.entries:
            attrs = prep.instance.groups.get(prep.entry(i).patient_id, {})
            ctx.entry_groups[i] = tuple((d, attrs[d]) for d in dims if d in attrs)

        for with_p in (False, True):
            ctx.block_classes[with_p] = _block_classes(ctx, with_p)
            ctx.entry_classes[with_p] = _entry_classes(ctx, by_patient, with_p)
        balance: dict[tuple[str, str], list[int]] = defaultdict(list)
        for b in sub.blocks:
            if prep.capacity[b] > 0:
                blk = prep.block(b)
                balance[(blk.specialty_code, blk.resource_kind)].append(b)
        ctx.balance_groups = [bs for _, bs in sorted(balance.items()) if len(bs) >= 2]
        return ctx


def _block_classes(ctx: SubContext, with_p: bool) -> list[list[int]]:
    """Bloques intercambiables (§8.4.2), ordenados por ``resource_id`` dentro de cada clase."""
    prep = ctx.prep
    sig: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for b in ctx.sub.blocks:
        blk = prep.block(b)
        cands = tuple(
            sorted(
                (prep.pair_entry[p], (prep.pair_p[p] or -1.0) if with_p else 0.0)
                for p in ctx.pairs_by_block[b]
            )
        )
        key = (
            blk.specialty_code,
            blk.resource_kind,
            blk.start_at,
            prep.capacity[b],
            prep.overbook_max[b],
            with_p and b in ctx.eligible,
            cands,
        )
        sig[key].append(b)
    classes = [sorted(bs, key=lambda b: prep.block(b).resource_id) for bs in sig.values()]
    return sorted((c for c in classes if len(c) >= 2), key=lambda c: c[0])


def _entry_classes(
    ctx: SubContext, by_patient: Mapping[str, list[int]], with_p: bool
) -> list[list[int]]:
    """Entradas idénticas (§8.4.3), ordenadas por puesto P4 dentro de cada clase."""
    prep = ctx.prep
    sig: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for i in ctx.sub.entries:
        e = prep.entry(i)
        if len(by_patient[e.patient_id]) != 1:
            continue
        pairs = tuple(
            (
                prep.pair_block[p],
                prep.pair_coef[p],
                (prep.pair_p[p] or -1.0) if with_p else 0.0,
                prep.pair_load(p),
            )
            for p in ctx.pairs_by_entry.get(i, [])
        )
        key = (
            prep.queue[i],
            prep.s[i],
            e.duration_min,
            e.clinical_priority,
            prep.obligation.get(i) if ctx.sub.is_obligated(prep, i) else None,
            e.ges_deadline,
            prep.ges_presolve.get(i),
            ctx.entry_groups[i],
            pairs,
        )
        sig[key].append(i)
    classes = [
        sorted(c, key=lambda i: (prep.entry(i).rank, prep.entry(i).entry_id)) for c in sig.values()
    ]
    return sorted((c for c in classes if len(c) >= 2), key=lambda c: c[0])


# ------------------------------------------------------------------ evaluación de soluciones


def block_loads(prep: Prepared, solution: frozenset[int]) -> dict[int, int]:
    """Carga por bloque (unidades CNE o minutos de pabellón)."""
    loads: dict[int, int] = defaultdict(int)
    for p in solution:
        loads[prep.pair_block[p]] += prep.pair_load(p)
    return dict(loads)


def block_counts(prep: Prepared, solution: frozenset[int]) -> dict[int, int]:
    """Número de entradas por bloque."""
    counts: dict[int, int] = defaultdict(int)
    for p in solution:
        counts[prep.pair_block[p]] += 1
    return dict(counts)


def overbook_levels(prep: Prepared, solution: frozenset[int]) -> dict[int, int]:
    """Sobrecupos ``o_b = max(0, n_b - C_b)`` por bloque CNE."""
    out: dict[int, int] = {}
    for b, n in block_counts(prep, solution).items():
        if prep.block(b).is_cne and n > prep.capacity[b]:
            out[b] = n - prep.capacity[b]
    return out


def assigned_entries(prep: Prepared, solution: frozenset[int]) -> set[int]:
    """Entradas agendadas."""
    return {prep.pair_entry[p] for p in solution}


def unmet_ges(prep: Prepared, sub: Sub, solution: frozenset[int]) -> set[int]:
    """Garantías obligadas del subproblema que la solución no cumple (``v_g`` verdadero)."""
    out: set[int] = set()
    for g in sub.entries:
        if not sub.is_obligated(prep, g):
            continue
        ok = prep.ges_satisfying.get(g, [])
        if g in prep.ges_presolve or not any(p in solution for p in ok):
            out.add(g)
    return out


def coef_sum(prep: Prepared, solution: frozenset[int]) -> int:
    """``sum c_ib x_ib``."""
    return sum(prep.pair_coef[p] for p in solution)


def balance_value(ctx: SubContext, solution: frozenset[int]) -> int:
    """``BAL`` (§6.6): suma de (máx - mín) de utilización por grupo de bloques."""
    prep = ctx.prep
    loads = block_loads(prep, solution)
    total = 0
    for bs in ctx.balance_groups:
        utils = [UTIL_SCALE * loads.get(b, 0) // prep.capacity[b] for b in bs]
        total += max(utils) - min(utils)
    return total


def objective_value(ctx: SubContext, objective: Objective, solution: frozenset[int]) -> int:
    """Valor del objetivo de una fase evaluado sobre una solución."""
    prep = ctx.prep
    if objective == "q1":
        return len(assigned_entries(prep, solution) & prep.q1)
    if objective == "ges":
        return len(unmet_ges(prep, ctx.sub, solution))
    if objective == "score":
        return coef_sum(prep, solution)
    return balance_value(ctx, solution)


def satisfies(ctx: SubContext, spec: PhaseSpec, solution: frozenset[int]) -> bool:
    """La solución (sin sobrecupo) cumple las fijaciones de ``spec``."""
    prep = ctx.prep
    fix = spec.fix
    assigned = assigned_entries(prep, solution)
    if overbook_levels(prep, solution) and not spec.overbooking:
        return False
    if fix.q1_min is not None and len(assigned & prep.q1) < fix.q1_min:
        return False
    if fix.v_max is not None and len(unmet_ges(prep, ctx.sub, solution)) > fix.v_max:
        return False
    if fix.s0 is not None and not fix.s0 <= assigned:
        return False
    if fix.coef_min is not None and coef_sum(prep, solution) < fix.coef_min:
        return False
    return not fix.overbook_levels


def canonicalize(ctx: SubContext, solution: frozenset[int], overbooking: bool) -> frozenset[int]:
    """Lleva una solución a la forma que exigen las restricciones de simetría (§8.4)."""
    prep = ctx.prep
    chosen = set(solution)
    pair_of: dict[tuple[int, int], int] = {
        (prep.pair_entry[p], prep.pair_block[p]): p for p in ctx.sub.pairs
    }
    entry_block = {prep.pair_entry[p]: prep.pair_block[p] for p in chosen}
    for cls in ctx.entry_classes[overbooking]:
        taken = [entry_block[i] for i in cls if i in entry_block]
        for i in cls:
            if i in entry_block:
                chosen.discard(pair_of[(i, entry_block.pop(i))])
        for i, b in zip(cls, taken, strict=False):
            chosen.add(pair_of[(i, b)])
            entry_block[i] = b
    for cls in ctx.block_classes[overbooking]:
        contents = [[i for i, b in entry_block.items() if b == blk] for blk in cls]
        for i_list in contents:
            for i in i_list:
                chosen.discard(pair_of[(i, entry_block[i])])

        def load(es: list[int], b0: int = cls[0]) -> int:
            return sum(prep.pair_load(pair_of[(i, b0)]) for i in es)

        contents.sort(key=lambda es: (-load(es), sorted(prep.entry(i).entry_id for i in es)))
        for blk, i_list in zip(cls, contents, strict=True):
            for i in i_list:
                chosen.add(pair_of[(i, blk)])
                entry_block[i] = blk
    return frozenset(chosen)


# ------------------------------------------------------------------ modelo


class SubModel:
    """Modelo CP-SAT de un subproblema para una fase."""

    def __init__(self, ctx: SubContext, spec: PhaseSpec) -> None:
        prep = ctx.prep
        cfg = prep.config
        sub = ctx.sub
        m = cp_model.CpModel()
        self.model = m
        self.ctx = ctx
        self.spec = spec
        self.x = {p: m.new_bool_var(f"x_{p}") for p in sub.pairs}
        x = self.x
        self.w_vars: list[tuple[cp_model.IntVar, int, list[int]]] = []  # (w, bloque, pares)
        self.util_vars: list[
            tuple[list[tuple[cp_model.IntVar, int]], cp_model.IntVar, cp_model.IntVar]
        ] = []
        fix = spec.fix

        # R1: a lo más un bloque por entrada.
        self.a: dict[int, cp_model.LinearExprT] = {}
        for i in sub.entries:
            ps = ctx.pairs_by_entry.get(i, [])
            if len(ps) > 1:
                m.add_at_most_one(x[p] for p in ps)
            self.a[i] = sum(x[p] for p in ps)

        # R2, R3 y sobrecupo (R7-R11, R13).
        self.k: dict[int, list[cp_model.IntVar]] = {}
        s0 = fix.s0 or frozenset()
        for b in sub.blocks:
            ps = ctx.pairs_by_block[b]
            load = sum(prep.pair_load(p) * x[p] for p in ps)
            cap = prep.capacity[b]
            if spec.overbooking and b in ctx.eligible:
                omax = prep.overbook_max[b]
                ks = [m.new_bool_var(f"k_{b}_{o}") for o in range(omax + 1)]
                self.k[b] = ks
                m.add_exactly_one(ks)
                m.add(load <= cap + sum(o * ks[o] for o in range(1, omax + 1)))
                count = sum(x[p] for p in ps)
                probs = [prep.pair_p[p] or 0.0 for p in ps]
                alpha = cfg.overbooking.alpha
                for o in range(1, omax + 1):
                    m.add(count == cap + o).only_enforce_if(ks[o])
                    if o == 1:
                        expr = sum(coef_one(pr) * x[p] for p, pr in zip(ps, probs, strict=True))
                        m.add(expr >= rhs_one(alpha)).only_enforce_if(ks[o])
                    else:
                        theta = chernoff_theta(ctx.eligible[b], cap, o)
                        if theta is None:
                            m.add(ks[o] == 0)
                            continue
                        expr = sum(
                            coef_theta(pr, theta) * x[p] for p, pr in zip(ps, probs, strict=True)
                        )
                        m.add(expr >= rhs_theta(theta, o, alpha)).only_enforce_if(ks[o])
                added = sum(x[p] for p in ps if prep.pair_entry[p] not in s0)
                m.add(added >= sum(o * ks[o] for o in range(1, omax + 1)))
                if fix.overbook_levels is not None:
                    m.add(ks[fix.overbook_levels.get(b, 0)] == 1)
            else:
                m.add(load <= cap)

        # R4: una cita por paciente por día.
        for ps in ctx.patient_day_pairs:
            m.add_at_most_one(x[p] for p in ps)

        # R5, R6: GES con holgura v_g.
        self.v: dict[int, cp_model.IntVar] = {}
        for g in sub.entries:
            if not sub.is_obligated(prep, g):
                continue
            v = m.new_bool_var(f"v_{g}")
            self.v[g] = v
            if g in prep.ges_presolve:
                m.add(v == 1)
            else:
                ok = [p for p in prep.ges_satisfying.get(g, []) if p in x]
                m.add(sum(x[p] for p in ok) + v >= 1)

        # Fijaciones de fases anteriores.
        if fix.q1_min is not None:
            m.add(sum(self.a[i] for i in sub.entries if i in prep.q1) >= fix.q1_min)
        if fix.v_max is not None:
            m.add(sum(self.v.values()) <= fix.v_max)
        for i in sorted(s0):
            m.add(self.a[i] == 1)
        self.coef_expr = sum(prep.pair_coef[p] * x[p] for p in sub.pairs)
        if fix.coef_min is not None:
            m.add(self.coef_expr >= fix.coef_min)

        # R14, R15: límites por grupo.
        if spec.group_caps:
            self._group_limits(spec.group_caps)

        # Simetrías (§8.4).
        for cls in ctx.block_classes[spec.overbooking]:
            loads = [sum(prep.pair_load(p) * x[p] for p in ctx.pairs_by_block[b]) for b in cls]
            for hi, lo in pairwise(loads):
                m.add(hi >= lo)
        for cls in ctx.entry_classes[spec.overbooking]:
            for i, j in pairwise(cls):
                m.add(self.a[i] >= self.a[j])

        # Objetivo de la fase.
        if spec.objective == "q1":
            m.maximize(sum(self.a[i] for i in sub.entries if i in prep.q1))
        elif spec.objective == "ges":
            m.minimize(sum(self.v.values()))
        elif spec.objective == "score":
            m.maximize(self.coef_expr)
        else:
            m.minimize(self._balance_expr())

    def _group_limits(self, caps: Mapping[GroupKey, float]) -> None:
        ctx = self.ctx
        prep = ctx.prep
        m = self.model
        x = self.x
        cne_blocks = [b for b in ctx.sub.blocks if prep.block(b).is_cne]
        for q, rho in sorted(caps.items()):
            members = {i for i in ctx.sub.entries if q in ctx.entry_groups.get(i, ())}
            total_e: list[cp_model.LinearExprT] = []
            ws: list[cp_model.IntVar] = []
            for b in cne_blocks:
                ps = [p for p in ctx.pairs_by_block[b] if prep.pair_entry[p] in members]
                if not ps:
                    continue
                e_qb = sum(x[p] for p in ps)
                total_e.append(e_qb)
                if b in self.k:
                    big_m = prep.capacity[b] + prep.overbook_max[b]
                    w = m.new_int_var(0, big_m, f"w_{q[0]}_{q[1]}_{b}")
                    m.add(w >= e_qb - big_m * self.k[b][0])
                    ws.append(w)
                    self.w_vars.append((w, b, ps))
            if ws:
                m.add(UTIL_SCALE * sum(ws) <= round_half_up(UTIL_SCALE * rho) * sum(total_e))

    def _balance_expr(self) -> cp_model.LinearExprT:
        ctx = self.ctx
        prep = ctx.prep
        m = self.model
        terms: list[cp_model.LinearExprT] = []
        for gi, bs in enumerate(ctx.balance_groups):
            utils: list[cp_model.IntVar] = []
            util_blocks: list[tuple[cp_model.IntVar, int]] = []
            top = 0
            for b in bs:
                cap = prep.capacity[b]
                load = sum(prep.pair_load(p) * self.x[p] for p in ctx.pairs_by_block[b])
                ub = UTIL_SCALE * (cap + prep.overbook_max[b]) // cap
                top = max(top, ub)
                u = m.new_int_var(0, ub, f"util_{b}")
                m.add(cap * u <= UTIL_SCALE * load)
                m.add(UTIL_SCALE * load <= cap * u + cap - 1)
                utils.append(u)
                util_blocks.append((u, b))
            hi = m.new_int_var(0, top, f"max_{gi}")
            lo = m.new_int_var(0, top, f"min_{gi}")
            m.add_max_equality(hi, utils)
            m.add_min_equality(lo, utils)
            self.util_vars.append((util_blocks, hi, lo))
            terms.append(hi - lo)
        return sum(terms)

    def add_hint(self, solution: frozenset[int]) -> None:
        """Pista completa para ``x``, ``v`` y ``k`` a partir de una solución."""
        prep = self.ctx.prep
        for p, var in self.x.items():
            self.model.add_hint(var, p in solution)
        unmet = unmet_ges(prep, self.ctx.sub, solution)
        for g, var in self.v.items():
            self.model.add_hint(var, g in unmet)
        levels = overbook_levels(prep, solution)
        for b, ks in self.k.items():
            lvl = levels.get(b, 0)
            for o, var in enumerate(ks):
                self.model.add_hint(var, o == lvl)
        for w, b, ps in self.w_vars:
            exposed = sum(1 for p in ps if p in solution) if levels.get(b, 0) > 0 else 0
            self.model.add_hint(w, exposed)
        loads = block_loads(prep, solution)
        for util_blocks, hi, lo in self.util_vars:
            values = []
            for u, b in util_blocks:
                val = UTIL_SCALE * loads.get(b, 0) // prep.capacity[b]
                self.model.add_hint(u, val)
                values.append(val)
            self.model.add_hint(hi, max(values))
            self.model.add_hint(lo, min(values))

    def extract(self, solver: cp_model.CpSolver) -> frozenset[int]:
        """Pares elegidos en la solución del solver."""
        return frozenset(p for p, var in self.x.items() if solver.boolean_value(var))


def solve_phase(
    ctx: SubContext,
    spec: PhaseSpec,
    hint: frozenset[int],
    hint_source: str,
    budget: float,
    seed: int,
) -> PhaseOutcome:
    """Construye, resuelve y evalúa una fase; nunca devuelve sin solución."""
    cfg: SchedulerConfig = ctx.prep.config
    sm = SubModel(ctx, spec)
    sm.add_hint(hint)
    solver = cp_model.CpSolver()
    params = solver.parameters
    params.random_seed = seed
    params.linearization_level = cfg.solver.linearization_level
    params.log_search_progress = cfg.solver.log_search_progress
    if cfg.solver.deterministic:
        # Búsqueda secuencial: determinista y, medido en la corrida canónica, más rápida que
        # interleave_search (que excede su límite determinista por lotes). Ver decisions.md.
        params.num_workers = 1
        params.max_deterministic_time = budget
    else:
        params.num_workers = cfg.solver.num_workers
        params.max_time_in_seconds = budget
    if spec.objective == "score":
        params.relative_gap_limit = cfg.solver.relative_gap_limit
    status = solver.solve(sm.model)
    name = solver.status_name(status)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution = sm.extract(solver)
        bound: float | None = solver.best_objective_bound
    elif status == cp_model.UNKNOWN:
        solution = hint
        bound = None
    else:
        raise RuntimeError(
            f"fase {spec.name} del subproblema {ctx.sub.label}: CP-SAT devolvió {name}; "
            f"todo lo duro tiene holgura o lo cumple la pista, así que es un error de "
            f"implementación. validate()={sm.model.validate()!r}"
        )
    value = float(objective_value(ctx, spec.objective, solution))
    gap = None if bound is None else abs(value - bound) / max(1.0, abs(value))
    proto = sm.model.proto
    return PhaseOutcome(
        name=spec.name,
        status=name,
        objective=value,
        bound=bound,
        gap=gap,
        wall_time_s=solver.wall_time,
        deterministic_time=solver.deterministic_time,
        budget=budget,
        num_variables=len(proto.variables),
        num_constraints=len(proto.constraints),
        solution=solution,
        hint_source=hint_source,
    )
