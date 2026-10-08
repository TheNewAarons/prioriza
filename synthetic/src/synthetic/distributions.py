"""Lognormal ajustada a media y mediana, cuantil normal (AS241) y muestreo estratificado."""

import math
from dataclasses import dataclass

import numpy as np

# Coeficientes del algoritmo AS241 (PPND16, Wichura 1988), precisión ~1e-16.
_A = (
    3.3871328727963666080,
    1.3314166789178437745e2,
    1.9715909503065514427e3,
    1.3731693765509461125e4,
    4.5921953931549871457e4,
    6.7265770927008700853e4,
    3.3430575583588128105e4,
    2.5090809287301226727e3,
)
_B = (
    1.0,
    4.2313330701600911252e1,
    6.8718700749205790830e2,
    5.3941960214247511077e3,
    2.1213794301586595867e4,
    3.9307895800092710610e4,
    2.8729085735721942674e4,
    5.2264952788528545610e3,
)
_C = (
    1.42343711074968357734,
    4.63033784615654529590,
    5.76949722146069140550,
    3.64784832476320460504,
    1.27045825245236838258,
    2.41780725177450611770e-1,
    2.27238449892691845833e-2,
    7.74545014278341407640e-4,
)
_D = (
    1.0,
    2.05319162663775882187,
    1.67638483018380384940,
    6.89767334985100004550e-1,
    1.48103976427480074590e-1,
    1.51986665636164571966e-2,
    5.47593808499534494600e-4,
    1.05075007164441684324e-9,
)
_E = (
    6.65790464350110377720,
    5.46378491116411436990,
    1.78482653991729133580,
    2.96560571828504891230e-1,
    2.65321895265761230930e-2,
    1.24266094738807843860e-3,
    2.71155556874348757815e-5,
    2.01033439929228813265e-7,
)
_F = (
    1.0,
    5.99832206555887937690e-1,
    1.36929880922735805310e-1,
    1.48753612908506148525e-2,
    7.86869131145613259100e-4,
    1.84631831751005468180e-5,
    1.42151175831644588870e-7,
    2.04426310338993978564e-15,
)


def _poly(coefs: tuple[float, ...], x: np.ndarray) -> np.ndarray:
    """Evalúa un polinomio por Horner con coeficientes en orden creciente."""
    acc = np.full_like(x, coefs[-1])
    for c in reversed(coefs[:-1]):
        acc = acc * x + c
    return acc


def norm_ppf(u: np.ndarray) -> np.ndarray:
    """Inversa de la normal estándar, vectorizada (AS241). Requiere ``0 < u < 1``."""
    p = np.asarray(u, dtype=np.float64)
    if ((p <= 0) | (p >= 1)).any():
        raise ValueError("u debe estar en (0, 1)")
    q = p - 0.5
    out = np.empty_like(p)
    central = np.abs(q) <= 0.425
    if central.any():
        r = 0.180625 - q[central] ** 2
        out[central] = q[central] * _poly(_A, r) / _poly(_B, r)
    tail = ~central
    if tail.any():
        pt = np.where(q[tail] < 0, p[tail], 1.0 - p[tail])
        r = np.sqrt(-np.log(pt))
        val = np.empty_like(r)
        near = r <= 5.0
        rn = r[near] - 1.6
        val[near] = _poly(_C, rn) / _poly(_D, rn)
        rf = r[~near] - 5.0
        val[~near] = _poly(_E, rf) / _poly(_F, rf)
        out[tail] = np.where(q[tail] < 0, -val, val)
    return out


@dataclass(frozen=True)
class LogNormal:
    """Lognormal con parámetros del logaritmo (mu, sigma)."""

    mu: float
    sigma: float


def needs_sigma_floor(mean: float, median: float) -> bool:
    """Verdadero si media <= 1,001·mediana y la lognormal no ajusta (se usa el piso de sigma)."""
    return not mean > 1.001 * median


def fit_lognormal(mean: float, median: float, sigma_floor: float = 0.1) -> LogNormal:
    """Ajusta una lognormal: mu = ln(mediana); sigma = sqrt(2 ln(media/mediana)) o el piso."""
    if median <= 0 or mean <= 0:
        raise ValueError("media y mediana deben ser positivas")
    mu = math.log(median)
    if needs_sigma_floor(mean, median):
        return LogNormal(mu, sigma_floor)
    return LogNormal(mu, math.sqrt(2.0 * math.log(mean / median)))


def stratified_lognormal(d: LogNormal, n: int, rng: np.random.Generator, cap: float) -> np.ndarray:
    """Muestra estratificada: u_i = (pi(i) + v_i)/n, W = exp(mu + sigma·Phi^-1(u)), en [1, cap]."""
    if n <= 0:
        return np.empty(0, dtype=np.float64)
    perm = rng.permutation(n)
    v = rng.random(n)
    u = (perm + v) / n
    u = np.clip(u, 1e-12, 1.0 - 1e-12)
    w = np.exp(d.mu + d.sigma * norm_ppf(u))
    return np.clip(w, 1.0, cap)


def match_mean_median(
    x: np.ndarray, mean: float, median: float, lo: float, hi: float
) -> np.ndarray:
    """Reescala la muestra para fijar la mediana y acercar la media al objetivo.

    Primero multiplica por ``median / mediana_muestral``; luego aplica una potencia
    ``median·(x/median)^k`` (que deja fija la mediana) con ``k`` por bisección para que
    la media de la muestra acotada a ``[lo, hi]`` iguale ``mean``. Si el objetivo no es
    alcanzable, usa el ``k`` más cercano.
    """
    if x.size == 0:
        return x
    med = float(np.median(x))
    y = np.clip(x * (median / med), lo, hi) if med > 0 else x
    base = np.maximum(y / median, 1e-12)

    def mean_for(k: float) -> float:
        return float(np.clip(median * base**k, lo, hi).mean())

    k_lo, k_hi = 0.05, 6.0
    if not mean_for(k_lo) <= mean <= mean_for(k_hi):
        k = k_lo if abs(mean_for(k_lo) - mean) < abs(mean_for(k_hi) - mean) else k_hi
        return np.clip(median * base**k, lo, hi)
    for _ in range(60):
        mid = 0.5 * (k_lo + k_hi)
        if mean_for(mid) < mean:
            k_lo = mid
        else:
            k_hi = mid
    return np.clip(median * base ** (0.5 * (k_lo + k_hi)), lo, hi)
