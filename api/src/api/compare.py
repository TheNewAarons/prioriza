"""Comparación de dos planes de la misma corrida.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Funciones puras sobre el informe (`PlanRecord.report`) de cada plan. No se oculta nada: si el
plan B es peor en una métrica o en un grupo, `better` lo dice. Las diferencias son `b - a`.
"""

from __future__ import annotations

from typing import Any, Literal

from api.plans import PlanRecord
from api.schemas import CompareEquityOut, CompareMetricOut

Direction = Literal["higher_is_better", "lower_is_better", "neutral"]

HIGHER: Direction = "higher_is_better"
LOWER: Direction = "lower_is_better"
NEUTRAL: Direction = "neutral"

# (clave, rótulo, sección del informe, campo, dirección). Rótulos estables para el panel.
METRICS: tuple[tuple[str, str, str, str, Direction], ...] = (
    ("scheduled", "Citas agendadas", "summary", "scheduled", HIGHER),
    ("q1_scheduled", "Citas de máxima prioridad", "summary", "q1_scheduled", HIGHER),
    ("ges_met", "GES cumplidas", "ges", "met", HIGHER),
    ("ges_unmet", "GES no cumplidas", "ges", "unmet", LOWER),
    ("ges_on_time", "GES dentro de plazo", "ges", "on_time", HIGHER),
    ("overbooked_flags", "Citas en sobrecupo", "summary", "overbooked_flags", NEUTRAL),
    (
        "added_by_overbooking",
        "Agendadas gracias al sobrecupo",
        "summary",
        "added_by_overbooking",
        NEUTRAL,
    ),
    ("max_overflow_risk", "Riesgo máximo de desborde", "overbooking", "max_risk_exact", LOWER),
)

EQUITY_METRICS: tuple[tuple[str, str, Direction], ...] = (
    ("scheduled_rate", "Tasa de agendamiento", HIGHER),
    ("exposure_share", "Exposición al sobrecupo", LOWER),
    ("flagged_share", "Citas en sobrecupo", LOWER),
)

_TOL = 1e-9


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def verdict(
    a: float | None, b: float | None, direction: Direction
) -> Literal["a", "b", "tie", "none"]:
    """Qué plan es mejor según la dirección; `none` si no hay dato o la métrica es neutra."""
    if a is None or b is None or direction == NEUTRAL:
        return "none"
    if abs(b - a) <= _TOL:
        return "tie"
    b_higher = b > a
    return "b" if b_higher == (direction == HIGHER) else "a"


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def compare_metrics(a: PlanRecord, b: PlanRecord) -> list[CompareMetricOut]:
    """Métricas globales de ambos planes con su diferencia absoluta."""
    out: list[CompareMetricOut] = []
    for key, label, section, field, direction in METRICS:
        va = _number((a.report.get(section) or {}).get(field))
        vb = _number((b.report.get(section) or {}).get(field))
        out.append(
            CompareMetricOut(
                key=key,
                label=label,
                direction=direction,
                a=va,
                b=vb,
                diff=_diff(va, vb),
                better=verdict(va, vb, direction),
            )
        )
    return out


def _equity_index(rec: PlanRecord) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(r["dimension"]), str(r["value"])): r for r in rec.report.get("equity") or []}


def compare_equity(a: PlanRecord, b: PlanRecord) -> list[CompareEquityOut]:
    """Equidad por grupo (unión de los grupos de ambos planes; faltantes quedan en `None`)."""
    ia, ib = _equity_index(a), _equity_index(b)
    out: list[CompareEquityOut] = []
    for dimension, value in sorted(ia.keys() | ib.keys()):
        for field, label, direction in EQUITY_METRICS:
            va = _number(ia.get((dimension, value), {}).get(field))
            vb = _number(ib.get((dimension, value), {}).get(field))
            out.append(
                CompareEquityOut(
                    key=field,
                    label=label,
                    direction=direction,
                    a=va,
                    b=vb,
                    diff=_diff(va, vb),
                    better=verdict(va, vb, direction),
                    dimension=dimension,
                    value=value,
                )
            )
    return out
