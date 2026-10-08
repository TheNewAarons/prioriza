"""Escenarios de inasistencia: neutral, baseline y ses_gradient (plan sección 2 y decisión 3)."""

from __future__ import annotations

import math

import polars as pl
import pytest

AGES = ["0_14", "15_19", "20_44", "45_64", "65_plus"]
INS = ["fonasa_a", "fonasa_b", "fonasa_c", "fonasa_d", "other"]


def _noshow(ds):
    return ds.run["params"]["noshow"]


def test_neutral_sin_efectos(ds20k_neutral):
    """neutral: beta_age = beta_ins = gamma = 0 (control obligatorio)."""
    p = _noshow(ds20k_neutral)
    assert all(v == 0 for v in p["beta_age"].values())
    assert all(v == 0 for v in p["beta_ins"].values())
    assert all(v == 0 for v in p["gamma"].values())


def test_baseline_sin_efecto_de_prevision(ds20k):
    """baseline: SIN efecto de previsión (decisión 3), con efecto de edad y de especialidad."""
    p = _noshow(ds20k)
    assert all(v == 0 for v in p["beta_ins"].values())
    assert p["beta_age"] == {
        "0_14": 0.10,
        "15_19": 0.35,
        "20_44": 0.30,
        "45_64": 0.0,
        "65_plus": -0.20,
    }
    assert any(v != 0 for v in p["gamma"].values())
    assert p["beta_wait"] == 0.15 and p["beta_lead"] == 0.10


def test_ses_gradient_con_efecto_de_prevision(ds20k_ses):
    """ses_gradient: baseline + beta_ins {A +0,2; B +0,1; C 0; D -0,1; other 0}."""
    p = _noshow(ds20k_ses)
    assert p["beta_ins"] == {
        "fonasa_a": 0.2,
        "fonasa_b": 0.1,
        "fonasa_c": 0.0,
        "fonasa_d": -0.1,
        "other": 0.0,
    }
    assert p["beta_age"]["20_44"] == 0.30


def test_escenario_registrado_en_la_corrida(ds20k, ds20k_neutral, ds20k_ses):
    """run['scenario'] refleja el escenario pedido."""
    assert [d.run["scenario"] for d in (ds20k, ds20k_neutral, ds20k_ses)] == [
        "baseline",
        "neutral",
        "ses_gradient",
    ]


@pytest.mark.parametrize("fixture", ["ds20k", "ds20k_neutral", "ds20k_ses"])
def test_tasas_por_servicio_y_tipo_se_mantienen(request, fixture, targets, assumptions, m):
    """En los tres escenarios la media de p por (servicio, tipo) = tasa objetivo (+-1e-4)."""
    ds = request.getfixturevalue(fixture)
    rates = m.noshow_rates(targets, assumptions)
    df = m.entry_p_ref(ds, targets)
    for (s, c), rate in rates.items():
        sub = df.filter((pl.col("health_service_code") == s) & (pl.col("care_type") == c))
        if sub.height:
            assert abs(float(sub["p_ref"].mean()) - rate) <= 1e-4, (fixture, s, c)


def _logit(p):
    return pl.col(p).clip(1e-9, 1 - 1e-9).log() - (1 - pl.col(p).clip(1e-9, 1 - 1e-9)).log()


def _group_gap(ds, m, col, hi, lo):
    """Diferencia de logit(p) entre dos categorías, centrada por servicio (historial)."""
    h = m.history_frame(ds).with_columns(_logit("true_noshow_prob").alias("lg"))
    h = h.with_columns(
        (pl.col("lg") - pl.col("lg").mean().over("health_service_code")).alias("res")
    )
    g = h.group_by(col).agg(pl.col("res").mean().alias("mu"))
    mu = dict(zip(g[col].to_list(), g["mu"].to_list(), strict=True))
    return mu[hi] - mu[lo]


def test_neutral_sin_brecha_por_edad_ni_prevision(ds20k_neutral, m):
    """neutral: logit(p) del historial (centrado por servicio) sin brecha por edad/previsión."""
    assert abs(_group_gap(ds20k_neutral, m, "age_group", "20_44", "65_plus")) < 0.12
    assert abs(_group_gap(ds20k_neutral, m, "insurance", "fonasa_a", "fonasa_d")) < 0.12


def test_baseline_brecha_por_edad_pero_no_por_prevision(ds20k, m):
    """baseline: 20_44 vs 65_plus ~ +0,5 en logit (> 0,3); previsión sin brecha (< 0,12)."""
    assert _group_gap(ds20k, m, "age_group", "20_44", "65_plus") > 0.3
    assert abs(_group_gap(ds20k, m, "insurance", "fonasa_a", "fonasa_d")) < 0.12


def test_ses_gradient_brecha_por_prevision(ds20k_ses, m):
    """ses_gradient: fonasa_a vs fonasa_d ~ +0,3 en logit (> 0,15)."""
    assert _group_gap(ds20k_ses, m, "insurance", "fonasa_a", "fonasa_d") > 0.15


def test_probabilidades_validas(ds20k):
    """true_noshow_prob en (0, 1) y sin nulos; el historial usa anticipación 7..90 d."""
    t = ds20k.tables["appointment_truth"]["true_noshow_prob"]
    assert t.null_count() == 0 and t.min() > 0 and t.max() < 1
    lead = ds20k.tables["appointment"]["lead_days"]
    assert lead.min() >= 7 and lead.max() <= 90
    assert math.isfinite(t.mean())
