"""Métricas: ECE, curva de calibración, evaluate y bootstrap pareado."""

from __future__ import annotations

import numpy as np
from noshow.metrics import (
    calibration_curve,
    evaluate,
    expected_calibration_error,
    paired_brier_bootstrap,
)


def test_ece_is_zero_when_calibrated_per_bin() -> None:
    p = np.array([0.25] * 4 + [0.75] * 4)
    y = np.array([1, 0, 0, 0, 1, 1, 1, 0])
    assert expected_calibration_error(y, p) == 0.0


def test_ece_positive_when_miscalibrated() -> None:
    p = np.full(10, 0.9)
    y = np.zeros(10, dtype=int)
    assert expected_calibration_error(y, p) > 0.8


def test_calibration_curve_counts_sum_to_n() -> None:
    rng = np.random.default_rng(3)
    p = rng.random(137)
    y = (rng.random(137) < p).astype(int)
    curve = calibration_curve(y, p, bins=10)
    assert sum(b["n"] for b in curve) == len(y)


def test_evaluate_constant_target_has_no_auc() -> None:
    p = np.linspace(0.1, 0.9, 20)
    out = evaluate(np.zeros(20, dtype=int), p)
    assert out["auc"] is None
    assert out["observed_rate"] == 0.0


def test_paired_bootstrap_identical_predictions() -> None:
    rng = np.random.default_rng(5)
    p = rng.random(60)
    y = (rng.random(60) < p).astype(int)
    groups = np.repeat(np.arange(20), 3)
    out = paired_brier_bootstrap(y, p, p.copy(), groups, n_boot=100, seed=1)
    assert out["brier_difference"] == 0.0
    assert out["ci95_low"] == 0.0
    assert out["ci95_high"] == 0.0


def test_paired_bootstrap_deterministic_with_seed() -> None:
    rng = np.random.default_rng(6)
    y = (rng.random(90) < 0.3).astype(int)
    p1, p2 = rng.random(90), rng.random(90)
    groups = np.repeat(np.arange(30), 3)
    a = paired_brier_bootstrap(y, p1, p2, groups, n_boot=200, seed=9)
    b = paired_brier_bootstrap(y, p1, p2, groups, n_boot=200, seed=9)
    assert a == b
    assert a["resampling_unit"] == "patient"
