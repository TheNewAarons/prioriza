"""Tests de los esquemas de datos públicos agregados (sin red)."""

from __future__ import annotations

import types
import typing
from datetime import date
from typing import Any

import polars as pl
import pytest
from pydantic import BaseModel, ValidationError
from shared.schemas import (
    FACILITY_POLARS_SCHEMA,
    GES_CASES_POLARS_SCHEMA,
    WAITLIST_POLARS_SCHEMA,
    CareSubtype,
    CareType,
    CountUnit,
    GesCaseRecord,
    GesStatus,
    Grain,
    HealthFacility,
    Insurer,
    WaitBasis,
    WaitlistRecord,
)


def make_record(**overrides: Any) -> WaitlistRecord:
    """Registro válido de servicio de salud (CNE) con los campos mínimos."""
    base: dict[str, Any] = {
        "period": date(2025, 9, 30),
        "grain": Grain.HEALTH_SERVICE,
        "health_service_code": 9,
        "health_service": "Metropolitano Norte",
        "care_type": CareType.CONSULTATION,
        "ges_status": GesStatus.NON_GES,
        "waiting_count": 136798,
        "count_unit": CountUnit.REFERRALS,
        "persons_count": 113994,
        "mean_wait_days": 610.0,
        "median_wait_days": 414.0,
        "wait_basis": WaitBasis.SINCE_REFERRAL,
        "source_id": "glosa06_2025q3",
        "source_table": "cne_by_service",
        "source_table_label": "Tabla 12",
        "source_page": 23,
    }
    base.update(overrides)
    return WaitlistRecord(**base)


def make_facility(**overrides: Any) -> HealthFacility:
    base: dict[str, Any] = {
        "establishment_code": "113150",
        "name": "Establecimiento de prueba",
        "region_code": 13,
        "region_name": "Metropolitana de Santiago",
        "commune_code": "13402",
        "commune_name": "Comuna de prueba",
        "facility_type": "Hospital",
        "belongs_to_snss": True,
        "is_operating": True,
        "has_emergency": True,
        "latitude": -33.7,
        "longitude": -70.7,
        "source_id": "minsal_establishments",
    }
    base.update(overrides)
    return HealthFacility(**base)


# --- WaitlistRecord ---------------------------------------------------------------------


def test_valid_record_roundtrip() -> None:
    record = make_record()
    assert record.waiting_count == 136798
    assert record.grain is Grain.HEALTH_SERVICE
    assert record.establishment_code is None


def test_record_is_frozen_and_forbids_extra_fields() -> None:
    record = make_record()
    with pytest.raises(ValidationError):
        record.waiting_count = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        make_record(unexpected_field=1)


@pytest.mark.parametrize("value", [-1, 10_000_001])
def test_waiting_count_out_of_range_rejected(value: int) -> None:
    with pytest.raises(ValidationError):
        make_record(waiting_count=value, persons_count=None)


def test_waiting_count_bounds_are_accepted() -> None:
    assert make_record(waiting_count=0, persons_count=0).waiting_count == 0
    assert make_record(waiting_count=10_000_000, persons_count=None).waiting_count == 10_000_000


def test_negative_persons_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(persons_count=-5)


def test_persons_cannot_exceed_records() -> None:
    with pytest.raises(ValidationError):
        make_record(waiting_count=100, persons_count=101)


@pytest.mark.parametrize("field", ["mean_wait_days", "median_wait_days"])
@pytest.mark.parametrize("value", [-0.1, 3650.01, 5000])
def test_wait_days_out_of_range_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_record(**{field: value})


@pytest.mark.parametrize("field", ["mean_wait_days", "median_wait_days"])
def test_wait_days_upper_bound_is_accepted(field: str) -> None:
    assert getattr(make_record(**{field: 3650}), field) == 3650


def test_median_may_exceed_mean() -> None:
    """Hay casos reales con mediana > media: no se exige median <= mean."""
    record = make_record(mean_wait_days=100.0, median_wait_days=150.0)
    assert record.median_wait_days == 150.0


