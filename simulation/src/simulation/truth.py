"""Probabilidad verdadera de inasistencia del generador (diseño §6).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

El programador ve solo la probabilidad predicha por ``noshow/``; el mundo responde con la
verdadera. Este módulo es el único del paquete que importa ``true_noshow_prob`` y
``NoShowParams``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from synthetic.noshow_truth import NoShowParams, true_noshow_prob


def true_params(data: dict[str, Any]) -> NoShowParams:
    """Reconstruye los parámetros del generador desde ``manifest["params"]["noshow"]``."""
    return NoShowParams.from_json(data)


def attendance_probability(
    params: NoShowParams, features: pl.DataFrame, frailty: np.ndarray
) -> np.ndarray:
    """Probabilidad verdadera de inasistencia por fila (``features`` según ``true_noshow_prob``)."""
    return true_noshow_prob(features, frailty, params)
