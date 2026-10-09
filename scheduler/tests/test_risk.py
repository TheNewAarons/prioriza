"""Riesgo exacto de desborde y condiciones lineales de R10 y R11 (formulación §6.3)."""

from __future__ import annotations

import itertools
import math

from hypothesis import given, settings
from hypothesis import strategies as st
from scheduler.risk import (
    SCALE,
    chernoff_theta,
    coef_one,
    coef_theta,
    overflow_risk,
    rhs_one,
    rhs_theta,
)

probs = st.lists(st.floats(0.001, 0.95), min_size=1, max_size=8)


def brute_risk(ps: list[float], capacity: int) -> float:
    """P(asisten > capacity) enumerando los 2^n resultados."""
    total = 0.0
    for shows in itertools.product([0, 1], repeat=len(ps)):
        prob = math.prod((1 - p) if s else p for p, s in zip(ps, shows, strict=True))
        if sum(shows) > capacity:
            total += prob
    return total


@given(probs, st.integers(0, 8))
def test_overflow_risk_matches_enumeration(ps: list[float], capacity: int) -> None:
    assert abs(overflow_risk(ps, capacity) - brute_risk(ps, capacity)) < 1e-12


def test_example_risk() -> None:
    assert abs(overflow_risk([0.45, 0.50, 0.10], 2) - 0.2475) < 1e-12
    assert coef_one(0.45) == 5978
    assert coef_one(0.50) == 6931
    assert coef_one(0.10) == 1053
    assert coef_one(0.08) == 833
    assert rhs_one(0.25) == 13863


@settings(max_examples=300)
@given(probs, st.floats(0.01, 0.9))
def test_r10_integer_condition_implies_exact_risk(ps: list[float], alpha: float) -> None:
    """Con un sobrecupo (n = C + 1), la condición entera de R10 implica riesgo <= alpha."""
    capacity = len(ps) - 1
    if sum(coef_one(p) for p in ps) >= rhs_one(alpha):
        assert overflow_risk(ps, capacity) <= alpha + 1e-12


@settings(max_examples=300)
@given(st.lists(st.floats(0.05, 0.95), min_size=3, max_size=8), st.floats(0.01, 0.9))
def test_r11_chernoff_condition_implies_exact_risk(ps: list[float], alpha: float) -> None:
    """Con o >= 2 sobrecupos, la condición de Chernoff (theta válido) es suficiente."""
    for o in range(2, len(ps)):
        capacity = len(ps) - o
        theta = chernoff_theta(sum(ps) / len(ps), capacity, o)
        if theta is None:
            continue
        if sum(coef_theta(p, theta) for p in ps) >= rhs_theta(theta, o, alpha):
            assert overflow_risk(ps, capacity) <= alpha + 1e-12


def test_chernoff_theta_disallows_when_too_few_noshows_expected() -> None:
    # 12 cupos, 2 sobrecupos, p = 0,05: se esperan 0,7 inasistencias < k = 1.
    assert chernoff_theta(0.05, 12, 2) is None
    theta = chernoff_theta(0.3, 12, 2)
    assert theta is not None and theta > 0
    assert SCALE == 10_000
