"""Esquemas de los datos públicos agregados ingeridos (listas de espera, GES, establecimientos).

Todos los modelos son inmutables y rechazan campos desconocidos. Los enums son ``StrEnum``
con valores en inglés. Cada modelo tiene una constante de esquema de polars con las mismas
claves que sus campos, usada al escribir parquet.
"""

from datetime import date
from enum import StrEnum
from typing import Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.health_services import SPECIAL_HEALTH_SERVICE_NAMES


class Grain(StrEnum):
    """Nivel de agregación de una fila."""

    NATIONAL = "national"
    HEALTH_SERVICE = "health_service"
    SPECIALTY = "specialty"
    GES_PROBLEM = "ges_problem"


class CareType(StrEnum):
    """Tipo de prestación: consulta nueva de especialidad (CNE), cirugía (IQ) o sin tipo (GES)."""

    CONSULTATION = "consultation"
    SURGERY = "surgery"
    UNSPECIFIED = "unspecified"


class CareSubtype(StrEnum):
    """Subtipo de prestación."""

    MEDICAL = "medical"
    DENTAL = "dental"
    MAJOR = "major"
    MINOR = "minor"


class GesStatus(StrEnum):
    """Si la fila corresponde a garantías GES o a lista de espera no GES."""

    GES = "ges"
    NON_GES = "non_ges"


class CountUnit(StrEnum):
    """Unidad de ``waiting_count``: registros/interconsultas o garantías."""

    REFERRALS = "referrals"
    GUARANTEES = "guarantees"


class WaitBasis(StrEnum):
    """Base de los tiempos: desde la derivación o retraso sobre el plazo GES."""

    SINCE_REFERRAL = "since_referral"
    DELAY_PAST_GUARANTEE = "delay_past_guarantee"


class Insurer(StrEnum):
    """Aseguradora de salud."""

    FONASA = "fonasa"
    ISAPRE = "isapre"


_FROZEN = ConfigDict(frozen=True, extra="forbid")


