"""Privacidad (sin atributos protegidos ni identificadores) y contrato con shared.db."""

from __future__ import annotations

import uuid

import pytest
from shared.db.models import Base

FORBIDDEN = {"name", "rut", "sex", "gender", "ethnicity", "nationality", "birth_date"}
TABLES = {
    "patient",
    "patient_latent",
    "waitlist_entry",
    "resource",
    "slot",
    "appointment",
    "appointment_truth",
}
CATALOGS = {"health_service", "commune", "establishment", "specialty", "ges_problem", "procedure"}


def test_claves_de_tablas(ds1k):
    """Las claves de tables y catalogs son exactamente las del plan (sección 6)."""
    assert set(ds1k.tables) == TABLES
    assert set(ds1k.catalogs) == CATALOGS


def test_sin_columnas_prohibidas(ds1k):
    """Ningún frame tiene name/rut/sex/ethnicity/nationality/birth_date (CLAUDE.md)."""
    for group in (ds1k.tables, ds1k.catalogs):
        for name, df in group.items():
            bad = FORBIDDEN & {c.lower() for c in df.columns}
            if name in {
                "health_service",
                "commune",
                "establishment",
                "specialty",
                "ges_problem",
                "procedure",
            }:
                # Los catálogos públicos sí tienen 'name' (nombres de servicios, no personas).
                bad -= {"name"}
            assert not bad, (name, bad)


@pytest.mark.parametrize(
    "table", ["patient", "patient_latent", "waitlist_entry", "appointment", "appointment_truth"]
)
def test_sin_columna_name_en_tablas_de_personas(ds1k, table):
    """Las tablas con datos por persona no tienen 'name' ni 'rut'."""
    cols = {c.lower() for c in ds1k.tables[table].columns}
    assert "name" not in cols and "rut" not in cols


@pytest.mark.parametrize("table", sorted(TABLES))
def test_ids_son_uuid5(ds1k, table):
    """Los ids/FKs de UUID son UUID válidos versión 5 (deterministas), sin repetidos en la PK."""
    df = ds1k.tables[table]
    pk = (
        "id"
        if "id" in df.columns
        else ("patient_id" if table == "patient_latent" else "appointment_id")
    )
    vals = df[pk].cast(str).to_list()
    assert len(set(vals)) == len(vals)
    for v in vals[:500]:
        assert uuid.UUID(str(v)).version == 5


def test_columnas_igual_a_metadata(ds1k):
    """Columnas de cada frame = columnas de la tabla homónima en Base.metadata."""
    md = Base.metadata.tables
    for name, df in {**ds1k.tables, **ds1k.catalogs}.items():
        assert name in md, name
        assert set(df.columns) == {c.name for c in md[name].columns}, name


def test_verdad_sintetica_separada(ds1k):
    """La verdad latente vive solo en patient_latent y appointment_truth."""
    for name, df in ds1k.tables.items():
        cols = set(df.columns)
        if name not in {"patient_latent", "appointment_truth"}:
            assert "noshow_frailty" not in cols
            assert "true_noshow_prob" not in cols
