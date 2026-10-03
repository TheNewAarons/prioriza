"""Tests del parser del XLSX de la Superintendencia de Salud (casos GES acumulados)."""

from __future__ import annotations

import re
import zipfile
from datetime import date
from pathlib import Path

import pytest
from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.parsers.sis_ges import parse_sis_ges_xlsx
from ingestion.sources import get_source
from ingestion.validate import validate_ges_cases
from shared.schemas import GesCaseRecord, Insurer

SOURCE_ID = "sis_ges_cases_2026q1"
PERIODS = [
    date(2025, 3, 31),
    date(2025, 6, 30),
    date(2025, 9, 30),
    date(2025, 12, 31),
    date(2026, 3, 31),
]
PROBLEM_CODES = [1, 2, 3, 4, 5]


@pytest.fixture(scope="module")
def mini_xlsx() -> Path:
    return Path(__file__).parent / "fixtures" / "sis_ges" / "sis_ges_cases_mini.xlsx"


@pytest.fixture(scope="module")
def parsed(
    mini_xlsx: Path,
) -> tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]]:
    return parse_sis_ges_xlsx(mini_xlsx, get_source(SOURCE_ID))


def _by_key(records: list[GesCaseRecord]) -> dict[tuple[date, int, Insurer], GesCaseRecord]:
    return {(r.period, r.ges_problem_code, r.insurer): r for r in records}


