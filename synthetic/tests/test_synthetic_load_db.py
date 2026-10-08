"""Carga a PostgreSQL (marcador ``db``; se omite sin PostgreSQL alcanzable).

Usa una base temporal aislada (no toca la de desarrollo) y migra con alembic.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from shared.config import get_settings
from sqlalchemy.engine import make_url
from synthetic.load import LoadError, count_rows, load_dataset

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = "prioriza_test_synthetic_load"
N = 2_000


def _admin_engine():
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
def engine(monkeypatch):
    """Motor sobre una base temporal migrada a head."""
    admin = _admin_engine()
    if admin is None:
        pytest.skip("No hay PostgreSQL alcanzable")
    base_url = make_url(get_settings().sqlalchemy_url)
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{SCRATCH}"'))
    url = base_url.set(database=SCRATCH).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "shared/src/shared/db/migrations"))
    command.upgrade(cfg, "head")
    eng = sa.create_engine(url)
    try:
        yield eng
    finally:
        eng.dispose()
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.db
def test_carga_conteos_y_estado(engine, make_dataset):
    """Tras la carga, los conteos coinciden con los DataFrames y la corrida queda 'ready'."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    run_id = UUID(str(ds.run["id"]))
    counts = count_rows(engine, run_id)
    for name, n in counts.items():
        assert n == ds.tables[name].height, name
    with engine.connect() as conn:
        status, digest = conn.execute(
            sa.text("SELECT status, dataset_sha256 FROM synthetic_run WHERE id = :i"),
            {"i": run_id},
        ).one()
    assert status == "ready" and digest == ds.digest


@pytest.mark.db
def test_carga_repetida_sin_replace_falla(engine, make_dataset):
    """Sin --replace, cargar una corrida existente falla y no duplica filas."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    with pytest.raises(LoadError):
        load_dataset(ds, engine)
    counts = count_rows(engine, UUID(str(ds.run["id"])))
    assert counts["patient"] == ds.tables["patient"].height


@pytest.mark.db
def test_replace_reemplaza_sin_duplicar(engine, make_dataset):
    """Con replace=True se borra en cascada y se recarga: mismos conteos, una sola corrida."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    load_dataset(ds, engine, replace=True)
    counts = count_rows(engine, UUID(str(ds.run["id"])))
    for name, n in counts.items():
        assert n == ds.tables[name].height, name
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM synthetic_run")).scalar_one() == 1


@pytest.mark.db
def test_varias_poblaciones_conviven(engine, make_dataset):
    """Dos corridas distintas (semillas) conviven sin interferir."""
    a, b = make_dataset(N, 11), make_dataset(N, 12)
    load_dataset(a, engine)
    load_dataset(b, engine)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM synthetic_run")).scalar_one() == 2
    assert count_rows(engine, UUID(str(a.run["id"])))["patient"] == a.tables["patient"].height