class WaitlistRecord(BaseModel):
    """Una cifra agregada de lista de espera publicada en una Glosa 06."""

    model_config = _FROZEN

    period: date
    grain: Grain
    health_service_code: int | None = None
    health_service: str | None = None
    establishment_code: str | None = None
    specialty: str | None = None
    specialty_raw: str | None = None
    ges_problem_code: int | None = None
    ges_problem: str | None = None
    care_type: CareType
    care_subtype: CareSubtype | None = None
    ges_status: GesStatus
    waiting_count: int = Field(ge=0, le=10_000_000)
    count_unit: CountUnit
    persons_count: int | None = Field(default=None, ge=0)
    mean_wait_days: float | None = Field(default=None, ge=0, le=3650)
    median_wait_days: float | None = Field(default=None, ge=0, le=3650)
    wait_basis: WaitBasis | None = None
    extracted_at: date | None = None
    source_id: str
    source_table: str
    source_table_label: str
    source_page: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Valida la coherencia entre grano, identificadores y estadísticos."""
        if self.grain is Grain.HEALTH_SERVICE:
            if self.health_service is None:
                raise ValueError("grano health_service exige health_service")
            if (
                self.health_service_code is None
                and self.health_service not in SPECIAL_HEALTH_SERVICE_NAMES
            ):
                raise ValueError("health_service_code solo puede ser None con nombres especiales")
        elif self.grain is Grain.SPECIALTY:
            if self.specialty is None:
                raise ValueError("grano specialty exige specialty")
        elif self.grain is Grain.GES_PROBLEM:
            if self.ges_problem_code is None:
                raise ValueError("grano ges_problem exige ges_problem_code")
        elif (
            self.health_service is not None
            or self.health_service_code is not None
            or self.specialty is not None
            or self.ges_problem_code is not None
            or self.ges_problem is not None
        ):
            raise ValueError("grano national exige servicio, especialidad y problema en None")
        if self.ges_status is GesStatus.GES and self.care_type is not CareType.UNSPECIFIED:
            raise ValueError("ges_status=ges implica care_type=unspecified")
        if self.persons_count is not None and self.persons_count > self.waiting_count:
            raise ValueError("persons_count no puede superar waiting_count")
        if (
            self.mean_wait_days is not None or self.median_wait_days is not None
        ) and self.wait_basis is None:
            raise ValueError("wait_basis es obligatorio si hay media o mediana")
        return self

    def key(self) -> tuple[object, ...]:
        """Clave única de la fila dentro de una fuente."""
        return (
            self.source_id,
            self.source_table,
            self.grain,
            self.health_service_code,
            self.health_service,
            self.specialty,
            self.ges_problem_code,
            self.care_type,
            self.care_subtype,
        )


class GesCaseRecord(BaseModel):
    """Casos GES acumulados (o ingresos del año) por problema de salud y aseguradora."""

    model_config = _FROZEN

    period: date
    ges_problem_code: int = Field(ge=0, le=99)
    ges_problem: str
    insurer: Insurer
    cumulative_cases: int = Field(ge=0)
    ytd_new_cases: int | None = Field(default=None, ge=0)
    source_id: str
    source_sheet: str


class HealthFacility(BaseModel):
    """Establecimiento de salud del catálogo público (sin dirección ni teléfono)."""

    model_config = _FROZEN

    establishment_code: str
    legacy_code: str | None = None
    name: str
    region_code: int
    region_name: str
    health_service_code: int | None = None
    health_service: str | None = None
    commune_code: str = Field(pattern=r"^\d{4,5}$")
    commune_name: str
    facility_type: str
    care_level: str | None = None
    complexity: str | None = None
    health_system: str | None = None
    belongs_to_snss: bool
    is_operating: bool
    has_emergency: bool
    latitude: float | None = Field(default=None, ge=-56, le=-17)
    longitude: float | None = Field(default=None, ge=-110, le=-66)
    opened_on: date | None = None
    closed_on: date | None = None
    source_id: str


def _schema(
    mapping: dict[str, pl.DataType],
) -> dict[str, pl.DataType]:
    return mapping


_D: pl.DataType = pl.Date()
_I: pl.DataType = pl.Int64()
_F: pl.DataType = pl.Float64()
_S: pl.DataType = pl.String()
_B: pl.DataType = pl.Boolean()

WAITLIST_POLARS_SCHEMA: dict[str, pl.DataType] = _schema(
    {
        "period": _D,
        "grain": _S,
        "health_service_code": _I,
        "health_service": _S,
        "establishment_code": _S,
        "specialty": _S,
        "specialty_raw": _S,
        "ges_problem_code": _I,
        "ges_problem": _S,
        "care_type": _S,
        "care_subtype": _S,
        "ges_status": _S,
        "waiting_count": _I,
        "count_unit": _S,
        "persons_count": _I,
        "mean_wait_days": _F,
        "median_wait_days": _F,
        "wait_basis": _S,
        "extracted_at": _D,
        "source_id": _S,
        "source_table": _S,
        "source_table_label": _S,
        "source_page": _I,
    }
)

GES_CASES_POLARS_SCHEMA: dict[str, pl.DataType] = _schema(
    {
        "period": _D,
        "ges_problem_code": _I,
        "ges_problem": _S,
        "insurer": _S,
        "cumulative_cases": _I,
        "ytd_new_cases": _I,
        "source_id": _S,
        "source_sheet": _S,
    }
)

FACILITY_POLARS_SCHEMA: dict[str, pl.DataType] = _schema(
    {
        "establishment_code": _S,
        "legacy_code": _S,
        "name": _S,
        "region_code": _I,
        "region_name": _S,
        "health_service_code": _I,
        "health_service": _S,
        "commune_code": _S,
        "commune_name": _S,
        "facility_type": _S,
        "care_level": _S,
        "complexity": _S,
        "health_system": _S,
        "belongs_to_snss": _B,
        "is_operating": _B,
        "has_emergency": _B,
        "latitude": _F,
        "longitude": _F,
        "opened_on": _D,
        "closed_on": _D,
        "source_id": _S,
    }
)