@pytest.mark.parametrize(
    "stats",
    [
        {"mean_wait_days": 10.0, "median_wait_days": None},
        {"mean_wait_days": None, "median_wait_days": 10.0},
        {"mean_wait_days": 10.0, "median_wait_days": 5.0},
    ],
)
def test_wait_basis_required_when_stats_present(stats: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_record(wait_basis=None, **stats)


def test_wait_basis_not_required_without_stats() -> None:
    record = make_record(mean_wait_days=None, median_wait_days=None, wait_basis=None)
    assert record.wait_basis is None


# --- requisitos por grano --------------------------------------------------------------


def test_health_service_grain_requires_name() -> None:
    with pytest.raises(ValidationError):
        make_record(health_service=None)


def test_health_service_code_none_only_with_special_names() -> None:
    ok = make_record(health_service_code=None, health_service="HOSPITAL DIGITAL")
    assert ok.health_service_code is None
    ok2 = make_record(health_service_code=None, health_service="NO INFORMADO")
    assert ok2.health_service == "NO INFORMADO"
    with pytest.raises(ValidationError):
        make_record(health_service_code=None, health_service="Metropolitano Norte")


def test_specialty_grain_requires_specialty() -> None:
    kwargs: dict[str, Any] = {
        "grain": Grain.SPECIALTY,
        "health_service_code": None,
        "health_service": None,
        "persons_count": None,
        "mean_wait_days": None,
        "median_wait_days": None,
        "wait_basis": None,
    }
    with pytest.raises(ValidationError):
        make_record(**kwargs)
    record = make_record(specialty="INFECTOLOGIA", specialty_raw="INFECTOLOGÍA", **kwargs)
    assert record.specialty == "INFECTOLOGIA"


def test_ges_problem_grain_requires_code() -> None:
    kwargs: dict[str, Any] = {
        "grain": Grain.GES_PROBLEM,
        "health_service_code": None,
        "health_service": None,
        "care_type": CareType.UNSPECIFIED,
        "ges_status": GesStatus.GES,
        "count_unit": CountUnit.GUARANTEES,
        "persons_count": None,
        "wait_basis": WaitBasis.DELAY_PAST_GUARANTEE,
    }
    with pytest.raises(ValidationError):
        make_record(**kwargs)
    record = make_record(ges_problem_code=10, ges_problem="Escoliosis", **kwargs)
    assert record.ges_problem_code == 10


def test_national_grain_forbids_service_specialty_and_problem() -> None:
    clean: dict[str, Any] = {
        "grain": Grain.NATIONAL,
        "health_service_code": None,
        "health_service": None,
    }
    assert make_record(**clean).grain is Grain.NATIONAL
    for extra in (
        {"health_service": "Metropolitano Norte"},
        {"health_service_code": 9},
        {"specialty": "CIRUGIA"},
        {"ges_problem_code": 3},
        {"ges_problem": "Algo"},
    ):
        with pytest.raises(ValidationError):
            make_record(**{**clean, **extra})


def test_ges_status_implies_unspecified_care_type() -> None:
    with pytest.raises(ValidationError):
        make_record(ges_status=GesStatus.GES, care_type=CareType.CONSULTATION)
    ok = make_record(ges_status=GesStatus.GES, care_type=CareType.UNSPECIFIED)
    assert ok.ges_status is GesStatus.GES


def test_unknown_enum_value_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(grain="region")
    with pytest.raises(ValidationError):
        make_record(count_unit="people")


def test_enum_values_are_english_strings() -> None:
    assert [g.value for g in Grain] == ["national", "health_service", "specialty", "ges_problem"]
    assert {c.value for c in CareType} == {"consultation", "surgery", "unspecified"}
    assert {c.value for c in CareSubtype} == {"medical", "dental", "major", "minor"}
    assert {c.value for c in GesStatus} == {"ges", "non_ges"}
    assert {c.value for c in CountUnit} == {"referrals", "guarantees"}
    assert {c.value for c in WaitBasis} == {"since_referral", "delay_past_guarantee"}
    assert {c.value for c in Insurer} == {"fonasa", "isapre"}
    assert Grain.NATIONAL == "national"  # StrEnum


def test_unique_key_distinguishes_rows() -> None:
    a = make_record()
    b = make_record(health_service_code=10, health_service="Metropolitano Occidente")
    c = make_record(care_type=CareType.SURGERY)
    assert a.key() == make_record().key()
    assert len({a.key(), b.key(), c.key()}) == 3


# --- GesCaseRecord y HealthFacility ----------------------------------------------------


def test_ges_case_record_validation() -> None:
    record = GesCaseRecord(
        period=date(2026, 3, 31),
        ges_problem_code=1,
        ges_problem="Insuficiencia Renal Crónica Terminal",
        insurer=Insurer.FONASA,
        cumulative_cases=98443,
        ytd_new_cases=None,
        source_id="sis_ges_cases_2026q1",
        source_sheet="Año 2026",
    )
    assert record.insurer is Insurer.FONASA
    for bad in ({"cumulative_cases": -1}, {"ges_problem_code": 100}, {"ytd_new_cases": -1}):
        data = record.model_dump() | bad
        with pytest.raises(ValidationError):
            GesCaseRecord(**data)
    with pytest.raises(ValidationError):
        GesCaseRecord(**(record.model_dump() | {"extra": 1}))


def test_facility_valid_and_optional_fields() -> None:
    facility = make_facility(latitude=None, longitude=None)
    assert facility.latitude is None
    assert facility.health_service_code is None


@pytest.mark.parametrize("code", ["123", "123456", "ABCDE", "1 345", ""])
def test_facility_commune_code_pattern(code: str) -> None:
    with pytest.raises(ValidationError):
        make_facility(commune_code=code)


@pytest.mark.parametrize("code", ["1101", "13402"])
def test_facility_commune_code_accepts_four_or_five_digits(code: str) -> None:
    assert make_facility(commune_code=code).commune_code == code


@pytest.mark.parametrize(
    ("field", "value"),
    [("latitude", -16.9), ("latitude", -56.1), ("longitude", -65.9), ("longitude", -110.1)],
)
def test_facility_coordinates_out_of_chile_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_facility(**{field: value})


def test_facility_has_no_address_or_phone_fields() -> None:
    """Minimización: no se guardan dirección ni teléfono."""
    names = set(HealthFacility.model_fields)
    forbidden = {"address", "street", "phone", "telephone", "number", "street_name"}
    assert not names & forbidden
    with pytest.raises(ValidationError):
        make_facility(phone="123")


# --- esquemas polars --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "schema"),
    [
        (WaitlistRecord, WAITLIST_POLARS_SCHEMA),
        (GesCaseRecord, GES_CASES_POLARS_SCHEMA),
        (HealthFacility, FACILITY_POLARS_SCHEMA),
    ],
)
def test_polars_schema_keys_match_model_fields(
    model: type[BaseModel], schema: dict[str, pl.DataType]
) -> None:
    assert set(schema) == set(model.model_fields)
    assert list(schema) == list(model.model_fields), "mismo orden que los campos del modelo"


