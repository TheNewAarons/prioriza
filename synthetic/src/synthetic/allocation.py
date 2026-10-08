"""Asignación determinista con márgenes exactos (método de Hamilton / resto mayor)."""

from collections.abc import Mapping, Sequence

import numpy as np


def hamilton[K](weights: Mapping[K, float], total: int) -> dict[K, int]:
    """Reparte ``total`` unidades en proporción a ``weights`` por resto mayor.

    Los empates se resuelven por el orden de inserción de ``weights``. La suma de la
    salida es exactamente ``total``; cada cuota difiere de la ideal en menos de 1.
    """
    if total < 0:
        raise ValueError("total debe ser >= 0")
    keys = list(weights)
    if not keys:
        if total:
            raise ValueError("no hay claves para repartir")
        return {}
    w = np.array([float(weights[k]) for k in keys], dtype=np.float64)
    if (w < 0).any() or not np.isfinite(w).all():
        raise ValueError("los pesos deben ser finitos y no negativos")
    peak = float(w.max())
    if peak > 0:
        w = w / peak  # evita desbordes (total/suma = inf) con pesos denormales
    s = float(w.sum())
    if s <= 0:
        if total:
            raise ValueError("la suma de pesos debe ser positiva")
        return dict.fromkeys(keys, 0)
    quota = w * (total / s)
    base = np.floor(quota).astype(np.int64)
    remainder = total - int(base.sum())
    if remainder > 0:
        frac = quota - base
        # orden estable: mayor resto primero, luego menor índice
        order = np.lexsort((np.arange(len(keys)), -frac))
        # un peso cero nunca recibe unidad extra salvo que no haya más candidatos
        for idx in order[:remainder]:
            base[idx] += 1
    return {k: int(c) for k, c in zip(keys, base, strict=True)}


def labels[K](counts: Mapping[K, int], order: Sequence[K]) -> np.ndarray:
    """Vector de etiquetas: cada clave de ``order`` repetida ``counts[clave]`` veces."""
    total = sum(int(counts.get(k, 0)) for k in order)
    out = np.empty(total, dtype=object)
    pos = 0
    for k in order:
        c = int(counts.get(k, 0))
        out[pos : pos + c] = [k] * c if c else []
        pos += c
    return out
