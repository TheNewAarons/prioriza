"""Riesgo de desborde por sobrecupo (formulación §6.3 y verificación §9).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

SCALE = 10_000


def overflow_risk(noshow_probs: Sequence[float], capacity: int) -> float:
    """``P(asisten > capacity)`` exacto con la distribución binomial de Poisson.

    Cada paciente asiste con probabilidad ``1 - p``, de forma independiente. Programación
    dinámica ``O(n²)`` sobre el número de asistentes.
    """
    dist = [1.0]
    for p in noshow_probs:
        show = 1.0 - p
        nxt = [0.0] * (len(dist) + 1)
        for k, mass in enumerate(dist):
            nxt[k] += mass * p
            nxt[k + 1] += mass * show
        dist = nxt
    return math.fsum(dist[capacity + 1 :])


def coef_one(p: float) -> int:
    """``A_ib`` de R10: ``floor(10⁴ · (-ln(1 - p)))`` (redondeo conservador)."""
    return math.floor(SCALE * -math.log1p(-p))


def rhs_one(alpha: float) -> int:
    """``R1`` de R10: ``ceil(10⁴ · ln(1/alpha))``."""
    return math.ceil(SCALE * math.log(1.0 / alpha))


def chernoff_theta(p_mean: float, capacity: int, overbook: int) -> float | None:
    """``theta`` que ajusta la cota de Chernoff de R11 en un bloque típico; ``None`` si no aplica.

    Con ``k = o - 1`` y ``n = C + o``, ``e^{-theta} = k(1 - p̄) / ((n - k)·p̄)``. Si ese valor es
    ``≥ 1`` (se esperan menos de ``k`` inasistencias), el nivel ``o`` no se permite.
    """
    k = overbook - 1
    n = capacity + overbook
    if k < 1 or p_mean <= 0.0:
        return None
    ratio = k * (1.0 - p_mean) / ((n - k) * p_mean)
    if ratio >= 1.0:
        return None
    return -math.log(ratio)


def coef_theta(p: float, theta: float) -> int:
    """``A^theta_ib`` de R11: ``floor(10⁴ · (-ln(1 - p(1 - e^{-theta}))))``."""
    return math.floor(SCALE * -math.log1p(-p * (1.0 - math.exp(-theta))))


def rhs_theta(theta: float, overbook: int, alpha: float) -> int:
    """``R^theta_o`` de R11: ``ceil(10⁴ · (theta·(o - 1) + ln(1/alpha)))``."""
    return math.ceil(SCALE * (theta * (overbook - 1) + math.log(1.0 / alpha)))
