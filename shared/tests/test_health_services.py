"""Tests del catálogo de Servicios de Salud y la resolución de nombres (sin red)."""

# ruff: noqa: RUF001  (las variantes con guion largo y comilla tipográfica son los datos)
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from shared.health_services import (
    HEALTH_SERVICES,
    UnknownHealthServiceError,
    resolve_health_service,
)

EXPECTED_CODES = [*range(1, 27), 28, 29, 33]

SAMPLE_CSV = (
    Path(__file__).resolve().parents[2]
    / "ingestion"
    / "tests"
    / "fixtures"
    / "minsal_establishments"
    / "establishments_sample.csv"
)


def test_catalog_has_the_29_services() -> None:
    assert sorted(HEALTH_SERVICES) == EXPECTED_CODES
    assert len(HEALTH_SERVICES) == 29
    assert len(set(HEALTH_SERVICES.values())) == 29


def test_catalog_is_read_only() -> None:
    with pytest.raises(TypeError):
        HEALTH_SERVICES[99] = "Otro"  # type: ignore[index]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("M. Norte", 9),
        ("METROPOLITANO NORTE", 9),
        ("Metropolitano Norte", 9),
        ("M. Occidente", 10),
        ("M. Central", 11),
        ("M. Oriente", 12),
        ("M. Sur", 13),
        ("Metropolitano Suroriente", 14),
        ("METROPOLITANO SUR-ORIENTE", 14),
        ("M. Sur Oriente", 14),
        ("Metropolitano Sur Oriente", 14),
        ("Valparaíso-SA", 6),
        ("Valparaíso – San Antonio", 6),
        ("Valparaíso - San Antonio", 6),
        ("Viña del Mar-Q", 7),
        ("Viña del Mar – Quillota", 7),
        ("Del Maule", 16),
        ("MAULE", 16),
        ("Del Reloncaví", 24),
        ("RELONCAVÍ", 24),
        ("O’Higgins", 15),
        ("O?Higgins", 15),
        ("O'Higgins", 15),
        ("Los Rios", 22),
        ("Los Ríos", 22),
        ("LOS RIOS", 22),
        ("Servicio de Salud  Reloncaví", 24),
        ("Servicio de Salud Metropolitano Sur - Oriente", 14),
        ("Arica y Parinacota", 1),
        ("Tarapacá", 2),
        ("Araucanía Norte", 29),
        ("Araucanía Sur", 21),
        ("Ñuble", 17),
        ("Biobío", 20),
        ("Chiloé", 33),
        ("Arauco", 28),
    ],
)
def test_observed_name_variants_resolve_to_the_right_code(raw: str, code: int) -> None:
    resolved_code, name = resolve_health_service(raw)
    assert resolved_code == code
    assert name == HEALTH_SERVICES[code]


@pytest.mark.parametrize("code", EXPECTED_CODES)
def test_canonical_names_resolve_to_themselves(code: int) -> None:
    name = HEALTH_SERVICES[code]
    for variant in (name, name.upper(), name.lower(), f"Servicio de Salud {name}", f"  {name}  "):
        assert resolve_health_service(variant) == (code, name)


@pytest.mark.parametrize(
    "raw",
    [
        "SERVICIO DE SALUD N/A",
        "Servicio de Salud N/A",
        "N/A",
        "Hospital Digital",
        "HOSPITAL DIGITAL",
    ],
)
def test_special_names_have_no_code(raw: str) -> None:
    assert resolve_health_service(raw) == (None, "NO INFORMADO")


@pytest.mark.parametrize(
    "raw", ["Servicio de Salud Narnia", "Narnia", "", "   ", "Metropolitano", "SEREMI de Salud"]
)
def test_unknown_name_raises(raw: str) -> None:
    with pytest.raises(UnknownHealthServiceError):
        resolve_health_service(raw)


def test_unknown_error_is_a_value_error() -> None:
    assert issubclass(UnknownHealthServiceError, ValueError)
    with pytest.raises(ValueError, match="Narnia"):
        resolve_health_service("Narnia")


def test_names_in_the_establishments_sample_match_their_deis_code() -> None:
    """El catálogo DEIS (E5) es la fuente de verdad de los códigos."""
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    checked = 0
    for row in rows:
        glosa = row["SeremiSaludGlosa_ServicioDeSaludGlosa"]
        if not glosa.startswith("Servicio de Salud"):
            continue
        code, _ = resolve_health_service(glosa)
        assert code == int(row["SeremiSaludCodigo_ServicioDeSaludCodigo"]), glosa
        checked += 1
    assert checked >= 5
