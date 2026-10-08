"""N pequeño (1.000): no falla y respeta C1."""

from __future__ import annotations

import pytest
from synthetic.config import RunConfig


def test_n_pequeno_respeta_c1(ds1k, targets, assumptions, m):
    """N=1.000: todos los márgenes de C1 cumplen TVD <= K/(2n) + 1e-9 (K=categorías)."""
    c1 = m.c1_checks(ds1k, targets, assumptions)
    bad = {k: v for k, v in c1.items() if v[0] > v[1]}
    assert not bad, bad


def test_n_pequeno_tamano(ds1k):
    """La lista tiene exactamente N entradas y menos pacientes que entradas."""
    assert ds1k.tables["waitlist_entry"].height == 1_000
    assert 0 < ds1k.tables["patient"].height <= 1_000


def test_n_pequeno_informe_c1(ds1k, targets, assumptions):
    """El informe no tiene chequeos C1 fallidos con N=1.000. Solo se exige C1 (plan sección 7);
    C2/C3/C5 dependen del ruido de muestreo con pocas entradas y no se exigen aquí."""
    from synthetic.validate import calibration_report

    rep = calibration_report(ds1k, targets, assumptions)
    assert [c.name for c in rep.checks if c.group == "C1" and not c.passed] == []


def test_n_menor_al_minimo_falla():
    """size < 1.000 es rechazado por RunConfig."""
    with pytest.raises(ValueError):
        RunConfig(size=999, seed=1)
