"""Explicaciones en español de por qué una entrada tiene su puntaje y su puesto.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

El texto se genera solo cuando se pide; ``rank`` no arma textos. Los números usan coma
decimal y punto como separador de miles (formato es-CL).
"""

from dataclasses import dataclass
from datetime import timedelta

from priority.rules import LinearSaturated, LogSaturated, RuleSet, WaitDaysComponent
from priority.score import PriorityScore, Ranking, StrictTier


def _num(x: float, decimals: int = 2) -> str:
    return f"{x:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _weight(w: float) -> str:
    return _int(int(w)) if float(w).is_integer() else _num(w)


@dataclass(frozen=True, slots=True)
class Explanation:
    """Explicación estructurada de un puntaje."""

    entry_id: str
    rank: int | None
    total: int | None
    score: float
    tier: StrictTier
    tier_reason: str | None
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        """Texto completo, una línea por elemento."""
        return "\n".join(self.lines)


def _tier_reason(s: PriorityScore) -> str | None:
    d = s.days_to_ges_deadline
    if d is None or s.tier is StrictTier.NONE:
        return None
    deadline = s.as_of + timedelta(days=d)
    if s.tier is StrictTier.GES_OVERDUE:
        return f"garantía GES vencida (plazo {deadline.isoformat()}, {_int(-d)} días de atraso)"
    if d == 0:
        return f"garantía GES por vencer (plazo {deadline.isoformat()}, vence hoy)"
    return f"garantía GES por vencer (plazo {deadline.isoformat()}, vence en {_int(d)} días)"


def explain(
    s: PriorityScore, rules: RuleSet, *, rank: int | None = None, total: int | None = None
) -> Explanation:
    """Explica el puntaje de una entrada; ``rank`` y ``total`` son opcionales."""
    if s.rules_digest and s.rules_digest != rules.digest():
        raise ValueError(
            "las reglas dadas no son las que se usaron para calcular el puntaje (digest distinto)"
        )
    rule = rules.ges_strict
    lines: list[str] = []
    if rank is not None and total is not None:
        lines.append(f"Puesto {_int(rank)} de {_int(total)}.")
    elif rank is not None:
        lines.append(f"Puesto {_int(rank)}.")
    lines.append(f"Puntaje {_num(s.score)}/100.")

    saturated = False
    for comp, rc in zip(s.components, rules.components, strict=True):
        if comp.raw_value is None:
            lines.append(
                f"{comp.label}: no aplica = {_num(comp.normalized)} "
                f"× peso {_weight(comp.effective_weight)} = {_num(comp.contribution)}"  # noqa: RUF001
            )
            continue
        raw = _int(comp.raw_value) if isinstance(comp.raw_value, int) else comp.raw_value
        unit = " días" if isinstance(comp.raw_value, int) else ""
        lines.append(
            f"{comp.label}: {raw}{unit} → {comp.transform_desc} = {_num(comp.normalized)} "
            f"× peso {_weight(comp.effective_weight)} = {_num(comp.contribution)}"  # noqa: RUF001
        )
        if (
            isinstance(rc, WaitDaysComponent)
            and isinstance(rc.transform, (LinearSaturated, LogSaturated))
            and s.wait_days >= rc.transform.saturation_days
        ):
            saturated = True
    if saturated:
        lines.append(
            "Más espera no aumenta el puntaje; frente a otra entrada con igual puntaje, "
            "desempata la fecha de ingreso."
        )

    reason = _tier_reason(s)
    ylist = ", ".join(p.value for p in rule.yield_to_priorities)
    cedes = rule.enabled and s.clinical_priority in rule.yield_to_priorities
    if reason is not None:
        tail = "va antes que toda entrada sin nivel estricto"
        if rule.yield_to_priorities and not cedes:
            tail += f", salvo las de prioridad {ylist}"
        lines.append(f"Nivel estricto: {reason}. Por la regla `ges_strict` (activa) {tail}.")
    else:
        lines.append("Nivel estricto: ninguno.")
    if cedes:
        lines.append(
            f"Prioridad {s.clinical_priority.value}: por la regla `ges_strict.yield_to_priorities` "
            f"va antes que toda entrada de prioridad fuera de {ylist}, incluidas las GES vencidas."
        )
    return Explanation(
        entry_id=s.entry_id,
        rank=rank,
        total=total,
        score=s.score,
        tier=s.tier,
        tier_reason=reason,
        lines=tuple(lines),
    )


def explain_ranked(r: Ranking, entry_id: str, rules: RuleSet) -> Explanation:
    """Explica una entrada de un ``Ranking`` incluyendo su puesto."""
    if r.rules_digest != rules.digest():
        raise ValueError("las reglas dadas no son las del ranking (digest distinto)")
    e = r.get(entry_id)
    return explain(e.score, rules, rank=e.rank, total=len(r.entries))


def explanation_to_dict(e: Explanation) -> dict[str, object]:
    """Representación serializable para la API."""
    return {
        "entry_id": e.entry_id,
        "rank": e.rank,
        "total": e.total,
        "score": e.score,
        "tier": e.tier.name,
        "tier_reason": e.tier_reason,
        "lines": list(e.lines),
        "text": e.text,
    }
