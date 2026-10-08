"""Tests de propiedad (hypothesis) de las utilidades numéricas de synthetic."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from synthetic.allocation import hamilton, labels
from synthetic.distributions import fit_lognormal, norm_ppf

SETTINGS = settings(max_examples=100, deadline=None, derandomize=True)


@st.composite
def _weights(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    w = draw(
        st.lists(
            st.one_of(
                st.just(0.0),
                st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False),
            ),
            min_size=n,
            max_size=n,
        )
    )
    if sum(w) <= 0:
        w[0] = 1.0
    return {f"k{i}": x for i, x in enumerate(w)}


@SETTINGS
@given(weights=_weights(), total=st.integers(min_value=0, max_value=200_000))
def test_hamilton_suma_total_y_error_menor_que_uno(weights, total):
    """Hamilton: suma exacta del total y |asignado - exacto| < 1 por clave.

    Tolerancia del plan (sección 1/5): cota de redondeo del resto mayor.
    """
    out = hamilton(weights, total)
    assert set(out) == set(weights)
    assert sum(out.values()) == total
    s = sum(weights.values())
    for k, w in weights.items():
        exact = w / s * total
        assert out[k] >= 0
        assert abs(out[k] - exact) < 1.0 + 1e-6


@SETTINGS
@given(weights=_weights(), total=st.integers(min_value=0, max_value=5_000))
def test_hamilton_es_determinista(weights, total):
    """Mismo insumo, misma asignación (sin aleatoriedad)."""
    assert hamilton(weights, total) == hamilton(dict(weights), total)


@SETTINGS
@given(
    counts=st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=10),
)
def test_labels_respeta_conteos(counts):
    """labels devuelve un vector con exactamente los conteos pedidos."""
    order = [f"k{i}" for i in range(len(counts))]
    arr = labels(dict(zip(order, counts, strict=True)), order)
    assert len(arr) == sum(counts)
    for k, c in zip(order, counts, strict=True):
        assert int(np.sum(np.asarray(arr) == k)) == c


@SETTINGS
@given(
    median=st.floats(min_value=1.0, max_value=2000.0),
    ratio=st.floats(min_value=1.002, max_value=6.0),
)
def test_fit_lognormal_ida_y_vuelta(median, ratio):
    """Sin piso (media > 1,001*mediana): mediana = exp(mu), media = exp(mu + s^2/2)."""
    mean = median * ratio
    d = fit_lognormal(mean, median)
    assert math.isclose(math.exp(d.mu), median, rel_tol=1e-9)
    assert math.isclose(math.exp(d.mu + d.sigma**2 / 2), mean, rel_tol=1e-9)


@SETTINGS
@given(
    median=st.floats(min_value=1.0, max_value=2000.0),
    ratio=st.floats(min_value=0.5, max_value=1.001),
)
def test_fit_lognormal_aplica_piso(median, ratio):
    """Si media <= 1,001*mediana se usa sigma = piso (0,1) y mu = ln(mediana)."""
    d = fit_lognormal(median * ratio, median)
    assert d.sigma == 0.1
    assert math.isclose(math.exp(d.mu), median, rel_tol=1e-9)


@SETTINGS
@given(
    u=st.lists(
        st.floats(min_value=1e-10, max_value=1 - 1e-10, allow_nan=False),
        min_size=1,
        max_size=50,
    )
)
def test_norm_ppf_coincide_con_normaldist(u):
    """norm_ppf (AS241) coincide con statistics.NormalDist().inv_cdf (atol 1e-8)."""
    got = norm_ppf(np.asarray(u, dtype=float))
    ref = np.array([NormalDist().inv_cdf(x) for x in u])
    np.testing.assert_allclose(got, ref, atol=1e-8, rtol=1e-8)


def test_hamilton_pesos_denormales_no_producen_nan():
    """Caso límite: pesos denormales (5e-324) hacen total/suma = inf e inf*0 = nan.

    Regresión de robustez en ``hamilton`` (ya corregida).
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = hamilton({"a": 5e-324, "b": 0.0}, 3)
    assert sum(out.values()) == 3
