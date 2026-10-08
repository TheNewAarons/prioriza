"""Métricas de discriminación y calibración, comparación pareada (bootstrap) y equidad por grupo."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

DEFAULT_BINS = 10
DECIMALS = 6


def _r(x: float) -> float:
    return round(float(x), DECIMALS)


def _quantile_bins(p: np.ndarray, bins: int) -> np.ndarray:
    """Índice de bin por fila con bins de igual frecuencia (empates van al mismo bin)."""
    edges = np.unique(np.quantile(p, np.linspace(0.0, 1.0, bins + 1)[1:-1]))
    return np.searchsorted(edges, p, side="right")


def calibration_curve(
    y: np.ndarray, p: np.ndarray, bins: int = DEFAULT_BINS
) -> list[dict[str, Any]]:
    """Por bin de igual frecuencia: probabilidad media predicha, tasa observada y n."""
    idx = _quantile_bins(p, bins)
    out: list[dict[str, Any]] = []
    for b in np.unique(idx):
        m = idx == b
        out.append(
            {
                "mean_predicted": _r(p[m].mean()),
                "observed_rate": _r(y[m].mean()),
                "n": int(m.sum()),
            }
        )
    return out


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = DEFAULT_BINS) -> float:
    """ECE = Σ_b (n_b / n) · |tasa observada_b - probabilidad media_b|, bins de igual frecuencia."""
    idx = _quantile_bins(p, bins)
    n = len(p)
    total = 0.0
    for b in np.unique(idx):
        m = idx == b
        total += m.sum() / n * abs(y[m].mean() - p[m].mean())
    return float(total)


def evaluate(y: np.ndarray, p: np.ndarray, bins: int = DEFAULT_BINS) -> dict[str, Any]:
    """AUC, Brier, log loss, ECE, tasa media predicha frente a observada y curva de calibración."""
    y = np.asarray(y, dtype=np.int64)
    p = np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)
    return {
        "auc": _r(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None,
        "brier": _r(brier_score_loss(y, p)),
        "log_loss": _r(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])),
        "ece": _r(expected_calibration_error(y, p, bins)),
        "mean_predicted": _r(p.mean()),
        "observed_rate": _r(y.mean()),
        "calibration_curve": calibration_curve(y, p, bins),
    }


def paired_brier_bootstrap(
    y: np.ndarray,
    p_model: np.ndarray,
    p_reference: np.ndarray,
    groups: np.ndarray,
    n_boot: int,
    seed: int,
) -> dict[str, Any]:
    """Diferencia de Brier (modelo - referencia) con IC 95 % por bootstrap de pacientes.

    Se remuestrean pacientes, no citas, porque las citas de un mismo paciente comparten la
    fragilidad latente y no son independientes. Negativo = el modelo es mejor.
    """
    y = np.asarray(y, dtype=np.float64)
    loss_diff = (np.asarray(p_model) - y) ** 2 - (np.asarray(p_reference) - y) ** 2
    _, g = np.unique(groups, return_inverse=True)
    n_groups = int(g.max()) + 1
    sum_by_group = np.bincount(g, weights=loss_diff, minlength=n_groups)
    n_by_group = np.bincount(g, minlength=n_groups).astype(np.float64)
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        w = np.bincount(rng.integers(0, n_groups, size=n_groups), minlength=n_groups)
        stats[i] = (w @ sum_by_group) / (w @ n_by_group)
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return {
        "brier_difference": _r(loss_diff.mean()),
        "ci95_low": _r(lo),
        "ci95_high": _r(hi),
        "n_boot": n_boot,
        "resampling_unit": "patient",
    }


def group_calibration(
    frame: pl.DataFrame, column: str, prob: str, min_n: int, truth: str | None = None
) -> list[dict[str, Any]]:
    """Por grupo: n, tasa observada, probabilidad media predicha y (si hay) media verdadera.

    ``gap`` = predicha - observada. Los grupos con menos de ``min_n`` citas se omiten.
    """
    aggs = [
        pl.len().alias("n"),
        pl.col("no_show").mean().alias("observed_rate"),
        pl.col(prob).mean().alias("mean_predicted"),
    ]
    if truth is not None:
        aggs.append(pl.col(truth).mean().alias("mean_true_prob"))
    stats = frame.group_by(column).agg(aggs).filter(pl.col("n") >= min_n).sort(column)
    out: list[dict[str, Any]] = []
    for row in stats.iter_rows(named=True):
        item: dict[str, Any] = {
            "group": str(row[column]),
            "n": int(row["n"]),
            "observed_rate": _r(row["observed_rate"]),
            "mean_predicted": _r(row["mean_predicted"]),
            "gap": _r(row["mean_predicted"] - row["observed_rate"]),
        }
        if truth is not None:
            item["mean_true_prob"] = _r(row["mean_true_prob"])
            item["gap_vs_truth"] = _r(row["mean_predicted"] - row["mean_true_prob"])
        out.append(item)
    return out
