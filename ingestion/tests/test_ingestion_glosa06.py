"""Tests del parser de la Glosa 06 sobre volcados de palabras grabados (sin red).

Tres trimestres (III-2025, IV-2025, I-2026) x ocho tablas. Los valores puntuales se
verificaron a mano contra los PDF originales de Minsal.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import Callable
from datetime import date

import pytest
from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.parsers.glosa06 import GLOSA06_TABLES, TableResult, parse_glosa06
from ingestion.parsers.numbers import parse_cl_number
from ingestion.pdf_words import PageWords, Word
from ingestion.sources import get_source
from ingestion.validate import require_columns, validate_waitlist
from shared.health_services import HEALTH_SERVICES
from shared.schemas import (
    CareSubtype,
    CareType,
    CountUnit,
    GesStatus,
    Grain,
    WaitBasis,
    WaitlistRecord,
)

QUARTERS = ["glosa06_2025q3", "glosa06_2025q4", "glosa06_2026q1"]
TABLE_KEYS = [
    "noges_national_by_subtype",
    "cne_by_service",
    "cne_medical_by_specialty",
    "cne_dental_by_specialty",
    "iq_by_service",
    "iq_by_specialty",
    "ges_delayed_by_service",
    "ges_delayed_by_problem",
]
SERVICE_TABLES = ["cne_by_service", "iq_by_service", "ges_delayed_by_service"]
ALL_CODES = set(HEALTH_SERVICES)

Results = dict[str, dict[str, TableResult]]


def _service_row(result: TableResult, code: int) -> WaitlistRecord:
    (row,) = [r for r in result.records if r.health_service_code == code]
    return row


def _specialty_row(result: TableResult, specialty: str) -> WaitlistRecord:
    (row,) = [r for r in result.records if r.specialty == specialty]
    return row


def _national(result: TableResult) -> WaitlistRecord:
    (row,) = [r for r in result.records if r.grain is Grain.NATIONAL]
    return row


# --- estructura general -----------------------------------------------------------------


def test_registry_has_the_eight_tables() -> None:
    assert set(GLOSA06_TABLES) == set(TABLE_KEYS)
    assert set(get_source("glosa06_2026q1").tables) == set(TABLE_KEYS)


@pytest.mark.parametrize("quarter", QUARTERS)
def test_all_eight_tables_are_found_once(glosa_results: Results, quarter: str) -> None:
    assert set(glosa_results[quarter]) == set(TABLE_KEYS)
    for result in glosa_results[quarter].values():
        assert result.records, result.key
        assert result.label.lower().startswith("tabla ")


@pytest.mark.parametrize("quarter", QUARTERS)
def test_cutoff_and_provenance_match_the_source(glosa_results: Results, quarter: str) -> None:
    source = get_source(quarter)
    for result in glosa_results[quarter].values():
        assert result.cutoff == source.period
        for record in result.records:
            assert record.period == source.period
            assert record.source_id == quarter
            assert record.source_table == result.key
            assert record.source_table_label == result.label
            assert record.source_page == result.pages[0]
            assert record.establishment_code is None


@pytest.mark.parametrize("quarter", QUARTERS)
@pytest.mark.parametrize("key", SERVICE_TABLES)
def test_service_tables_have_the_29_services_once(
    glosa_results: Results, quarter: str, key: str
) -> None:
    rows = [r for r in glosa_results[quarter][key].records if r.grain is Grain.HEALTH_SERVICE]
    codes = [r.health_service_code for r in rows if r.health_service_code is not None]
    assert sorted(codes) == sorted(ALL_CODES)
    assert len(codes) == len(set(codes))
    specials = [r for r in rows if r.health_service_code is None]
    if key == "ges_delayed_by_service":
        assert specials, "T6 trae filas especiales (Hospital Digital / N/A)"
    else:
        assert not specials


# Totales publicados en la fila "Total" de cada tabla, leídos del texto de los PDF originales
# (no del parser): la suma del detalle debe coincidir con ellos.
PUBLISHED_WAITING_TOTALS: dict[str, dict[str, int]] = {
    "glosa06_2025q3": {
        "cne_by_service": 2_576_371,
        "cne_medical_by_specialty": 2_051_482,
        "cne_dental_by_specialty": 524_889,
        "iq_by_service": 417_561,
        "iq_by_specialty": 417_561,
        "ges_delayed_by_service": 80_022,
        "ges_delayed_by_problem": 80_022,
    },
    "glosa06_2025q4": {
        "cne_by_service": 2_464_738,
        "cne_medical_by_specialty": 1_952_221,
        "cne_dental_by_specialty": 512_517,
        "iq_by_service": 425_095,
        "iq_by_specialty": 425_095,
        "ges_delayed_by_service": 78_594,
        "ges_delayed_by_problem": 78_594,
    },
    "glosa06_2026q1": {
        "cne_by_service": 2_513_203,
        "cne_medical_by_specialty": 1_981_653,
        "cne_dental_by_specialty": 531_550,
        "iq_by_service": 458_109,
        "iq_by_specialty": 458_109,
        "ges_delayed_by_service": 77_604,
        "ges_delayed_by_problem": 77_604,
    },
}


@pytest.mark.parametrize("quarter", QUARTERS)
@pytest.mark.parametrize("key", [k for k in TABLE_KEYS if k != "noges_national_by_subtype"])
def test_sum_of_records_equals_published_total(
    glosa_results: Results, quarter: str, key: str
) -> None:
    expected = PUBLISHED_WAITING_TOTALS[quarter][key]
    result = glosa_results[quarter][key]
    detail = sum(r.waiting_count for r in result.records if r.grain is not Grain.NATIONAL)
    assert detail == expected
    assert result.totals["waiting_count"] == expected


# Fila "Total" de las tablas por servicio (registros, personas, media, mediana), según el PDF.
PUBLISHED_NATIONAL_ROWS: dict[tuple[str, str], tuple[int, int, float, float]] = {
    ("glosa06_2025q3", "cne_by_service"): (2_576_371, 2_134_364, 341.0, 242.0),
    ("glosa06_2025q4", "cne_by_service"): (2_464_738, 2_047_191, 323.0, 226.0),
    ("glosa06_2026q1", "cne_by_service"): (2_513_203, 2_088_245, 329.0, 236.0),
    ("glosa06_2025q3", "iq_by_service"): (417_561, 365_781, 394.0, 264.0),
    ("glosa06_2025q4", "iq_by_service"): (425_095, 371_907, 378.0, 251.0),
    ("glosa06_2026q1", "iq_by_service"): (458_109, 398_496, 383.0, 259.0),
}


@pytest.mark.parametrize(("quarter", "key"), list(PUBLISHED_NATIONAL_ROWS))
def test_by_service_tables_also_emit_the_national_total(
    glosa_results: Results, quarter: str, key: str
) -> None:
    result = glosa_results[quarter][key]
    national = _national(result)
    waiting, persons, mean, median = PUBLISHED_NATIONAL_ROWS[(quarter, key)]
    assert (national.waiting_count, national.persons_count) == (waiting, persons)
    assert (national.mean_wait_days, national.median_wait_days) == (mean, median)
    assert len(result.records) == 30


@pytest.mark.parametrize("quarter", QUARTERS)
def test_care_type_ges_status_and_units(glosa_results: Results, quarter: str) -> None:
    res = glosa_results[quarter]
    for key in ("cne_by_service", "cne_medical_by_specialty", "cne_dental_by_specialty"):
        for r in res[key].records:
            assert r.care_type is CareType.CONSULTATION
            assert r.ges_status is GesStatus.NON_GES
            assert r.count_unit is CountUnit.REFERRALS
    for key in ("iq_by_service", "iq_by_specialty"):
        for r in res[key].records:
            assert r.care_type is CareType.SURGERY
            assert r.ges_status is GesStatus.NON_GES
    for key in ("ges_delayed_by_service", "ges_delayed_by_problem"):
        for r in res[key].records:
            assert r.care_type is CareType.UNSPECIFIED
            assert r.ges_status is GesStatus.GES
            assert r.count_unit is CountUnit.GUARANTEES
    for r in res["cne_by_service"].records:
        assert r.wait_basis is WaitBasis.SINCE_REFERRAL
    for r in res["ges_delayed_by_problem"].records:
        assert r.wait_basis is WaitBasis.DELAY_PAST_GUARANTEE
    for r in res["cne_medical_by_specialty"].records:
        assert r.care_subtype in (CareSubtype.MEDICAL, None)
    for r in res["cne_dental_by_specialty"].records:
        assert r.care_subtype in (CareSubtype.DENTAL, None)


@pytest.mark.parametrize("quarter", QUARTERS)
def test_specialty_names_are_normalized(glosa_results: Results, quarter: str) -> None:
    for key in ("cne_medical_by_specialty", "cne_dental_by_specialty", "iq_by_specialty"):
        rows = [r for r in glosa_results[quarter][key].records if r.grain is Grain.SPECIALTY]
        assert len(rows) >= 10
        for r in rows:
            assert r.specialty is not None and r.specialty_raw is not None
            assert r.specialty == r.specialty.upper()
            assert "  " not in r.specialty
            assert not any(
                unicodedata.combining(c) for c in unicodedata.normalize("NFD", r.specialty)
            )
        names = [r.specialty for r in rows]
        assert len(names) == len(set(names)), "especialidades duplicadas"


@pytest.mark.parametrize("quarter", QUARTERS)
def test_persons_never_exceed_records_and_are_not_summed(
    glosa_results: Results, quarter: str
) -> None:
    for key in ("cne_by_service", "iq_by_service", "iq_by_specialty"):
        for r in glosa_results[quarter][key].records:
            assert r.persons_count is not None
            assert r.persons_count <= r.waiting_count


@pytest.mark.parametrize("quarter", QUARTERS)
def test_ges_by_problem_codes_are_contiguous(glosa_results: Results, quarter: str) -> None:
    result = glosa_results[quarter]["ges_delayed_by_problem"]
    codes = [r.ges_problem_code for r in result.records if r.grain is Grain.GES_PROBLEM]
    assert codes == sorted(codes)
    assert codes == list(range(1, len(codes) + 1))
    assert len(codes) >= 87
    assert _national(result).waiting_count == result.totals["waiting_count"]


@pytest.mark.parametrize("quarter", QUARTERS)
def test_noges_table_reconciles_with_national_totals(glosa_results: Results, quarter: str) -> None:
    result = glosa_results[quarter]["noges_national_by_subtype"]
    by_sub = {r.care_subtype: r for r in result.records}
    assert set(by_sub) == {
        CareSubtype.MEDICAL,
        CareSubtype.DENTAL,
        CareSubtype.MAJOR,
        CareSubtype.MINOR,
    }
    assert all(r.grain is Grain.NATIONAL for r in result.records)
    cne = by_sub[CareSubtype.MEDICAL].waiting_count + by_sub[CareSubtype.DENTAL].waiting_count
    iq = by_sub[CareSubtype.MAJOR].waiting_count + by_sub[CareSubtype.MINOR].waiting_count
    assert cne == result.totals["cne_registros"]
    assert iq == result.totals["iq_registros"]
    assert cne == glosa_results[quarter]["cne_by_service"].totals["waiting_count"]
    assert iq == glosa_results[quarter]["iq_by_service"].totals["waiting_count"]


# --- valores puntuales verificados contra los PDF -------------------------------------


def test_q3_t12_metropolitano_norte(glosa_results: Results) -> None:
    row = _service_row(glosa_results["glosa06_2025q3"]["cne_by_service"], 9)
    assert row.health_service == "Metropolitano Norte"
    assert (row.waiting_count, row.persons_count) == (136798, 113994)
    assert (row.mean_wait_days, row.median_wait_days) == (610.0, 414.0)
    assert row.source_table_label == "Tabla 12"
    assert row.source_page == 23


def test_q3_t12_national_row(glosa_results: Results) -> None:
    nat = _national(glosa_results["glosa06_2025q3"]["cne_by_service"])
    assert (nat.waiting_count, nat.persons_count) == (2576371, 2134364)
    assert (nat.mean_wait_days, nat.median_wait_days) == (341.0, 242.0)


def test_q3_t18_spans_pages_31_and_32_with_29_services(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2025q3"]["iq_by_service"]
    assert result.pages == (31, 32)
    rows = [r for r in result.records if r.grain is Grain.HEALTH_SERVICE]
    assert len(rows) == 29
    assert result.totals["waiting_count"] == 417561
    # Las personas no son sumables y el propio Minsal las publica distintas entre tablas
    assert result.totals["persons_count"] == 365781


def test_q3_t9_columns_in_published_order_personas_then_registros(
    glosa_results: Results,
) -> None:
    """En III-2025 la columna de personas va antes que la de registros (al revés que IV)."""
    result = glosa_results["glosa06_2025q3"]["noges_national_by_subtype"]
    by_sub = {r.care_subtype: r for r in result.records}
    medical = by_sub[CareSubtype.MEDICAL]
    assert (medical.waiting_count, medical.persons_count) == (2051482, 1730291)
    dental = by_sub[CareSubtype.DENTAL]
    assert (dental.waiting_count, dental.persons_count) == (524889, 500634)
    major = by_sub[CareSubtype.MAJOR]
    assert (major.waiting_count, major.persons_count) == (302093, 265081)
    minor = by_sub[CareSubtype.MINOR]
    assert (minor.waiting_count, minor.persons_count) == (115468, 108381)
    assert result.totals["cne_registros"] == 2576371
    assert result.totals["iq_personas"] == 365118


def test_q4_t9_columns_registros_then_personas(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2025q4"]["noges_national_by_subtype"]
    by_sub = {r.care_subtype: r for r in result.records}
    medical = by_sub[CareSubtype.MEDICAL]
    assert (medical.waiting_count, medical.persons_count) == (1952221, 1651761)
    minor = by_sub[CareSubtype.MINOR]
    assert (minor.waiting_count, minor.persons_count) == (114613, 107681)


def test_q4_t15_infectologia_has_no_thousands_separator(glosa_results: Results) -> None:
    row = _specialty_row(
        glosa_results["glosa06_2025q4"]["cne_medical_by_specialty"], "INFECTOLOGIA"
    )
    assert row.waiting_count == 4062
    assert row.specialty_raw == "INFECTOLOGÍA"
    assert row.grain is Grain.SPECIALTY


def test_q4_t6_label_split_over_two_lines(glosa_results: Results) -> None:
    """'METROPOLITANO / OCCIDENTE' viene partido en dos líneas con las cifras en medio."""
    row = _service_row(glosa_results["glosa06_2025q4"]["ges_delayed_by_service"], 10)
    assert row.health_service == "Metropolitano Occidente"
    assert row.waiting_count == 4298
    result = glosa_results["glosa06_2025q4"]["ges_delayed_by_service"]
    assert result.pages == (21, 22)


def test_q1_t18_valparaiso_san_antonio(glosa_results: Results) -> None:
    row = _service_row(glosa_results["glosa06_2026q1"]["iq_by_service"], 6)
    assert row.health_service == "Valparaíso San Antonio"
    assert row.waiting_count == 16158
    assert row.persons_count == 13868
    assert (row.mean_wait_days, row.median_wait_days) == (350.0, 244.0)


def test_q1_t6_dashes_are_zero_and_hospital_digital_has_no_code(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2026q1"]["ges_delayed_by_service"]
    arica = _service_row(result, 1)
    assert arica.waiting_count == 0  # Arica: "- - - -" en conteos vale 0
    assert arica.mean_wait_days is None  # y en días significa "sin dato", no 0
    digital = [r for r in result.records if r.health_service_code is None]
    assert [(r.health_service, r.waiting_count) for r in digital] == [("HOSPITAL DIGITAL", 5)]
    assert result.totals["waiting_count"] == 77604


def test_q1_t5_problem_10(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2026q1"]["ges_delayed_by_problem"]
    (row,) = [r for r in result.records if r.ges_problem_code == 10]
    assert (row.waiting_count, row.mean_wait_days, row.median_wait_days) == (493, 533.0, 337.0)
    assert row.ges_problem is not None
    assert "escoliosis" in row.ges_problem.lower()
    # el "25" de "menores de 25 años" es parte de la etiqueta, no una cifra
    assert "25" in row.ges_problem
    assert result.totals["waiting_count"] == 77604


def test_q3_t5_problem_10_has_decimal_mean(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2025q3"]["ges_delayed_by_problem"]
    (row,) = [r for r in result.records if r.ges_problem_code == 10]
    assert (row.waiting_count, row.mean_wait_days, row.median_wait_days) == (449, 485.1, 302.0)


def test_q3_t6_ges_delay_total(glosa_results: Results) -> None:
    result = glosa_results["glosa06_2025q3"]["ges_delayed_by_service"]
    assert result.totals["waiting_count"] == 80022


def test_extraction_dates_come_from_the_source_line(glosa_results: Results) -> None:
    assert glosa_results["glosa06_2025q3"]["cne_by_service"].extracted_at == date(2025, 10, 14)
    assert glosa_results["glosa06_2025q4"]["cne_by_service"].extracted_at == date(2026, 1, 20)
    assert glosa_results["glosa06_2026q1"]["cne_by_service"].extracted_at == date(2026, 4, 14)


def test_specialty_names_align_between_q3_and_q1(glosa_results: Results) -> None:
    """Contrato F.2: al menos 95 % de coincidencia de especialidades entre trimestres."""
    first: set[tuple[str, str]] = set()
    last: set[tuple[str, str]] = set()
    for key in ("cne_medical_by_specialty", "cne_dental_by_specialty", "iq_by_specialty"):
        for store, quarter in ((first, "glosa06_2025q3"), (last, "glosa06_2026q1")):
            for r in glosa_results[quarter][key].records:
                if r.grain is Grain.SPECIALTY and r.specialty is not None:
                    store.add((key, r.specialty))
    assert len(first & last) / len(first) >= 0.95


# --- números chilenos -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ("1.234", 1234.0),
        ("1234", 1234.0),
        ("4062", 4062.0),
        ("201,2", 201.2),
        ("1,2", 1.2),
        ("-", 0.0),
        ("0", 0.0),
        ("2.576.371", 2576371.0),
        ("2.576.371**", 2576371.0),
        ("2.134.364*", 2134364.0),
        ("12.345,5", 12345.5),
    ],
)
def test_parse_cl_number(token: str, value: float) -> None:
    assert parse_cl_number(token) == value


@pytest.mark.parametrize("token", ["", "abc", "1.23.4", "--", "1,2,3", "12a", "."])
def test_parse_cl_number_rejects_non_numbers(token: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_cl_number(token)


# --- deriva del formato: se mutan las palabras en memoria --------------------------------

Mutator = Callable[[list[PageWords]], list[PageWords]]
DRIFT_SOURCE = "glosa06_2026q1"
DRIFT_TABLE = "cne_by_service"
DRIFT_PAGE = 26  # Tabla 12 de I-2026 (una sola página)


def _map_page(
    pages: list[PageWords], number: int, fn: Callable[[tuple[Word, ...]], tuple[Word, ...]]
) -> list[PageWords]:
    return [
        dataclasses.replace(p, words=fn(p.words)) if p.page_number == number else p for p in pages
    ]


def _rename(old: str, new: str) -> Mutator:
    def mutate(pages: list[PageWords]) -> list[PageWords]:
        def fn(words: tuple[Word, ...]) -> tuple[Word, ...]:
            found = False
            out = []
            for w in words:
                if not found and w.text == old:
                    out.append(dataclasses.replace(w, text=new))
                    found = True
                else:
                    out.append(w)
            assert found, f"palabra {old!r} no encontrada"
            return tuple(out)

        return _map_page(pages, DRIFT_PAGE, fn)

    return mutate


def _drop_line_starting_with(text: str) -> Mutator:
    def mutate(pages: list[PageWords]) -> list[PageWords]:
        def fn(words: tuple[Word, ...]) -> tuple[Word, ...]:
            (first,) = [w for w in words if w.text == text]
            kept = tuple(w for w in words if abs(w.top - first.top) > 3.0)
            assert len(kept) < len(words)
            return kept

        return _map_page(pages, DRIFT_PAGE, fn)

    return mutate


def _duplicate_page(pages: list[PageWords]) -> list[PageWords]:
    (original,) = [p for p in pages if p.page_number == DRIFT_PAGE]
    return [*pages, dataclasses.replace(original, page_number=99)]


def _break_title_word(pages: list[PageWords]) -> list[PageWords]:
    return _rename("Nueva", "Vieja")(pages)


DRIFT_CASES: list[tuple[str, Mutator]] = [
    ("anchor_missing", _break_title_word),
    ("anchor_duplicated", _duplicate_page),
    ("header_keyword_renamed", _rename("Mediana", "P50")),
    ("unknown_service", _rename("Chiloé", "Narnia")),
    ("cutoff_differs_from_period", _rename("31/03/2026.", "30/04/2026.")),
    ("total_row_missing", _drop_line_starting_with("Total")),
]


@pytest.mark.parametrize(("name", "mutate"), DRIFT_CASES, ids=[c[0] for c in DRIFT_CASES])
def test_format_drift_raises_schema_drift_with_source_and_table(
    glosa_pages: dict[str, list[PageWords]], name: str, mutate: Mutator
) -> None:
    pages = mutate(list(glosa_pages[DRIFT_SOURCE]))
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_glosa06(pages, get_source(DRIFT_SOURCE))
    message = str(excinfo.value)
    assert DRIFT_SOURCE in message, name
    assert DRIFT_TABLE in message, name
    assert excinfo.value.source_id == DRIFT_SOURCE
    assert excinfo.value.table == DRIFT_TABLE


def test_drift_message_tells_the_reader_what_to_do(glosa_pages: dict[str, list[PageWords]]) -> None:
    pages = _rename("Mediana", "P50")(list(glosa_pages[DRIFT_SOURCE]))
    with pytest.raises(SchemaDriftError) as excinfo:
        parse_glosa06(pages, get_source(DRIFT_SOURCE))
    message = str(excinfo.value)
    assert message.startswith(f"[{DRIFT_SOURCE}/{DRIFT_TABLE}]")
    assert "Revise el PDF" in message


def test_untouched_pages_still_parse(glosa_pages: dict[str, list[PageWords]]) -> None:
    """Control de los tests de deriva: sin mutación no hay error."""
    results = parse_glosa06(list(glosa_pages[DRIFT_SOURCE]), get_source(DRIFT_SOURCE))
    assert len(results) == 8


# --- validación de consistencia ---------------------------------------------------------


def _copy(result: TableResult) -> TableResult:
    return dataclasses.replace(result, records=list(result.records), totals=dict(result.totals))


@pytest.mark.parametrize("quarter", QUARTERS)
def test_validate_accepts_real_data(glosa_results: Results, quarter: str) -> None:
    """Los PDF publicados no deben generar ni errores ni advertencias."""
    assert validate_waitlist(list(glosa_results[quarter].values()), get_source(quarter)) == []


def test_validate_flags_a_tampered_total(glosa_results: Results) -> None:
    source = get_source("glosa06_2025q3")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    target = next(r for r in results if r.key == "cne_by_service")
    target.totals["waiting_count"] += 1
    with pytest.raises(DataValidationError) as excinfo:
        validate_waitlist(results, source)
    assert source.source_id in str(excinfo.value)
    assert "cne_by_service" in str(excinfo.value)


def test_validate_flags_a_duplicated_row(glosa_results: Results) -> None:
    source = get_source("glosa06_2026q1")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    target = next(r for r in results if r.key == "cne_medical_by_specialty")
    target.records.append(target.records[0])
    with pytest.raises(DataValidationError) as excinfo:
        validate_waitlist(results, source)
    assert "cne_medical_by_specialty" in str(excinfo.value)


def test_validate_flags_a_missing_service(glosa_results: Results) -> None:
    source = get_source("glosa06_2025q4")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    target = next(r for r in results if r.key == "iq_by_service")
    target.records = [r for r in target.records if r.health_service_code != 10]
    with pytest.raises(DataValidationError):
        validate_waitlist(results, source)


def test_validate_flags_special_rows_outside_t6(glosa_results: Results) -> None:
    source = get_source("glosa06_2026q1")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    target = next(r for r in results if r.key == "cne_by_service")
    extra = target.records[0].model_copy(
        update={
            "health_service_code": None,
            "health_service": "HOSPITAL DIGITAL",
            "waiting_count": 0,
            "persons_count": 0,
        }
    )
    target.records.append(extra)
    with pytest.raises(DataValidationError):
        validate_waitlist(results, source)


def test_validate_flags_cutoff_different_from_period(glosa_results: Results) -> None:
    source = get_source("glosa06_2025q3")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    results[0] = dataclasses.replace(results[0], cutoff=date(2025, 6, 30))
    with pytest.raises(DataValidationError):
        validate_waitlist(results, source)


def test_validate_flags_subtypes_that_do_not_add_up(glosa_results: Results) -> None:
    source = get_source("glosa06_2025q3")
    results = [_copy(r) for r in glosa_results[source.source_id].values()]
    target = next(r for r in results if r.key == "noges_national_by_subtype")
    target.totals["cne_registros"] += 10
    with pytest.raises(DataValidationError):
        validate_waitlist(results, source)


def test_require_columns_lists_every_missing_column() -> None:
    with pytest.raises(SchemaDriftError) as excinfo:
        require_columns(["a", "b"], ["a", "c", "d"], source_id="src", table="tbl")
    message = str(excinfo.value)
    assert "src/tbl" in message
    assert "c" in message
    assert "d" in message
    require_columns(["a", "b", "c"], ["a", "b"], source_id="src", table="tbl")
