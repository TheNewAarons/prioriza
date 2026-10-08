"""Carga a PostgreSQL (marcador ``db``; se omite sin PostgreSQL alcanzable).

Usa una base temporal aislada (no toca la de desarrollo) y migra con alembic.
"""

from __future__ import annotations

import os
from datetime import UTC, date
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
import synthetic.load as load_mod
from alembic import command
from alembic.config import Config
from shared.config import get_settings
from sqlalchemy.engine import make_url
from synthetic.load import LoadError, count_rows, load_dataset

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = f"prioriza_test_synthetic_load_{os.getpid()}"
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
        try:
            conn.execute(sa.text(f'CREATE DATABASE "{SCRATCH}"'))
        except sa.exc.ProgrammingError as exc:
            admin.dispose()
            if "permission denied" in str(exc).lower():
                pytest.skip("El usuario no tiene permiso CREATEDB")
            raise
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


def _status_and_counts(engine, run_id):
    with engine.connect() as conn:
        status = conn.execute(
            sa.text("SELECT status FROM synthetic_run WHERE id = :i"), {"i": run_id}
        ).scalar_one()
    return status, count_rows(engine, run_id)


@pytest.mark.db
def test_fallo_a_mitad_de_replace_deja_corrida_previa_intacta(engine, make_dataset, monkeypatch):
    """B5a: si el COPY de una tabla falla durante --replace, hay rollback total: la corrida
    anterior sigue 'ready' con los mismos conteos."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    run_id = UUID(str(ds.run["id"]))
    antes = _status_and_counts(engine, run_id)
    assert antes[0] == "ready"

    original = load_mod._copy_frame

    def falla_en_slot(cursor, table, frame):
        if table == "slot":
            raise RuntimeError("fallo forzado en COPY de slot")
        original(cursor, table, frame)

    monkeypatch.setattr(load_mod, "_copy_frame", falla_en_slot)
    with pytest.raises(RuntimeError, match="fallo forzado"):
        load_dataset(ds, engine, replace=True)
    monkeypatch.setattr(load_mod, "_copy_frame", original)
    assert _status_and_counts(engine, run_id) == antes


@pytest.mark.db
def test_timestamps_con_zona_horaria_identicos_tras_copy(engine, make_dataset):
    """B5b: slot.start_at y appointment.scheduled_start vuelven idénticos (instantes UTC)."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    for table, col in (("slot", "start_at"), ("appointment", "scheduled_start")):
        with engine.connect() as conn:
            rows = conn.execute(sa.text(f"SELECT id, {col} FROM {table}")).all()
        db = {str(i): t for i, t in rows}
        frame = ds.tables[table]
        assert len(db) == frame.height
        for i, t in zip(frame["id"].to_list(), frame[col].to_list(), strict=True):
            assert t.tzinfo is not None
            assert db[str(i)].tzinfo is not None
            assert db[str(i)].astimezone(UTC) == t.astimezone(UTC), (table, i)


def _insert_schedule_run(engine, run_id):
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO schedule_run (id, run_id, policy, horizon_start, horizon_end, "
                "seed, params, code_version) VALUES (gen_random_uuid(), :r, 'fifo', :a, :b, "
                "1, '{}', 'test')"
            ),
            {"r": run_id, "a": date(2026, 1, 1), "b": date(2026, 2, 1)},
        )


@pytest.mark.db
def test_replace_con_schedule_run_aborta_sin_borrar(engine, make_dataset):
    """B5c: --replace con un schedule_run existente aborta con error claro y no borra nada."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    run_id = UUID(str(ds.run["id"]))
    _insert_schedule_run(engine, run_id)
    antes = _status_and_counts(engine, run_id)
    with pytest.raises(LoadError, match="drop-downstream"):
        load_dataset(ds, engine, replace=True)
    assert _status_and_counts(engine, run_id) == antes
    with engine.connect() as conn:
        n = conn.execute(sa.text("SELECT count(*) FROM schedule_run")).scalar_one()
    assert n == 1


@pytest.mark.db
def test_replace_con_drop_downstream_procede(engine, make_dataset):
    """B5c: con drop_downstream=True se reemplaza y el plan derivado se borra."""
    ds = make_dataset(N, 11)
    load_dataset(ds, engine)
    run_id = UUID(str(ds.run["id"]))
    _insert_schedule_run(engine, run_id)
    load_dataset(ds, engine, replace=True, drop_downstream=True)
    status, counts = _status_and_counts(engine, run_id)
    assert status == "ready"
    assert counts["patient"] == ds.tables["patient"].height
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM schedule_run")).scalar_one() == 0
