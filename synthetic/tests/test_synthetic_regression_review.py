"""Regresiones de la revisión de ml-engineer (hallazgos A1, A2, B1 y M2/C6 independiente).

Todo es 100% sintético, con semillas fijas y sin red.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from synthetic.validate import calibration_report

SEED = 42


def _assumptions_with(a, **overrides):
    """Copia en memoria de los supuestos con valores de parámetros cambiados."""
    params = {
        k: (v.model_copy(update={"value": overrides[k]}) if k in overrides else v)
        for k, v in a.parameters.items()
    }
    return a.model_copy(update={"parameters": params})


def _gen(size, a, t):
    from shared.db.enums import NoShowScenario
    from synthetic.config import RunConfig
    from synthetic.pipeline import generate

    cfg = RunConfig(size=size, seed=SEED, scenario=NoShowScenario("baseline"))
    return generate(cfg, t, a)


# ------------------------------------------------------------------ A1


def test_a1_lambda_del_historial_se_usa(targets, assumptions):
    """Cambiar history_poisson_lambda cambia el nº de citas del historial y el digest."""
    base = float(assumptions.value("history_poisson_lambda"))
    a_hi = _assumptions_with(assumptions, history_poisson_lambda=base * 3)
    d0 = _gen(1_000, assumptions, targets)
    d1 = _gen(1_000, a_hi, targets)
    assert d1.tables["appointment"].height > d0.tables["appointment"].height * 1.5
    assert d1.digest != d0.digest


def test_a1_mismos_supuestos_mismo_resultado(targets, assumptions):
    """Con los mismos supuestos (copia idéntica) el resultado es idéntico."""
    a_copy = _assumptions_with(assumptions)
    d0 = _gen(1_000, assumptions, targets)
    d1 = _gen(1_000, a_copy, targets)
    assert d0.digest == d1.digest
    assert d0.tables["appointment"].height == d1.tables["appointment"].height


# ------------------------------------------------------------------ A2


def test_a2_specialty_code_del_historial(ds20k):
    """specialty_code no nulo y dentro de las especialidades de las entradas del paciente."""
    ap = ds20k.tables["appointment"]
    assert "specialty_code" in ap.columns
    hist = ap.filter(pl.col("origin") == "history") if "origin" in ap.columns else ap
    assert hist.height > 0
    assert hist["specialty_code"].null_count() == 0
    allowed = (
        ds20k.tables["waitlist_entry"]
        .group_by("patient_id")
        .agg(pl.col("specialty_code").unique().alias("allowed"))
    )
    chk = hist.select("patient_id", "specialty_code").join(allowed, on="patient_id", how="left")
    assert chk["allowed"].null_count() == 0
    ok = [s in al for s, al in zip(chk["specialty_code"], chk["allowed"], strict=True)]
    assert all(ok)


# ------------------------------------------------------------------ C6 independiente


def _independent_checks(rep):
    return [
        c
        for c in rep.checks
        if c.group == "C6" and c.name.startswith("C6.media_p") and c.name != "C6.media_p"
    ]


def test_c6_independiente_existe_y_pasa(ds20k, targets, assumptions):
    """El informe tiene un C6 independiente estricto y pasa con N=20.000; el viejo se mantiene."""
    rep = calibration_report(ds20k, targets, assumptions)
    assert any(c.name == "C6.media_p" for c in rep.checks)
    ind = _independent_checks(rep)
    assert ind, "falta el chequeo C6 con sorteo independiente de u"
    for c in ind:
        assert c.severity == "strict"
        assert c.passed, c.detail


def test_c6_media_p_con_u_independiente_recalculada(ds20k, targets, assumptions, m):
    """No tautológico: media de p con un u nuevo (semilla fija) vs tasa objetivo por grupo."""
    sigma_u = float(ds20k.run["params"]["noshow"]["sigma_u"])
    entry = ds20k.tables["waitlist_entry"]
    rng = np.random.default_rng(987_654)
    u = rng.normal(0.0, sigma_u, entry.height)
    pref = m.entry_p_ref(ds20k, targets, frailty=u)
    rates = m.noshow_rates(targets, assumptions)
    p = pref["p_ref"].to_numpy()
    svc = pref["health_service_code"].to_list()
    ct = pref["care_type"].to_list()
    checked = 0
    for (s, c), rate in sorted(rates.items()):
        idx = [i for i, (a, b) in enumerate(zip(svc, ct, strict=True)) if a == s and b == c]
        if len(idx) < 200:
            continue
        checked += 1
        sub = p[idx]
        tol = 3 * float(sub.std()) / np.sqrt(len(idx)) + 0.005
        assert abs(float(sub.mean()) - rate) <= tol, (s, c, float(sub.mean()), rate, tol)
    assert checked >= 5


# ------------------------------------------------------------------ B1


def test_b1_historial_vs_objetivo_separado_por_tipo(ds20k, targets, assumptions):
    """Hay una comparación blanda del historial por tipo (CNE e IQ), no una sola mezclada."""
    rep = calibration_report(ds20k, targets, assumptions)
    comp = [c for c in rep.checks if c.name.startswith("C6.historial.vs_tasa_objetivo")]
    assert len(comp) >= 2, [c.name for c in comp]
    names = " ".join(c.name.lower() + " " + c.metric.lower() for c in comp)
    assert "cne" in names and "iq" in names
    for c in comp:
        assert c.severity in ("soft", "skipped")
