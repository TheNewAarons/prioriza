"""Calibración C1-C8 (estrictas) sobre N=20.000, semilla 42.

Las métricas se recalculan en ``synthetic_metrics.py`` a partir de los DataFrames y de
los JSON versionados (no se confía solo en ``passed`` del informe). Además se verifica
``calibration_report(...).passed``. Tolerancias del plan de diseño, sección 5.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest
from synthetic.validate import calibration_report

C1_NAMES = [
    "tipo",
    "servicio|cne",
    "servicio|iq",
    "especialidad|cne_medical",
    "especialidad|cne_dental",
    "especialidad|iq",
    "problema|ges",
    "servicio|ges",
    "edad|pediatrica",
    "edad|general",
    "previsión",
]


@pytest.fixture(scope="module")
def c1(ds20k, targets, assumptions, m):
    return m.c1_checks(ds20k, targets, assumptions)


@pytest.mark.parametrize("name", C1_NAMES)
def test_c1_tvd_margenes(c1, name):
    """C1: TVD = 1/2 sum|p_obs - p_obj| <= K/(2n) + 1e-9 (cota de redondeo de Hamilton)."""
    obs, bound = c1[name]
    assert obs <= bound, f"{name}: tvd={obs:.6f} > {bound:.6f}"


def test_c1_comuna_por_servicio(c1):
    """C1: TVD de comuna|servicio <= K/(2n) + 1e-9 en cada servicio con APS."""
    keys = [k for k in c1 if k.startswith("comuna|servicio")]
    assert len(keys) >= 20
    bad = {k: c1[k] for k in keys if c1[k][0] > c1[k][1]}
    assert not bad, bad


def test_c2_espera_por_servicio_y_tipo(ds20k, targets, m):
    """C2: por (servicio, tipo) con n>=30: mediana +-max(2 %, 1 día); media +-3 %."""
    fails, groups = m.wait_group_errors(ds20k, targets)
    assert groups >= 20
    assert not fails, fails


@pytest.mark.parametrize("key,care", [("consultation", "consultation"), ("surgery", "surgery")])
def test_c3_mezcla_nacional(ds20k, targets, m, key, care):
    """C3: media y mediana nacionales de la mezcla (CNE 341/242, IQ 394/264) +-5 %."""
    nat = targets.national_row(key)
    mean, median = m.national_wait(ds20k, care)
    assert m.within(mean, nat.mean_wait_days, 0.05), (mean, nat.mean_wait_days)
    assert m.within(median, nat.median_wait_days, 0.05), (median, nat.median_wait_days)


def test_c4_registros_por_persona(ds20k, targets, m):
    """C4: razón registros/personas por (servicio, tipo) +-(0,01 + 1/P)."""
    fails, groups = m.ratio_errors(ds20k, targets)
    assert groups >= 40
    assert not fails, fails


def test_c5_retraso_ges_por_problema(ds20k, targets, assumptions, m):
    """C5: retraso GES por problema con n>=30: mediana +-max(2 %, 1 día); media +-3 %."""
    fails, groups, _, _ = m.ges_delay_errors(ds20k, targets, assumptions)
    assert groups >= 1
    assert not fails, fails


def test_c5_retraso_ges_agregado(ds20k, targets, assumptions, m):
    """C5: media agregada del retraso +-5 % de la mezcla de problemas mapeados.

    El objetivo nacional 136/71 incluye problemas no mapeados (cobertura < 100 %), por lo
    que se compara con la mezcla ponderada de los problemas mapeados; el nacional se
    informa en el siguiente test sin fallar (se reporta, no se oculta).
    """
    _, _, delay, mix_mean = m.ges_delay_errors(ds20k, targets, assumptions)
    assert delay.size > 100
    assert m.within(float(delay.mean()), mix_mean, 0.05), (delay.mean(), mix_mean)


def test_c5_retraso_ges_vs_nacional_informativo(ds20k, targets, assumptions, m, record_property):
    """C5 (informativo): compara con el nacional 136/71 del plan y lo registra."""
    _, _, delay, _ = m.ges_delay_errors(ds20k, targets, assumptions)
    record_property("ges_delay_mean", float(delay.mean()))
    record_property("ges_delay_median", float(np.median(delay)))
    assert delay.size > 0


def test_c6_media_p_por_servicio_y_tipo(ds20k, targets, assumptions, m):
    """C6: media de p verdadera (anticipación 28 d) por (servicio, tipo) = tasa objetivo +-1e-4."""
    rates = m.noshow_rates(targets, assumptions)
    df = m.entry_p_ref(ds20k, targets)
    worst = 0.0
    for (s, c), rate in rates.items():
        sub = df.filter((pl.col("health_service_code") == s) & (pl.col("care_type") == c))
        if sub.height == 0:
            continue
        worst = max(worst, abs(float(sub["p_ref"].mean()) - rate))
    assert worst <= 1e-4, worst


def test_c6_tasas_objetivo_agregadas(targets, assumptions, m):
    """Tasas objetivo: CNE 15,65 % ponderado por L, Arica 22 %, Iquique 21 %, IQ 5 %."""
    rates = m.noshow_rates(targets, assumptions)
    cne = {
        r.health_service_code: r.waiting_count
        for r in targets.service_rows
        if r.care_type == "consultation"
    }
    avg = sum(rates[(s, "consultation")] * w for s, w in cne.items()) / sum(cne.values())
    assert math.isclose(avg, 0.1565, abs_tol=1e-6)
    assert rates[(1, "consultation")] == 0.22 and rates[(2, "consultation")] == 0.21
    assert all(v == 0.05 for (s, c), v in rates.items() if c == "surgery")


def test_c6_historial_global_y_por_servicio(ds20k, m):
    """C6: tasa realizada vs E[p] del historial: global y por servicio con n_h>=200,
    +-(3*sqrt(t(1-t)/n_h) + 0,5 pp)."""
    h = m.history_frame(ds20k)
    t = float(h["true_noshow_prob"].mean())
    obs = float((h["status"] == "no_show").mean())
    assert abs(obs - t) <= 3 * math.sqrt(t * (1 - t) / h.height) + 0.005
    checked = 0
    for svc in sorted(set(h["health_service_code"].to_list())):
        sub = h.filter(pl.col("health_service_code") == svc)
        if sub.height < 200:
            continue
        checked += 1
        ts = float(sub["true_noshow_prob"].mean())
        os_ = float((sub["status"] == "no_show").mean())
        assert abs(os_ - ts) <= 3 * math.sqrt(ts * (1 - ts) / sub.height) + 0.005, svc
    assert checked >= 5


def test_c7_participacion_iq_mayor(ds20k, targets):
    """C7: participación de IQ mayor (no GES) = 302.093/(302.093+115.468) +-3 pp."""
    sub = {r.care_subtype: r.waiting_count for r in targets.subtypes if r.care_type == "surgery"}
    target = sub["major"] / (sub["major"] + sub["minor"])
    iq = ds20k.tables["waitlist_entry"].filter(
        ~pl.col("is_ges") & (pl.col("care_type") == "surgery")
    )
    assert abs(float((iq["care_subtype"] == "major").mean()) - target) <= 0.03


def test_c8_capacidad_programada(ds20k, targets, assumptions, m):
    """C8: minutos programados / H vs objetivo (Little) por (servicio, tipo):
    +-max(5 %, 1 sesión/H)."""
    fails, groups = m.capacity_errors(ds20k, targets, assumptions, 20_000, 26)
    assert groups >= 40
    assert not fails, fails


def test_informe_de_calibracion_pasa(ds20k, targets, assumptions):
    """calibration_report(...).passed es verdadero y no hay chequeos estrictos fallidos."""
    rep = calibration_report(ds20k, targets, assumptions)
    failed = [c.name for c in rep.checks if c.severity == "strict" and not c.passed]
    assert not failed, failed
    assert rep.passed
    assert rep.digest == ds20k.digest
    assert any(c.group == "C1" for c in rep.checks)
    assert any("validación institucional" in n for n in rep.notes)


def test_informe_no_oculta_resultados_blandos(ds20k, targets, assumptions):
    """Los chequeos blandos (C9) se incluyen en el informe aunque no fallen."""
    rep = calibration_report(ds20k, targets, assumptions)
    assert any(c.group == "C9" for c in rep.checks)
