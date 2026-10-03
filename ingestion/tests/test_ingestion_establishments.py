"""Tests del parser del catálogo de establecimientos (CSV de datos.gob.cl, CC0)."""

from __future__ import annotations

import csv
import dataclasses
from datetime import date
from pathlib import Path

import pytest
from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.parsers.establishments import EXPECTED_COLUMNS, parse_establishments_csv
from ingestion.sources import get_source
from ingestion.validate import MIN_FACILITIES, validate_facilities
from shared.schemas import HealthFacility

SOURCE_ID = "minsal_establishments"
BLANKED = ("TelefonoMovil_TelefonoFijo", "TipoViaGlosa", "NombreVia", "Numero")


@pytest.fixture(scope="module")
def sample_csv() -> Path:
    return (
        Path(__file__).parent / "fixtures" / "minsal_establishments" / "establishments_sample.csv"
    )


@pytest.fixture(scope="module")
def raw_rows(sample_csv: Path) -> list[dict[str, str]]:
    with sample_csv.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


@pytest.fixture(scope="module")
def facilities(sample_csv: Path) -> list[HealthFacility]:
    return parse_establishments_csv(sample_csv, get_source(SOURCE_ID))


def _by_code(facilities: list[HealthFacility]) -> dict[str, HealthFacility]:
    return {f.establishment_code: f for f in facilities}


def test_sample_has_all_33_columns_and_no_address_or_phone(
    raw_rows: list[dict[str, str]],
) -> None:
    assert tuple(raw_rows[0]) == EXPECTED_COLUMNS
    assert len(EXPECTED_COLUMNS) == 33
    for row in raw_rows:
        for column in BLANKED:
            assert row[column] == "", column


