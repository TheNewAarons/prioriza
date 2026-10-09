"""Preprocesamiento: compatibilidad, coeficientes, causas GES previas, filtro y componentes.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Implementa las secciones 3, 4, 6.6 (coeficientes), 7 (causas antes de resolver), 8.2 y 8.3
de ``docs/scheduler-formulation.md``. Los índices de entradas y bloques son posiciones en
``instance.entries`` e ``instance.blocks``; los pares se guardan en listas paralelas.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from scheduler.config import SchedulerConfig
from scheduler.instance import KIND_FOR_CARE, Block, Entry, SchedulingInstance

QueueKey = tuple[str, str]  # (clave de lugar, especialidad)
Obligation = Literal["overdue", "deadline"]

# Causas de la formulación §7 que se determinan antes de resolver.
NO_BLOCK_IN_HORIZON = "no_block_in_horizon"
DURATION_EXCEEDS_BLOCKS = "duration_exceeds_blocks"
DEADLINE_BEFORE_FIRST_BLOCK = "deadline_before_first_block"
LEAD_TIME = "lead_time"


def round_half_up(x: float) -> int:
    """Redondeo aritmético (``round`` de Python redondea al par)."""
    return math.floor(x + 0.5)


def score_units(score: float) -> int:
    """``s_i = round(100·S_i) + 100`` (formulación §3)."""
    return round_half_up(100.0 * score) + 100


@dataclass
class Prepared:
    """Datos derivados de la instancia y la configuración, comunes a todas las fases."""

    instance: SchedulingInstance
    config: SchedulerConfig
    horizon_end: date
    horizon_days: int
    s: list[int]
    queue: list[QueueKey]
    obligation: dict[int, Obligation]
    q1: frozenset[int]
    block_in_horizon: list[bool]
    capacity: list[int]  # C_b (CNE) o L_b (pabellón), residual
    overbook_max: list[int]  # O_b
    # Pares compatibles (listas paralelas).
    pair_entry: list[int]
    pair_block: list[int]
    pair_coef: list[int]
    pair_early: list[int]
    pair_delay_days: list[int]
    pair_p: list[float | None]
    pairs_of_entry: dict[int, list[int]]
    first_date: dict[int, date]
    no_pair_reason: dict[int, str]
    ges_presolve: dict[int, str]  # g -> causa que fija v_g = 1
    ges_satisfying: dict[int, list[int]]  # g -> pares que cumplen su obligación (R5/R6)
    queue_blocks: dict[QueueKey, list[int]]
    queue_min_duration: dict[QueueKey, int]
    candidates: frozenset[int] = frozenset()
    filtered_out: dict[int, tuple[QueueKey, int]] = field(default_factory=dict)
    frontier_tail: dict[QueueKey, frozenset[int]] = field(default_factory=dict)
    queue_cutoff: dict[QueueKey, int] = field(default_factory=dict)

    def pair_coef_delay(self, pid: int) -> int:
        """Término de atraso GES ``delay_ib`` del coeficiente del par (§6.6)."""
        w = self.config.weights.ges_delay_points_per_day
        return round_half_up(100.0 * w * self.pair_delay_days[pid])

    def entry(self, i: int) -> Entry:
        """Entrada por índice."""
        return self.instance.entries[i]

    def block(self, b: int) -> Block:
        """Bloque por índice."""
        return self.instance.blocks[b]

    def pair_load(self, pid: int) -> int:
        """Carga del par en su bloque: unidades CNE ``u_i`` o minutos ``d + τ`` en pabellón."""
        return entry_load(
            self.config, self.entry(self.pair_entry[pid]), self.block(self.pair_block[pid])
        )


def entry_load(config: SchedulerConfig, e: Entry, b: Block) -> int:
    """Unidades CNE ``ceil(d / unit_min)`` o minutos de pabellón ``d + τ`` de ``e`` en ``b``."""
    if b.is_cne:
        assert b.unit_min is not None
        return math.ceil(e.duration_min / b.unit_min)
    return e.duration_min + config.or_turnover_min


def place_key(config: SchedulerConfig, service: int, establishment: str) -> str:
    """Clave de lugar según ``config.match_level`` (formulación §4.2)."""
    if config.match_level == "health_service":
        return f"s:{service}"
    return f"e:{establishment}"


def prepare(instance: SchedulingInstance, config: SchedulerConfig) -> Prepared:
    """Calcula compatibilidad, coeficientes y causas previas; no aplica el filtro."""
    hs = instance.horizon_start
    he = hs + timedelta(days=7 * config.horizon_weeks)
    days = 7 * config.horizon_weeks
    entries = instance.entries
    blocks = instance.blocks
    ob = config.overbooking

    in_horizon = [hs <= b.local_date < he for b in blocks]
    capacity: list[int] = []
    overbook_max: list[int] = []
    for b in blocks:
        if b.is_cne:
            assert b.unit_min is not None
            cap = b.duration_min // b.unit_min - b.prebooked_units
            omax = math.floor(ob.max_fraction * cap) if ob.enabled and cap > 0 else 0
        else:
            cap = math.floor(config.or_max_fill * b.duration_min) - b.prebooked_min
            omax = 0
        if cap < 0:
            raise ValueError(f"capacidad residual negativa en el bloque {b.slot_id}: {cap}")
        capacity.append(cap)
        overbook_max.append(omax)

    queue_blocks: dict[QueueKey, list[int]] = defaultdict(list)
    for bi, b in enumerate(blocks):
        if in_horizon[bi]:
            queue_blocks[
                (place_key(config, b.health_service_code, b.establishment_code), b.specialty_code)
            ].append(bi)
    for lst in queue_blocks.values():
        lst.sort(key=lambda bi: (blocks[bi].local_date, blocks[bi].start_at, blocks[bi].slot_id))

    s = [score_units(e.score) for e in entries]
    queue = [
        (place_key(config, e.health_service_code, e.establishment_code), e.specialty_code)
        for e in entries
    ]
    obligation: dict[int, Obligation] = {}
    for i, e in enumerate(entries):
        if e.is_ges and e.ges_deadline is not None and e.ges_deadline < he:
            obligation[i] = "overdue" if e.ges_deadline < hs else "deadline"
    q1 = frozenset(
        i for i, e in enumerate(entries) if e.clinical_priority in instance.yield_priorities
    )

    pair_entry: list[int] = []
    pair_block: list[int] = []
    pairs_of_entry: dict[int, list[int]] = {}
    first_date: dict[int, date] = {}
    no_pair_reason: dict[int, str] = {}
    ges_presolve: dict[int, str] = {}
    ges_satisfying: dict[int, list[int]] = {}
    queue_min_duration: dict[QueueKey, int] = {}
    for i, e in enumerate(entries):
        q = queue[i]
        queue_min_duration[q] = min(queue_min_duration.get(q, e.duration_min), e.duration_min)

    for i, e in enumerate(entries):
        b0 = queue_blocks.get(queue[i], [])
        kind = KIND_FOR_CARE[e.care_type]
        for bi in b0:
            if blocks[bi].resource_kind != kind:
                raise ValueError(
                    f"dato corrupto: bloque {blocks[bi].slot_id} ({blocks[bi].resource_kind}) "
                    f"de la especialidad {e.specialty_code} no corresponde a {e.care_type}"
                )
        if not b0:
            no_pair_reason[i] = NO_BLOCK_IN_HORIZON
            if i in obligation:
                ges_presolve[i] = NO_BLOCK_IN_HORIZON
            continue
        b1 = [bi for bi in b0 if entry_load(config, e, blocks[bi]) <= capacity[bi]]
        if not b1:
            no_pair_reason[i] = DURATION_EXCEEDS_BLOCKS
            if i in obligation:
                ges_presolve[i] = DURATION_EXCEEDS_BLOCKS
            continue
        lead = config.ges_min_lead_days if i in obligation else config.min_lead_days
        earliest = instance.as_of + timedelta(days=lead)
        b2 = [bi for bi in b1 if blocks[bi].local_date >= earliest]
        if i in obligation:
            deadline = e.ges_deadline
            assert deadline is not None
            if obligation[i] == "deadline":
                b1_dl = [bi for bi in b1 if blocks[bi].local_date <= deadline]
                if not b1_dl:
                    ges_presolve[i] = DEADLINE_BEFORE_FIRST_BLOCK
                elif not any(blocks[bi].local_date >= earliest for bi in b1_dl):
                    ges_presolve[i] = LEAD_TIME
            elif deadline >= instance.as_of:
                # Vence entre la fecha de decisión y el inicio del horizonte: ningún bloque
                # puede cumplir el plazo (§6.2 y §7).
                ges_presolve[i] = DEADLINE_BEFORE_FIRST_BLOCK
            elif not b2:
                ges_presolve[i] = LEAD_TIME
        if not b2:
            no_pair_reason[i] = LEAD_TIME
            continue
        first_date[i] = blocks[b2[0]].local_date
        pids: list[int] = []
        for bi in b2:
            pids.append(len(pair_entry))
            pair_entry.append(i)
            pair_block.append(bi)
        pairs_of_entry[i] = pids

    w_delay = config.weights.ges_delay_points_per_day
    e_w = config.weights.earliness
    pair_coef: list[int] = []
    pair_early: list[int] = []
    pair_delay_days: list[int] = []
    pair_p: list[float | None] = []
    for pid, (i, bi) in enumerate(zip(pair_entry, pair_block, strict=True)):
        blk = blocks[bi]
        e = entries[i]
        day = (blk.local_date - hs).days
        early = round_half_up(s[i] * e_w * day / days)
        delay_days = 0
        if i in obligation:
            assert e.ges_deadline is not None
            ref = max(e.ges_deadline, first_date[i])
            delay_days = max(0, (blk.local_date - ref).days)
        delay = round_half_up(100.0 * w_delay * delay_days)
        pair_coef.append(max(1, s[i] - early - delay))
        pair_early.append(early)
        pair_delay_days.append(delay_days)
        raw = instance.noshow.get((e.entry_id, blk.slot_id))
        if raw is None:
            if blk.is_cne and ob.enabled:
                raise ValueError(
                    f"falta p de inasistencia para el par ({e.entry_id}, {blk.slot_id}) "
                    "con sobreagendamiento activo"
                )
            pair_p.append(None)
        else:
            pair_p.append(min(ob.p_clip_high, max(ob.p_clip_low, raw)))
        if i in obligation and i not in ges_presolve:
            deadline = e.ges_deadline
            assert deadline is not None
            if obligation[i] == "overdue" or blk.local_date <= deadline:
                ges_satisfying.setdefault(i, []).append(pid)

    return Prepared(
        instance=instance,
        config=config,
        horizon_end=he,
        horizon_days=days,
        s=s,
        queue=queue,
        obligation=obligation,
        q1=q1,
        block_in_horizon=in_horizon,
        capacity=capacity,
        overbook_max=overbook_max,
        pair_entry=pair_entry,
        pair_block=pair_block,
        pair_coef=pair_coef,
        pair_early=pair_early,
        pair_delay_days=pair_delay_days,
        pair_p=pair_p,
        pairs_of_entry=pairs_of_entry,
        first_date=first_date,
        no_pair_reason=no_pair_reason,
        ges_presolve=ges_presolve,
        ges_satisfying=ges_satisfying,
        queue_blocks=dict(queue_blocks),
        queue_min_duration=queue_min_duration,
    )


def queue_bound(prep: Prepared, q: QueueKey) -> int:
    """``K_q`` de la formulación §8.2: cota de casos que caben en la cola."""
    total = 0
    d_min = prep.queue_min_duration.get(q, 1)
    for bi in prep.queue_blocks.get(q, []):
        if prep.block(bi).is_cne:
            # O_b nominal aunque el sobrecupo esté apagado: así el filtro (y las fases 1-3a)
            # no dependen de si hay sobreagendamiento.
            cap = prep.capacity[bi]
            total += cap + math.floor(prep.config.overbooking.max_fraction * cap)
        else:
            total += prep.capacity[bi] // (d_min + prep.config.or_turnover_min)
    return total


def select_candidates(
    prep: Prepared, margin: float, margins: dict[QueueKey, float] | None = None
) -> None:
    """Aplica el filtro §8.2 y registra candidatos, descartados y la cola de frontera."""
    by_queue: dict[QueueKey, list[int]] = defaultdict(list)
    for i in prep.pairs_of_entry:
        by_queue[prep.queue[i]].append(i)
    candidates: set[int] = set()
    filtered: dict[int, tuple[QueueKey, int]] = {}
    tail: dict[QueueKey, frozenset[int]] = {}
    cutoff: dict[QueueKey, int] = {}
    entries = prep.instance.entries
    for q, members in by_queue.items():
        members.sort(key=lambda i: (entries[i].rank, entries[i].entry_id))
        m = (margins or {}).get(q, margin)
        n_keep = math.ceil(m * queue_bound(prep, q))
        top = members[:n_keep]
        cutoff[q] = n_keep
        candidates.update(top)
        for i in members[n_keep:]:
            if i in prep.obligation:
                candidates.add(i)
            else:
                filtered[i] = (q, n_keep)
        if len(top) < len(members):
            # Último 10 % de los candidatos por puesto, con al menos uno.
            start = len(top) - max(1, math.ceil(0.1 * len(top)))
            tail[q] = frozenset(top[start:])
    prep.candidates = frozenset(candidates)
    prep.filtered_out = filtered
    prep.frontier_tail = tail
    prep.queue_cutoff = cutoff


class _UnionFind:
    def __init__(self, items: Iterable[int]) -> None:
        self.parent = {x: x for x in items}

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def components(prep: Prepared, entries: Iterable[int]) -> list[list[int]]:
    """Componentes conexas (§8.3): entradas unidas por paciente o por bloque compatible.

    Devuelve listas de índices de entradas ordenadas, en orden determinista (por la menor
    cola y el menor índice de cada componente).
    """
    members = sorted(entries)
    uf = _UnionFind(members)
    by_patient: dict[str, int] = {}
    by_block: dict[int, int] = {}
    for i in members:
        pid = prep.entry(i).patient_id
        if pid in by_patient:
            uf.union(by_patient[pid], i)
        else:
            by_patient[pid] = i
        for p in prep.pairs_of_entry.get(i, []):
            bi = prep.pair_block[p]
            if bi in by_block:
                uf.union(by_block[bi], i)
            else:
                by_block[bi] = i
    groups: dict[int, list[int]] = defaultdict(list)
    for i in members:
        groups[uf.find(i)].append(i)
    comps = list(groups.values())
    comps.sort(key=lambda c: (min(prep.queue[i] for i in c), c[0]))
    return comps
