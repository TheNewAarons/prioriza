"""Pruebas de los filtros de formato en español de Chile."""

from __future__ import annotations

import pytest

from reports import fmt


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (0, 0, "0"),
        (1234, 0, "1.234"),
        (2576371, 0, "2.576.371"),
        (1234.5, 1, "1.234,5"),
        (-1234.567, 2, "-1.234,57"),
        (-0.0001, 2, "0,00"),
        (2.675, 2, "2,68"),
        (0.5, 0, "1"),
        (1.5, 0, "2"),
    ],
)
def test_num(value: float, decimals: int, expected: str) -> None:
    assert fmt.num(value, decimals) == expected


def test_num_rechaza_none_y_booleanos() -> None:
    for bad in (None, True, "12", float("nan"), float("inf")):
        with pytest.raises(TypeError):
            fmt.num(bad)


def test_raw_solo_enteros() -> None:
    assert fmt.raw(100000) == "100000"
    with pytest.raises(TypeError):
        fmt.raw(1.5)


def test_pct_y_pp() -> None:
    assert fmt.pct(0.1458) == "14,6 %"
    assert fmt.pct(0.1458, 2) == "14,58 %"
    assert fmt.pct(1) == "100,0 %"
    assert fmt.pp(0.0123) == "+1,2 pp"
    assert fmt.pp(-0.0123, 2) == "-1,23 pp"
    assert fmt.pp(0.0) == "0,0 pp"
    assert fmt.pp(-0.00001) == "0,0 pp"


def test_days_singular_y_plural() -> None:
    assert fmt.days(242) == "242 días"
    assert fmt.days(1) == "1 día"
    assert fmt.days(1234.5, 1) == "1.234,5 días"


def test_signed() -> None:
    assert fmt.signed(1.5, 1) == "+1,5"
    assert fmt.signed(-3) == "-3"
    assert fmt.signed(0) == "0"
    assert fmt.signed(0.04, 1) == "0,0"
    assert fmt.signed(1234567) == "+1.234.567"


def test_sig() -> None:
    assert fmt.sig(0) == "0"
    assert fmt.sig(247.0) == "247"
    assert fmt.sig(0.000006247, 3) == "0,00000625"
    assert fmt.sig(0.1476) == "0,148"
    assert fmt.sig(1e-17) == "0"
    assert fmt.sig(133.4, 3) == "133"


def test_date() -> None:
    assert fmt.date("2025-09-30") == "30-09-2025"
    assert fmt.date("2026-10-09T14:33:20+00:00") == "09-10-2026"
    with pytest.raises(TypeError):
        fmt.date(None)


def test_ci_cuentas_y_tasas() -> None:
    stat = {"mean": 6428.4, "ci95_low": 6400.576, "ci95_high": 6456.224}
    assert fmt.ci(stat) == "6.428,4 (IC 95 % 6.400,6 a 6.456,2)"
    rate = {"mean": 0.154, "ci95_low": 0.152, "ci95_high": 0.156}
    assert fmt.ci(rate, "rate") == "15,4 % (IC 95 % 15,2 % a 15,6 %)"
    diff = {"mean": 0.01, "ci95_low": -0.002, "ci95_high": 0.022}
    assert fmt.ci(diff, "rate", with_sign=True) == "+1,0 pp (IC 95 % -0,2 pp a +2,2 pp)"
    count_diff = {"mean": -5.25, "ci95_low": -9.0, "ci95_high": 0.0}
    assert fmt.ci(count_diff, "count", with_sign=True) == "-5,3 (IC 95 % -9,0 a 0,0)"


def test_ci_errores() -> None:
    with pytest.raises(ValueError):
        fmt.ci({"mean": 1.0, "ci95_low": 0.0, "ci95_high": 2.0}, "otro")
    with pytest.raises(TypeError):
        fmt.ci({"mean": 1.0}, "count")


def test_label_y_cell() -> None:
    assert fmt.label("0_14") == "0-14"
    assert fmt.label("65_plus") == "65+"
    assert fmt.label("fonasa_a") == "fonasa a"
    assert fmt.label("s:1|iq:x") == "s:1\\|iq:x"
    assert fmt.cell("a|b\nc") == "a\\|b c"


def test_show_y_arg() -> None:
    assert fmt.show(True) == "sí"
    assert fmt.show(1000) == "1.000"
    assert fmt.show(0.6) == "0,6"
    assert fmt.show(1.0) == "1"
    assert fmt.show(["p1", 2]) == "p1, 2"
    assert fmt.show(None) == "sin valor"
    assert fmt.arg([1000, 10000]) == "1000,10000"
    assert fmt.arg(120.0) == "120"
    assert fmt.arg(0.1) == "0.1"
    assert fmt.short("32c9e349-74f9") == "32c9e349"
