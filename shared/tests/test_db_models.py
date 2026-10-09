"""Tests del modelo de datos: metadata, privacidad y migraciones (offline y contra PostgreSQL)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from shared.config import get_settings
from shared.db import Base
from shared.db.enums import AgeGroup, NoShowScenario
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "health_service",
    "commune",
    "establishment",
    "specialty",
    "ges_problem",
    "procedure",
    "synthetic_run",
    "patient",
    "patient_latent",
    "waitlist_entry",
    "resource",
    "slot",
    "appointment",
    "appointment_truth",
    "schedule_run",
    "plan_review",
    "policy_result",
}

FORBIDDEN_COLUMNS = {
    "name_patient",
    "patient_name",
    "first_name",
    "last_name",
    "rut",
    "run_patient",
    "birth_date",
    "birthdate",
    "date_of_birth",
    "sex",
    "gender",
    "ethnicity",
    "nationality",
}


def _alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "shared/src/shared/db/migrations"))
    return cfg


def test_metadata_has_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_no_forbidden_columns() -> None:
    for table in Base.metadata.tables.values():
        bad = {c.name for c in table.columns} & FORBIDDEN_COLUMNS
        assert not bad, f"{table.name} tiene columnas prohibidas: {bad}"


def test_truth_tables_are_marked() -> None:
    for name in ("patient_latent", "appointment_truth"):
        assert Base.metadata.tables[name].comment == "verdad sintética, prohibido como feature"


def test_enum_values_are_lowercase_strings() -> None:
    assert AgeGroup.AGE_0_14.value == "0_14"
    assert [m.value for m in NoShowScenario] == ["neutral", "baseline", "ses_gradient"]


def test_offline_sql_renders() -> None:
    cfg = _alembic_config()
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, "head", sql=True)
    sql = buffer.getvalue()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table} " in sql


def _admin_engine() -> sa.Engine | None:
    url = make_url(get_settings().sqlalchemy_url).set(database="postgres")
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError:
        engine.dispose()
        return None
    return engine


@pytest.fixture
def scratch_db_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Base temporal aislada: no toca la base de desarrollo."""
    admin = _admin_engine()
    if admin is None:
        pytest.skip("No hay PostgreSQL alcanzable")
    name = "prioriza_test_migrations"
    base_url = make_url(get_settings().sqlalchemy_url)
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base_url.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        yield url
    finally:
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.db
def test_upgrade_downgrade_upgrade(scratch_db_url: str) -> None:
    cfg = _alembic_config()
    engine = sa.create_engine(scratch_db_url)
    try:
        command.upgrade(cfg, "head")
        assert set(sa.inspect(engine).get_table_names()) >= EXPECTED_TABLES
        command.downgrade(cfg, "base")
        assert set(sa.inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(cfg, "head")
        assert set(sa.inspect(engine).get_table_names()) >= EXPECTED_TABLES
    finally:
        engine.dispose()
