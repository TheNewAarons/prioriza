"""Validaciones de consistencia de los datos parseados.

Las funciones lanzan :class:`DataValidationError` ante inconsistencias duras (totales que no
cuadran, claves repetidas, servicios faltantes) y devuelven una lista de advertencias para lo
que no invalida los datos pero conviene reportar. Las personas no se validan entre tablas:
no son sumables y el propio Minsal lo advierte.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date

from shared.health_services import HEALTH_SERVICES
from shared.schemas import CareSubtype, GesCaseRecord, Grain, HealthFacility, Insurer

from ingestion.errors import DataValidationError, SchemaDriftError
from ingestion.parsers.glosa06 import TableResult
from ingestion.sources import SourceSpec

#: Tablas por servicio, que deben traer los 29 servicios exactamente una vez.
SERVICE_TABLES: frozenset[str] = frozenset(
    {"cne_by_service", "iq_by_service", "ges_delayed_by_service"}
)
#: Única tabla donde se permiten las filas especiales (Hospital Digital, N/A).
SPECIAL_ROWS_TABLE = "ges_delayed_by_service"
MIN_FACILITIES = 1000


def require_columns(
    found: Sequence[str], expected: Sequence[str], *, source_id: str, table: str
) -> None:
    """Lanza ``SchemaDriftError`` listando las columnas esperadas que faltan."""
    missing = [column for column in expected if column not in found]
    if missing:
        raise SchemaDriftError(
            source_id,
            table,
            "faltan columnas",
            expected=", ".join(missing),
            found=", ".join(found),
        )


def _check_service_coverage(result: TableResult, source: SourceSpec) -> None:
    rows = [r for r in result.records if r.grain is Grain.HEALTH_SERVICE]
    codes = [r.health_service_code for r in rows if r.health_service_code is not None]
    duplicated = sorted({c for c in codes if codes.count(c) > 1})
    if duplicated:
        raise DataValidationError(
            source.source_id, result.key, f"servicios repetidos: {duplicated}"
        )
    missing = sorted(set(HEALTH_SERVICES) - set(codes))
    if missing:
        raise DataValidationError(source.source_id, result.key, f"faltan servicios: {missing}")
    special = [r.health_service for r in rows if r.health_service_code is None]
    if special and result.key != SPECIAL_ROWS_TABLE:
        raise DataValidationError(
            source.source_id, result.key, f"filas especiales no permitidas: {special}"
        )


def _check_totals(result: TableResult, source: SourceSpec) -> None:
    if result.key == "noges_national_by_subtype":
        by_sub = {r.care_subtype: r.waiting_count for r in result.records}
        pairs = (
            ("cne_registros", by_sub[CareSubtype.MEDICAL] + by_sub[CareSubtype.DENTAL]),
            ("iq_registros", by_sub[CareSubtype.MAJOR] + by_sub[CareSubtype.MINOR]),
        )
        for name, total in pairs:
            published = result.totals[name]
            if total != published:
                raise DataValidationError(
                    source.source_id,
                    result.key,
                    f"{name}: subtipos suman {total}, el total publicado es {published:.0f}",
                )
        return
    total = sum(r.waiting_count for r in result.records if r.grain is not Grain.NATIONAL)
    published = result.totals["waiting_count"]
    if total != published:
        raise DataValidationError(
            source.source_id,
            result.key,
            f"la suma de registros ({total}) no cuadra con el Total publicado ({published:.0f})",
        )


def validate_waitlist(results: Sequence[TableResult], source: SourceSpec) -> list[str]:
    """Valida las tablas de una Glosa y devuelve advertencias."""
    warnings: list[str] = []
    for result in results:
        if source.period is not None and result.cutoff != source.period:
            raise DataValidationError(
                source.source_id,
                result.key,
                f"corte {result.cutoff} distinto del período {source.period}",
            )
        keys = [r.key() for r in result.records]
        duplicated = [k for k, n in Counter(keys).items() if n > 1]
        if duplicated:
            raise DataValidationError(
                source.source_id, result.key, f"clave repetida: {duplicated[0]}"
            )
        if result.key in SERVICE_TABLES:
            _check_service_coverage(result, source)
        _check_totals(result, source)

    totals = {r.key: r.totals for r in results}
    cross: list[tuple[str, str, float, str, float]] = []
    if "noges_national_by_subtype" in totals and "cne_by_service" in totals:
        cross.append(
            (
                "CNE: Tabla 9 vs por servicio",
                "cne_by_service",
                totals["cne_by_service"]["waiting_count"],
                "noges_national_by_subtype",
                totals["noges_national_by_subtype"]["cne_registros"],
            )
        )
    if "noges_national_by_subtype" in totals and "iq_by_service" in totals:
        cross.append(
            (
                "IQ: Tabla 9 vs por servicio",
                "iq_by_service",
                totals["iq_by_service"]["waiting_count"],
                "noges_national_by_subtype",
                totals["noges_national_by_subtype"]["iq_registros"],
            )
        )
    if "iq_by_specialty" in totals and "iq_by_service" in totals:
        cross.append(
            (
                "IQ: por especialidad vs por servicio",
                "iq_by_service",
                totals["iq_by_service"]["waiting_count"],
                "iq_by_specialty",
                totals["iq_by_specialty"]["waiting_count"],
            )
        )
    if "ges_delayed_by_problem" in totals and "ges_delayed_by_service" in totals:
        cross.append(
            (
                "GES retrasadas: por problema vs por servicio",
                "ges_delayed_by_service",
                totals["ges_delayed_by_service"]["waiting_count"],
                "ges_delayed_by_problem",
                totals["ges_delayed_by_problem"]["waiting_count"],
            )
        )
    for label, key_a, value_a, key_b, value_b in cross:
        if value_a != value_b:
            warnings.append(
                f"{label}: {key_a}={value_a:.0f} difiere de {key_b}={value_b:.0f} (fuente)"
            )
    if {"cne_medical_by_specialty", "cne_dental_by_specialty", "cne_by_service"} <= totals.keys():
        specialty_sum = (
            totals["cne_medical_by_specialty"]["waiting_count"]
            + totals["cne_dental_by_specialty"]["waiting_count"]
        )
        service_total = totals["cne_by_service"]["waiting_count"]
        if specialty_sum != service_total:
            warnings.append(
                f"CNE: médica+odontológica por especialidad ({specialty_sum:.0f}) difiere del "
                f"total por servicio ({service_total:.0f}) (fuente)"
            )
    return warnings


def validate_ges_cases(
    records: Sequence[GesCaseRecord],
    totals: dict[tuple[date, Insurer], int],
    source: SourceSpec,
) -> list[str]:
    """Valida los casos GES: no vacío, claves únicas y sumas iguales a ``TOTAL GENERAL``."""
    table = "ges_cases"
    if not records:
        raise DataValidationError(source.source_id, table, "no se leyó ningún registro")
    keys = [(r.period, r.ges_problem_code, r.insurer) for r in records]
    if len(keys) != len(set(keys)):
        raise DataValidationError(
            source.source_id, table, "claves (período, problema, aseguradora) repetidas"
        )
    sums: dict[tuple[date, Insurer], int] = {}
    for record in records:
        key = (record.period, record.insurer)
        sums[key] = sums.get(key, 0) + record.cumulative_cases
    for key, total in sorted(totals.items()):
        if sums.get(key) != total:
            raise DataValidationError(
                source.source_id,
                table,
                f"{key[0]} {key[1].value}: suma {sums.get(key)} distinta de TOTAL GENERAL {total}",
            )
    return []


def validate_facilities(facilities: Sequence[HealthFacility], source: SourceSpec) -> list[str]:
    """Valida el catálogo: tamaño mínimo y códigos únicos; advierte coordenadas faltantes."""
    table = "facilities"
    if len(facilities) < MIN_FACILITIES:
        raise DataValidationError(
            source.source_id,
            table,
            f"solo {len(facilities)} establecimientos (se esperaban al menos {MIN_FACILITIES})",
        )
    codes = [f.establishment_code for f in facilities]
    if len(codes) != len(set(codes)):
        raise DataValidationError(source.source_id, table, "códigos de establecimiento repetidos")
    warnings: list[str] = []
    no_coords = sum(1 for f in facilities if f.latitude is None or f.longitude is None)
    if no_coords:
        warnings.append(f"{no_coords} establecimientos sin coordenadas válidas")
    return warnings
