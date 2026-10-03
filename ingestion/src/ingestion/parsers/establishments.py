"""Parser del catálogo de establecimientos de salud vigentes (CSV de datos.gob.cl, CC0).

Se descartan a propósito la dirección y el teléfono (minimización de datos).
"""

import re
from datetime import date
from pathlib import Path

import polars as pl
from shared.health_services import UnknownHealthServiceError, resolve_health_service
from shared.schemas import HealthFacility

from ingestion.errors import SchemaDriftError
from ingestion.sources import SourceSpec
from ingestion.validate import require_columns

EXPECTED_COLUMNS: tuple[str, ...] = (
    "EstablecimientoCodigoAntiguo",
    "EstablecimientoCodigo",
    "EstablecimientoCodigoMadreAntiguo",
    "EstablecimientoCodigoMadreNuevo",
    "RegionCodigo",
    "RegionGlosa",
    "SeremiSaludCodigo_ServicioDeSaludCodigo",
    "SeremiSaludGlosa_ServicioDeSaludGlosa",
    "TipoPertenenciaEstabGlosa",
    "TipoEstablecimientoGlosa",
    "AmbitoFuncionamiento",
    "EstablecimientoGlosa",
    "Certificacion",
    "DependenciaAdministrativa",
    "NivelAtencionEstabglosa",
    "ComunaCodigo",
    "ComunaGlosa",
    "TipoViaGlosa",
    "NombreVia",
    "Numero",
    "TelefonoMovil_TelefonoFijo",
    "FechaInicioFuncionamientoEstab",
    "TieneServicioUrgencia",
    "TipoUrgencia",
    "ClasificacionTipoSapu",
    "Latitud",
    "Longitud",
    "TipoSistemaSaludGlosa",
    "EstadoFuncionamiento",
    "NivelComplejidadEstabGlosa",
    "TipoAtencionEstabGlosa",
    "FechaIncorporacion",
    "FechaCierre",
)

_TABLE = "facilities"
_SERVICE_PREFIX = re.compile(r"^servicio de salud\b", re.IGNORECASE)
_DATE_DMY = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")
_DATE_YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _clean(value: str | None) -> str | None:
    """Colapsa espacios y repara ``O?Higgins`` (el origen pierde el apóstrofo)."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"(?<=[Oo])\?(?=[Hh]iggins)", "'", text)
    return text or None


def _float(value: str | None, low: float, high: float) -> float | None:
    """Convierte una coordenada; fuera de rango se descarta (queda ``None``)."""
    if value is None or not value.strip():
        return None
    try:
        number = float(value.strip().replace(",", "."))
    except ValueError:
        return None
    return number if low <= number <= high else None


def _date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        if match := _DATE_DMY.match(text):
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if match := _DATE_YMD.match(text):
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return None


def parse_establishments_csv(path: Path, source: SourceSpec) -> list[HealthFacility]:
    """Lee el CSV (separador ``;``, UTF-8) y devuelve los establecimientos tipados."""
    frame = pl.read_csv(
        path,
        separator=";",
        encoding="utf8",
        infer_schema=False,
        truncate_ragged_lines=False,
    )
    require_columns(frame.columns, EXPECTED_COLUMNS, source_id=source.source_id, table=_TABLE)
    facilities: list[HealthFacility] = []
    for row in frame.iter_rows(named=True):
        service_gloss = _clean(row["SeremiSaludGlosa_ServicioDeSaludGlosa"])
        service_code: int | None = None
        service_name: str | None = None
        if service_gloss is not None and _SERVICE_PREFIX.match(service_gloss):
            try:
                service_code, service_name = resolve_health_service(service_gloss)
            except UnknownHealthServiceError:
                raise SchemaDriftError(
                    source.source_id,
                    _TABLE,
                    "Servicio de Salud desconocido",
                    found=service_gloss,
                ) from None
        pertenece = (_clean(row["TipoPertenenciaEstabGlosa"]) or "").lower()
        status = (_clean(row["EstadoFuncionamiento"]) or "").lower()
        urgency = (_clean(row["TieneServicioUrgencia"]) or "").upper()
        facilities.append(
            HealthFacility(
                establishment_code=(_clean(row["EstablecimientoCodigo"]) or ""),
                legacy_code=_clean(row["EstablecimientoCodigoAntiguo"]),
                name=_clean(row["EstablecimientoGlosa"]) or "",
                region_code=int(row["RegionCodigo"]),
                region_name=_clean(row["RegionGlosa"]) or "",
                health_service_code=service_code,
                health_service=service_name,
                commune_code=(_clean(row["ComunaCodigo"]) or ""),
                commune_name=_clean(row["ComunaGlosa"]) or "",
                facility_type=_clean(row["TipoEstablecimientoGlosa"]) or "",
                care_level=_clean(row["NivelAtencionEstabglosa"]),
                complexity=_clean(row["NivelComplejidadEstabGlosa"]),
                health_system=_clean(row["TipoSistemaSaludGlosa"]),
                belongs_to_snss=pertenece.startswith("perteneciente"),
                is_operating=status.startswith("vigente"),
                has_emergency=urgency in {"SI", "SÍ"},
                latitude=_float(row["Latitud"], -56.0, -17.0),
                longitude=_float(row["Longitud"], -110.0, -66.0),
                opened_on=_date(row["FechaInicioFuncionamientoEstab"]),
                closed_on=_date(row["FechaCierre"]),
                source_id=source.source_id,
            )
        )
    return facilities
