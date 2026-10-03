"""Registro de fuentes públicas de entrada (ver ``docs/data-sources.md``)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType


class SourceKind(StrEnum):
    """Formato de la fuente."""

    GLOSA06_PDF = "glosa06_pdf"
    SIS_GES_XLSX = "sis_ges_xlsx"
    CKAN_CSV = "ckan_csv"


@dataclass(frozen=True)
class SourceSpec:
    """Descripción de una fuente: dónde está, cómo verificarla y qué tablas se extraen."""

    source_id: str
    ref: str
    title: str
    publisher: str
    kind: SourceKind
    url: str | None
    ckan_resource_id: str | None
    filename: str
    period: date | None
    expected_sha256: str | None
    license: str
    max_cache_age_days: int | None
    tables: tuple[str, ...]


_GLOSA_TABLES = (
    "noges_national_by_subtype",
    "cne_by_service",
    "cne_medical_by_specialty",
    "cne_dental_by_specialty",
    "iq_by_service",
    "iq_by_specialty",
    "ges_delayed_by_service",
    "ges_delayed_by_problem",
)

_MINSAL = "Ministerio de Salud, Subsecretaría de Redes Asistenciales"
_GLOSA_LICENSE = "No indicada (se cita la fuente; el PDF no se redistribuye)"


def _glosa(source_id: str, ref: str, title: str, url: str, period: date, sha256: str) -> SourceSpec:
    return SourceSpec(
        source_id=source_id,
        ref=ref,
        title=title,
        publisher=_MINSAL,
        kind=SourceKind.GLOSA06_PDF,
        url=url,
        ckan_resource_id=None,
        filename=f"{source_id}.pdf",
        period=period,
        expected_sha256=sha256,
        license=_GLOSA_LICENSE,
        max_cache_age_days=None,
        tables=_GLOSA_TABLES,
    )


SOURCES: Mapping[str, SourceSpec] = MappingProxyType(
    {
        spec.source_id: spec
        for spec in (
            _glosa(
                "glosa06_2025q3",
                "E1",
                "Glosa 06 listas de espera, III trimestre 2025",
                "https://www.minsal.cl/wp-content/uploads/2025/11/"
                "1764018133827_Glosa-06-LE-III-trimestre-2025.pdf",
                date(2025, 9, 30),
                "b4fe13ea8afffd9d47fb33ae3a2f071dc6acc13539dd5094d0f8ba29809c4d7c",
            ),
            _glosa(
                "glosa06_2025q4",
                "E2a",
                "Glosa 06 listas de espera, IV trimestre 2025",
                "https://www.minsal.cl/wp-content/uploads/2026/02/Glosa-06-LE-IV-trimestre.pdf",
                date(2025, 12, 31),
                "4e3dab4685b6c3c396fe30a7cfefce44fc493ad72851e7901bbcdd4aed461c55",
            ),
            _glosa(
                "glosa06_2026q1",
                "E2b",
                "Glosa 06 listas de espera, I trimestre 2026",
                "https://www.minsal.cl/wp-content/uploads/2026/07/"
                "Glosa-06-letra-a-b-c-i-j-k-comun-a-la-partida-1er-trimestre-1.pdf",
                date(2026, 3, 31),
                "eed1e288e8572bc87daefb4b366ebe915fe6b8b0563fc9abec1d746632bafefb",
            ),
            SourceSpec(
                source_id="sis_ges_cases_2026q1",
                ref="E3",
                title="Estadística trimestral de casos GES-AUGE de FONASA e Isapres, marzo 2026",
                publisher="Superintendencia de Salud",
                kind=SourceKind.SIS_GES_XLSX,
                url=(
                    "https://www.superdesalud.gob.cl/app/uploads/2026/07/"
                    "estadistica-trimestral-de-casos-ges-auge-de-fonasa-y-sistema-isapre-"
                    "marzo-2026-1.xlsx"
                ),
                ckan_resource_id=None,
                filename="sis_ges_cases_2026q1.xlsx",
                period=date(2026, 3, 31),
                expected_sha256="60799377e494f31aa2147bc53329cd2cfbfc43540989fb5b12be909b1a2e5352",
                license="No indicada (se cita la fuente; el XLSX no se redistribuye)",
                max_cache_age_days=None,
                tables=("ges_cases",),
            ),
            SourceSpec(
                source_id="minsal_establishments",
                ref="E5",
                title="Establecimientos de salud vigentes",
                publisher="Ministerio de Salud (datos.gob.cl)",
                kind=SourceKind.CKAN_CSV,
                url=None,
                ckan_resource_id="2c44d782-3365-44e3-aefb-2c8b8363a1bc",
                filename="establishments.csv",
                period=None,
                expected_sha256=None,
                license="CC0",
                max_cache_age_days=7,
                tables=("facilities",),
            ),
        )
    }
)


def get_source(source_id: str) -> SourceSpec:
    """Devuelve la fuente registrada o lanza ``KeyError`` con las opciones válidas."""
    try:
        return SOURCES[source_id]
    except KeyError:
        valid = ", ".join(SOURCES)
        raise KeyError(f"Fuente desconocida {source_id!r}. Válidas: {valid}") from None