def _expected_dtype(annotation: Any) -> type[pl.DataType]:
    """Mapeo del contrato: date->Date, int->Int64, float->Float64, str->String, bool->Boolean."""
    args = typing.get_args(annotation)
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        (inner,) = [a for a in args if a is not type(None)]
        return _expected_dtype(inner)
    if annotation is bool:
        return pl.Boolean
    if annotation is date:
        return pl.Date
    if annotation is int:
        return pl.Int64
    if annotation is float:
        return pl.Float64
    if annotation is str or (isinstance(annotation, type) and issubclass(annotation, str)):
        return pl.String
    raise AssertionError(f"tipo sin mapeo: {annotation!r}")


@pytest.mark.parametrize(
    ("model", "schema"),
    [
        (WaitlistRecord, WAITLIST_POLARS_SCHEMA),
        (GesCaseRecord, GES_CASES_POLARS_SCHEMA),
        (HealthFacility, FACILITY_POLARS_SCHEMA),
    ],
)
def test_polars_schema_dtypes_follow_contract(
    model: type[BaseModel], schema: dict[str, pl.DataType]
) -> None:
    for name, field in model.model_fields.items():
        assert schema[name] == _expected_dtype(field.annotation), name


def test_polars_schema_builds_an_empty_frame() -> None:
    for schema in (WAITLIST_POLARS_SCHEMA, GES_CASES_POLARS_SCHEMA, FACILITY_POLARS_SCHEMA):
        frame = pl.DataFrame(schema=schema)
        assert frame.height == 0
        assert frame.columns == list(schema)
