"""Cálculo del puntaje de prioridad, nivel estricto GES y ranking.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Fórmula: ``S = sum_i (100 * w_i / sum_j w_j) * v_i`` con ``v_i`` en [0, 1], por lo que
``S`` queda en [0, 100]. La prioridad clínica es un dato de entrada: se refleja sin
modificarla. ``as_of`` es siempre explícito (nunca se usa la fecha del sistema).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum

from shared.db.enums import ClinicalPriority
from shared.disclaimer import DISCLAIMER

from priority.inputs import PriorityInput
from priority.rules import (
    ClinicalPriorityComponent,
    GesDeadlineComponent,
    GesStrictRule,
    LinearSaturated,
    LogSaturated,
    RampDown,
    RuleSet,
    Steps,
    WaitDaysComponent,
    WaitTransform,
)

SortKey = tuple[int, int, int, int, int, str]


class StrictTier(IntEnum):
    """Nivel estricto GES: mayor valor, antes en la cola."""

    NONE = 0
    GES_DUE_SOON = 1
    GES_OVERDUE = 2


@dataclass(frozen=True, slots=True)
class ComponentContribution:
    """Aporte de un componente al puntaje (para explicabilidad)."""

    field: str
    label: str
    raw_value: str | int | None
    transform_desc: str
    normalized: float
    weight: float
    effective_weight: float
    contribution: float


@dataclass(frozen=True, slots=True)
class PriorityScore:
    """Puntaje de una entrada con su desglose."""

    entry_id: str
    as_of: date
    clinical_priority: ClinicalPriority  # eco sin modificar de la entrada
    wait_days: int
    days_to_ges_deadline: int | None
    tier: StrictTier
    score: float
    components: tuple[ComponentContribution, ...]
    rules_digest: str = ""  # reglas con que se calculó; explain verifica que coincidan


@dataclass(frozen=True, slots=True)
class RankedEntry:
    """Entrada con su puesto (parte en 1)."""

    rank: int
    score: PriorityScore


@dataclass(frozen=True, slots=True)
class Ranking:
    """Resultado ordenado de ``rank`` con la identidad de las reglas usadas."""

    as_of: date
    rules_id: str
    rules_version: str
    rules_digest: str
    entries: tuple[RankedEntry, ...]
    disclaimer: str
    _index: dict[str, int] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        """Construye el índice id -> posición."""
        index = {e.score.entry_id: i for i, e in enumerate(self.entries)}
        object.__setattr__(self, "_index", index)

    def get(self, entry_id: str) -> RankedEntry:
        """Devuelve la entrada por id; ``KeyError`` si no está."""
        return self.entries[self._index[entry_id]]


def strict_tier(days_to_deadline: int | None, rule: GesStrictRule) -> StrictTier:
    """Nivel estricto según los días al plazo GES (``None`` si no es GES)."""
    if not rule.enabled or days_to_deadline is None:
        return StrictTier.NONE
    if days_to_deadline < 0:
        return StrictTier.GES_OVERDUE
    if days_to_deadline <= rule.due_soon_days:
        return StrictTier.GES_DUE_SOON
    return StrictTier.NONE


def _normalize_wait(t: WaitTransform, wait_days: int) -> float:
    if isinstance(t, LinearSaturated):
        return min(wait_days, t.saturation_days) / t.saturation_days
    if isinstance(t, LogSaturated):
        return min(1.0, math.log1p(wait_days) / math.log1p(t.saturation_days))
    value = 0.0
    for step in t.steps:
        if wait_days >= step.at_days:
            value = step.value
    return value


def _normalize_ramp(t: RampDown, d: int | None) -> float:
    if d is None:
        return 0.0
    return min(1.0, max(0.0, (t.start_days - d) / (t.start_days - t.end_days)))


def _wait_desc(t: WaitTransform) -> str:
    if isinstance(t, LinearSaturated):
        return f"lineal saturada en {t.saturation_days} días"
    if isinstance(t, LogSaturated):
        return f"logarítmica saturada en {t.saturation_days} días"
    assert isinstance(t, Steps)
    return "escalones por días de espera"


def _ramp_desc(t: RampDown) -> str:
    return f"rampa descendente de {t.start_days} a {t.end_days} días al plazo"


def _score(
    inp: PriorityInput, rules: RuleSet, as_of: date, total_weight: float, digest: str
) -> PriorityScore:
    wait = (as_of - inp.entry_date).days
    if wait < 0:
        raise ValueError(
            f"entrada {inp.entry_id}: la fecha de ingreso ({inp.entry_date}) es posterior "
            f"a as_of ({as_of})"
        )
    d = None if inp.ges_deadline is None else (inp.ges_deadline - as_of).days
    contribs: list[ComponentContribution] = []
    for c in rules.components:
        raw: str | int | None
        if isinstance(c, ClinicalPriorityComponent):
            raw = inp.clinical_priority.value
            norm = c.mapping[inp.clinical_priority]
            desc = "escalón fijo por prioridad declarada"
        elif isinstance(c, WaitDaysComponent):
            raw = wait
            norm = _normalize_wait(c.transform, wait)
            desc = _wait_desc(c.transform)
        else:
            assert isinstance(c, GesDeadlineComponent)
            raw = d
            norm = _normalize_ramp(c.transform, d)
            desc = _ramp_desc(c.transform)
        eff = 100.0 * c.weight / total_weight
        # Cada aporte se redondea a 6 decimales para que sum(aportes) == puntaje.
        contribs.append(
            ComponentContribution(
                field=c.field,
                label=c.label,
                raw_value=raw,
                transform_desc=desc,
                normalized=norm,
                weight=c.weight,
                effective_weight=eff,
                contribution=round(eff * norm, 6),
            )
        )
    s = round(math.fsum(x.contribution for x in contribs), 6)
    s = min(100.0, max(0.0, s))
    return PriorityScore(
        entry_id=inp.entry_id,
        as_of=as_of,
        clinical_priority=inp.clinical_priority,
        wait_days=wait,
        days_to_ges_deadline=d,
        tier=strict_tier(d, rules.ges_strict),
        score=s,
        components=tuple(contribs),
        rules_digest=digest,
    )


def _total_weight(rules: RuleSet) -> float:
    return math.fsum(c.weight for c in rules.components)


def score_entry(inp: PriorityInput, rules: RuleSet, *, as_of: date) -> PriorityScore:
    """Puntaje de una entrada. ``ValueError`` si ``entry_date > as_of``."""
    return _score(inp, rules, as_of, _total_weight(rules), rules.digest())


def sort_key(s: PriorityScore, inp: PriorityInput, rules: RuleSet) -> SortKey:
    """Clave de orden total ascendente (sin empates porque ``entry_id`` es único).

    ``(-cede, -nivel, plazo, -round(S*1e6), ordinal(entry_date), entry_id)`` donde ``cede``
    vale 1 si la regla estricta está activa y la prioridad está en ``yield_to_priorities``,
    y ``plazo`` son los días al plazo GES solo si hay nivel y ``order_within == "deadline"``.
    """
    rule = rules.ges_strict
    yields = 1 if rule.enabled and s.clinical_priority in rule.yield_to_priorities else 0
    d = s.days_to_ges_deadline
    d_key = (
        d if d is not None and s.tier > StrictTier.NONE and rule.order_within == "deadline" else 0
    )
    return (
        -yields,
        -int(s.tier),
        d_key,
        -round(s.score * 1_000_000),
        inp.entry_date.toordinal(),
        inp.entry_id,
    )


def rank(inputs: Iterable[PriorityInput], rules: RuleSet, *, as_of: date) -> Ranking:
    """Ordena las entradas de la más a la menos prioritaria. ``ValueError`` si hay ids repetidos."""
    total_w = _total_weight(rules)
    digest = rules.digest()
    seen: set[str] = set()
    keyed: list[tuple[SortKey, PriorityScore]] = []
    for inp in inputs:
        if inp.entry_id in seen:
            raise ValueError(f"entry_id duplicado: {inp.entry_id}")
        seen.add(inp.entry_id)
        sc = _score(inp, rules, as_of, total_w, digest)
        keyed.append((sort_key(sc, inp, rules), sc))
    keyed.sort(key=lambda kv: kv[0])
    entries = tuple(RankedEntry(rank=i, score=sc) for i, (_, sc) in enumerate(keyed, start=1))
    return Ranking(
        as_of=as_of,
        rules_id=rules.rules_id,
        rules_version=rules.rules_version,
        rules_digest=digest,
        entries=entries,
        disclaimer=DISCLAIMER,
    )