def test_every_row_is_parsed_with_the_right_types(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    assert len(facilities) == len(raw_rows) >= 14
    codes = [f.establishment_code for f in facilities]
    assert len(set(codes)) == len(codes)
    for f in facilities:
        assert isinstance(f, HealthFacility)
        assert isinstance(f.region_code, int)
        assert f.commune_code.isdigit() and 4 <= len(f.commune_code) <= 5
        assert isinstance(f.belongs_to_snss, bool)
        assert isinstance(f.is_operating, bool)
        assert isinstance(f.has_emergency, bool)
        assert f.source_id == SOURCE_ID
        assert f.opened_on is None or isinstance(f.opened_on, date)
        assert f.name and f.facility_type and f.commune_name and f.region_name


def test_snss_and_private_rows(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    for row in raw_rows:
        expected = row["TipoPertenenciaEstabGlosa"].lower().startswith("perteneciente")
        assert by_code[row["EstablecimientoCodigo"]].belongs_to_snss is expected
    assert any(f.belongs_to_snss for f in facilities)
    assert any(not f.belongs_to_snss for f in facilities)
    # variante en minúsculas: "No perteneciente ..." no debe leerse como perteneciente
    lower = [
        r
        for r in raw_rows
        if r["TipoPertenenciaEstabGlosa"]
        == "No perteneciente al Sistema Nacional de Servicios de Salud"
    ]
    assert lower
    assert all(not by_code[r["EstablecimientoCodigo"]].belongs_to_snss for r in lower)


def test_service_code_only_for_servicio_de_salud_glosas(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    """El código del catálogo se comparte con las SEREMI: solo vale si la glosa es de un SS."""
    by_code = _by_code(facilities)
    seen_service = seen_other = 0
    for row in raw_rows:
        glosa = row["SeremiSaludGlosa_ServicioDeSaludGlosa"]
        facility = by_code[row["EstablecimientoCodigo"]]
        if glosa.startswith("Servicio de Salud"):
            assert facility.health_service_code == int(
                row["SeremiSaludCodigo_ServicioDeSaludCodigo"]
            )
            assert facility.health_service is not None
            seen_service += 1
        else:
            assert facility.health_service_code is None, glosa
            assert facility.health_service is None, glosa
            seen_other += 1
    assert seen_service >= 5
    assert seen_other >= 3


def test_shared_code_06_seremi_vs_servicio(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    code06 = [r for r in raw_rows if r["SeremiSaludCodigo_ServicioDeSaludCodigo"] == "06"]
    seremi = [r for r in code06 if r["SeremiSaludGlosa_ServicioDeSaludGlosa"].startswith("SEREMI")]
    service = [
        r for r in code06 if r["SeremiSaludGlosa_ServicioDeSaludGlosa"].startswith("Servicio")
    ]
    assert seremi
    assert service
    assert all(by_code[r["EstablecimientoCodigo"]].health_service_code is None for r in seremi)
    assert all(by_code[r["EstablecimientoCodigo"]].health_service_code == 6 for r in service)


def test_servicio_names_are_canonical(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    pairs = {
        r["SeremiSaludGlosa_ServicioDeSaludGlosa"]: by_code[r["EstablecimientoCodigo"]]
        for r in raw_rows
    }
    assert pairs["Servicio de Salud  Reloncaví"].health_service == "Reloncaví"  # doble espacio
    assert pairs["Servicio de Salud  Reloncaví"].health_service_code == 24
    assert pairs["Servicio de Salud O'Higgins"].health_service_code == 15
    assert (
        pairs["Servicio de Salud Valparaíso San Antonio"].health_service == "Valparaíso San Antonio"
    )


def test_no_aplica_service_has_no_code(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    rows = [r for r in raw_rows if r["SeremiSaludGlosa_ServicioDeSaludGlosa"] == "No Aplica"]
    assert len(rows) >= 2  # con código vacío y con código 95
    for row in rows:
        facility = by_code[row["EstablecimientoCodigo"]]
        assert facility.health_service_code is None
        assert facility.health_service is None


def test_closed_establishment(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    closed = [r for r in raw_rows if r["EstadoFuncionamiento"] == "Cerrado"]
    assert closed
    for row in closed:
        facility = by_code[row["EstablecimientoCodigo"]]
        assert facility.is_operating is False
        assert isinstance(facility.closed_on, date)
    first = by_code[closed[0]["EstablecimientoCodigo"]]
    day, month, year = closed[0]["FechaCierre"].split("-")
    assert first.closed_on == date(int(year), int(month), int(day))


def test_both_spellings_of_vigente_are_operating(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    variants = {
        r["EstadoFuncionamiento"] for r in raw_rows if r["EstadoFuncionamiento"] != "Cerrado"
    }
    assert variants == {"Vigente en Operación Habitual", "Vigente en operación habitual"}
    for row in raw_rows:
        if row["EstadoFuncionamiento"] != "Cerrado":
            assert by_code[row["EstablecimientoCodigo"]].is_operating is True


def test_missing_coordinates_become_none_and_the_rest_are_in_range(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    empty = [r for r in raw_rows if not r["Latitud"].strip()]
    assert empty
    for row in empty:
        facility = by_code[row["EstablecimientoCodigo"]]
        assert facility.latitude is None
        assert facility.longitude is None
    with_coords = [f for f in facilities if f.latitude is not None]
    assert with_coords
    for f in with_coords:
        assert -56 <= f.latitude <= -17
        assert f.longitude is not None
        assert -110 <= f.longitude <= -66


def test_emergency_flag(facilities: list[HealthFacility], raw_rows: list[dict[str, str]]) -> None:
    by_code = _by_code(facilities)
    values = {r["TieneServicioUrgencia"] for r in raw_rows}
    assert "SI" in values
    assert values - {"SI"}  # y hay filas sin urgencia ("NO", "No Aplica" o vacío)
    for row in raw_rows:
        assert by_code[row["EstablecimientoCodigo"]].has_emergency is (
            row["TieneServicioUrgencia"] == "SI"
        )


def test_question_mark_in_ohiggins_is_repaired(facilities: list[HealthFacility]) -> None:
    """La fuente pierde el apóstrofo ('O?Higgins'); no debe quedar ningún '?' en los textos."""
    for f in facilities:
        for value in (f.name, f.region_name, f.commune_name, f.health_service, f.facility_type):
            assert value is None or "?" not in value


def test_dates_dd_mm_yyyy_are_parsed(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    dated = [r for r in raw_rows if r["FechaInicioFuncionamientoEstab"]]
    assert dated
    row = dated[0]
    day, month, year = row["FechaInicioFuncionamientoEstab"].split("-")
    assert by_code[row["EstablecimientoCodigo"]].opened_on == date(int(year), int(month), int(day))
    undated = [r for r in raw_rows if not r["FechaInicioFuncionamientoEstab"]]
    assert all(by_code[r["EstablecimientoCodigo"]].opened_on is None for r in undated)


def test_blank_legacy_code_is_none(
    facilities: list[HealthFacility], raw_rows: list[dict[str, str]]
) -> None:
    by_code = _by_code(facilities)
    for row in raw_rows:
        expected = row["EstablecimientoCodigoAntiguo"] or None
        assert by_code[row["EstablecimientoCodigo"]].legacy_code == expected


# --- deriva del formato ----------------------------------------------------------------------


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_missing_columns_raise_schema_drift_listing_all_of_them(
    sample_csv: Path, tmp_path: Path
) -> None:
    with sample_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    header, data = rows[0], rows[1:]
    drop = {"Latitud", "ComunaCodigo"}
    keep = [i for i, name in enumerate(header) if name not in drop]
    broken = _write_csv(
        tmp_path / "missing.csv",
        [header[i] for i in keep],
        [[row[i] for i in keep] for row in data],
    )
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_establishments_csv(broken, get_source(SOURCE_ID))
    message = str(excinfo.value)
    assert SOURCE_ID in message
    assert "Latitud" in message
    assert "ComunaCodigo" in message


def test_unknown_servicio_de_salud_raises_schema_drift(sample_csv: Path, tmp_path: Path) -> None:
    with sample_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    header, data = rows[0], rows[1:]
    column = header.index("SeremiSaludGlosa_ServicioDeSaludGlosa")
    for row in data:
        if row[column].startswith("Servicio de Salud"):
            row[column] = "Servicio de Salud Narnia"
            break
    broken = _write_csv(tmp_path / "unknown.csv", header, data)
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_establishments_csv(broken, get_source(SOURCE_ID))
    assert "Narnia" in str(excinfo.value)


def test_validation_requires_a_plausible_catalog_size(facilities: list[HealthFacility]) -> None:
    source = get_source(SOURCE_ID)
    with pytest.raises(DataValidationError):
        validate_facilities(facilities, source)  # la muestra tiene muy pocas filas
    full = [
        facilities[i % len(facilities)].model_copy(update={"establishment_code": f"{100000 + i}"})
        for i in range(MIN_FACILITIES)
    ]
    warnings = validate_facilities(full, source)
    assert isinstance(warnings, list)
    duplicated = [*full, full[0]]
    with pytest.raises(DataValidationError):
        validate_facilities(duplicated, source)


def test_registry_entry_for_the_ckan_source() -> None:
    spec = get_source(SOURCE_ID)
    assert spec.ckan_resource_id == "2c44d782-3365-44e3-aefb-2c8b8363a1bc"
    assert spec.max_cache_age_days == 7
    assert spec.license == "CC0"
    assert dataclasses.is_dataclass(spec)