def test_one_row_per_period_problem_and_insurer(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    records, _ = parsed
    keys = [(r.period, r.ges_problem_code, r.insurer) for r in records]
    assert len(keys) == len(set(keys))
    expected = {(p, c, i) for p in PERIODS for c in PROBLEM_CODES for i in Insurer}
    assert set(keys) == expected
    assert len(records) == 5 * 5 * 2


def test_rows_per_sheet(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    records, _ = parsed
    per_sheet = {
        s: sum(1 for r in records if r.source_sheet == s) for s in ("Año 2025", "Año 2026")
    }
    assert per_sheet == {"Año 2025": 40, "Año 2026": 10}
    assert {r.source_id for r in records} == {SOURCE_ID}


def test_period_is_quarter_end_even_when_the_fonasa_cut_differs(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    """El corte de FONASA de sept-2025 fue el 24, pero el período es el fin de trimestre."""
    records, _ = parsed
    sept = [r for r in records if r.period.month == 9]
    assert {r.period for r in sept} == {date(2025, 9, 30)}
    assert {r.insurer for r in sept} == {Insurer.FONASA, Insurer.ISAPRE}


def test_known_values(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    by_key = _by_key(parsed[0])
    first = by_key[(date(2025, 3, 31), 1, Insurer.FONASA)]
    assert first.cumulative_cases == 90929
    assert first.ges_problem == "Insuficiencia Renal Crónica Terminal"
    assert by_key[(date(2025, 3, 31), 1, Insurer.ISAPRE)].cumulative_cases == 6991
    assert by_key[(date(2025, 12, 31), 3, Insurer.FONASA)].cumulative_cases == 10137845
    latest = by_key[(date(2026, 3, 31), 1, Insurer.FONASA)]
    assert latest.cumulative_cases == 98443
    assert latest.source_sheet == "Año 2026"
    assert by_key[(date(2026, 3, 31), 5, Insurer.ISAPRE)].cumulative_cases == 26670


def test_ytd_new_cases_only_in_the_last_column_of_each_sheet(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    by_key = _by_key(parsed[0])
    assert by_key[(date(2025, 12, 31), 1, Insurer.FONASA)].ytd_new_cases == 7467
    assert by_key[(date(2025, 12, 31), 1, Insurer.ISAPRE)].ytd_new_cases == 654
    assert by_key[(date(2026, 3, 31), 1, Insurer.FONASA)].ytd_new_cases == 1763
    assert by_key[(date(2026, 3, 31), 1, Insurer.ISAPRE)].ytd_new_cases == 99
    with_ytd = {r.period for r in parsed[0] if r.ytd_new_cases is not None}
    assert with_ytd == {date(2025, 12, 31), date(2026, 3, 31)}


def test_sums_equal_total_general(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    records, totals = parsed
    assert set(totals) == {(p, i) for p in PERIODS for i in Insurer}
    for (period, insurer), total in totals.items():
        detail = sum(
            r.cumulative_cases for r in records if r.period == period and r.insurer == insurer
        )
        assert detail == total, (period, insurer)


def test_problem_zero_row_does_not_add_cases(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    """'Sin Problema de Salud Informado' (código 0) viene vacío en el original."""
    assert all(r.cumulative_cases == 0 for r in parsed[0] if r.ges_problem_code == 0)


def test_validation_passes_and_flags_a_tampered_total(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    records, totals = parsed
    source = get_source(SOURCE_ID)
    assert validate_ges_cases(records, totals, source) == []
    tampered = dict(totals)
    key = (date(2026, 3, 31), Insurer.FONASA)
    tampered[key] += 1
    with pytest.raises(DataValidationError) as excinfo:
        validate_ges_cases(records, tampered, source)
    assert SOURCE_ID in str(excinfo.value)


def test_validation_flags_duplicate_keys_and_empty_input(
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    records, totals = parsed
    source = get_source(SOURCE_ID)
    with pytest.raises(DataValidationError):
        validate_ges_cases([*records, records[0]], totals, source)
    with pytest.raises(DataValidationError):
        validate_ges_cases([], {}, source)


# --- deriva del formato: se edita el XLSX (zip) ---------------------------------------------


def _rewrite(src: Path, dest: Path, replacements: dict[str, list[tuple[bytes, bytes]]]) -> Path:
    """Copia el XLSX aplicando reemplazos de bytes sobre partes concretas del zip."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            for old, new in replacements.get(name, []):
                assert old in data, f"{old!r} no está en {name}"
                data = data.replace(old, new)
            zout.writestr(name, data)
    return dest


def _both_sheets(old: bytes, new: bytes) -> dict[str, list[tuple[bytes, bytes]]]:
    """Reemplazo en las hojas 1 y 2 (openpyxl escribe las cadenas en línea)."""
    return {f"xl/worksheets/sheet{n}.xml": [(old, new)] for n in (1, 2)}


def test_renamed_problem_header_raises_schema_drift(mini_xlsx: Path, tmp_path: Path) -> None:
    broken = _rewrite(
        mini_xlsx,
        tmp_path / "broken_header.xlsx",
        _both_sheets(b"PROBLEMA DE SALUD", b"PATOLOGIA"),
    )
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_sis_ges_xlsx(broken, get_source(SOURCE_ID))
    assert SOURCE_ID in str(excinfo.value)
    assert "PROBLEMA DE SALUD" in str(excinfo.value)


def test_missing_sheet_raises_schema_drift(mini_xlsx: Path, tmp_path: Path) -> None:
    broken = _rewrite(
        mini_xlsx,
        tmp_path / "broken_sheet.xlsx",
        {"xl/workbook.xml": [("Año 2026".encode(), "Año 2027".encode())]},
    )
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_sis_ges_xlsx(broken, get_source(SOURCE_ID))
    assert "Año 2026" in str(excinfo.value)


def test_renamed_insurer_columns_raise_schema_drift(mini_xlsx: Path, tmp_path: Path) -> None:
    broken = _rewrite(
        mini_xlsx,
        tmp_path / "broken_insurer.xlsx",
        _both_sheets(b"FONASA", b"FONASAX"),
    )
    with pytest.raises(SchemaDriftError):
        parse_sis_ges_xlsx(broken, get_source(SOURCE_ID))


def _shift_rows(xml: bytes, by: int) -> bytes:
    """Desplaza todas las filas ``by`` hacia abajo (filas, celdas y celdas combinadas)."""
    text = xml.decode("utf-8")
    text = re.sub(r'<row r="(\d+)"', lambda m: f'<row r="{int(m[1]) + by}"', text)
    text = re.sub(
        r'(<c r=")([A-Z]+)(\d+)(")', lambda m: f"{m[1]}{m[2]}{int(m[3]) + by}{m[4]}", text
    )
    text = re.sub(
        r'(<mergeCell ref=")([A-Z]+)(\d+):([A-Z]+)(\d+)(")',
        lambda m: f"{m[1]}{m[2]}{int(m[3]) + by}:{m[4]}{int(m[5]) + by}{m[6]}",
        text,
    )
    return text.encode("utf-8")


def test_header_row_is_detected_not_fixed(
    mini_xlsx: Path,
    tmp_path: Path,
    parsed: tuple[list[GesCaseRecord], dict[tuple[date, Insurer], int]],
) -> None:
    """El índice de la fila de encabezado varía entre archivos: se busca por su texto."""
    shifted = tmp_path / "shifted.xlsx"
    with (
        zipfile.ZipFile(mini_xlsx) as zin,
        zipfile.ZipFile(shifted, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for name in zin.namelist():
            data = zin.read(name)
            if name.startswith("xl/worksheets/sheet"):
                data = _shift_rows(data, 3)
            zout.writestr(name, data)
    records, totals = parse_sis_ges_xlsx(shifted, get_source(SOURCE_ID))
    assert records == parsed[0]
    assert totals == parsed[1]
