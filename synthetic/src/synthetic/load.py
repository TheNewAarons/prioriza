"""Carga de una corrida sintética a PostgreSQL (upsert de catálogos y COPY por lotes)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import polars as pl
from alembic.config import Config
from alembic.script import ScriptDirectory
from shared.db import models
from shared.db.enums import NoShowScenario, RunStatus
from sqlalchemy import Connection, Engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError, ProgrammingError

if TYPE_CHECKING:
    from synthetic.pipeline import SyntheticDataset

BATCH_ROWS = 50_000
# Orden de las tablas por corrida respetando claves foráneas.
RUN_TABLE_ORDER = (
    "patient",
    "patient_latent",
    "waitlist_entry",
    "resource",
    "slot",
    "appointment",
    "appointment_truth",
)
# Catálogo -> (modelo, columnas de la clave primaria), en orden de claves foráneas.
CATALOG_ORDER = (
    ("health_service", models.HealthService),
    ("commune", models.Commune),
    ("establishment", models.Establishment),
    ("specialty", models.Specialty),
    ("ges_problem", models.GesProblem),
    ("procedure", models.Procedure),
)
HINT = "ejecuta `make up && make migrate`"


class LoadError(RuntimeError):
    """Error de carga con un mensaje accionable."""


def _find_alembic_ini() -> Path | None:
    for base in (Path.cwd(), *Path.cwd().parents):
        candidate = base / "alembic.ini"
        if candidate.exists():
            return candidate
    return None


def _expected_head() -> str | None:
    ini = _find_alembic_ini()
    if ini is None:
        return None
    cfg = Config(str(ini))
    cfg.set_main_option(
        "script_location", str(ini.parent / cfg.get_main_option("script_location", ""))
    )
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_database(engine: Engine) -> None:
    """Verifica conexión y que ``alembic_version`` esté en la última revisión."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except OperationalError as exc:
        raise LoadError(f"No se pudo conectar a PostgreSQL: {HINT}.") from exc
    except ProgrammingError as exc:
        raise LoadError(f"La base no tiene migraciones aplicadas: {HINT}.") from exc
    head = _expected_head()
    if version is None or (head is not None and version != head):
        raise LoadError(f"La base está en la revisión {version!r} y la última es {head!r}: {HINT}.")


def upsert_catalogs(conn: Connection, catalogs: dict[str, pl.DataFrame]) -> None:
    """Upsert (``ON CONFLICT DO UPDATE``) de los catálogos globales dentro de la transacción."""
    for name, model in CATALOG_ORDER:
        rows = catalogs[name].to_dicts()
        if not rows:
            continue
        table = model.__table__
        pk = [c.name for c in table.primary_key.columns]
        stmt = insert(table)
        update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in pk}
        stmt = stmt.on_conflict_do_update(index_elements=pk, set_=update_cols)
        conn.execute(stmt, rows)


def _copy_frame(cursor: Any, table: str, frame: pl.DataFrame) -> None:
    columns = ", ".join(frame.columns)
    sql = f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)"
    for offset in range(0, frame.height, BATCH_ROWS):
        chunk = frame.slice(offset, BATCH_ROWS)
        data = chunk.write_csv(include_header=False, datetime_format="%Y-%m-%dT%H:%M:%S%.6f%:z")
        with cursor.copy(sql) as copy:
            copy.write(data.encode("utf-8"))


def load_dataset(ds: SyntheticDataset, engine: Engine, replace: bool = False) -> None:
    """Carga catálogos y tablas de la corrida a PostgreSQL, de forma atómica.

    Todo ocurre en UNA transacción: (con ``replace``) borrado en cascada de la corrida previa,
    upsert de catálogos, inserción de la corrida en ``loading``, COPY de todas las tablas y
    paso a ``ready``. Si algo falla, rollback total y la corrida anterior queda intacta. Sin
    ``replace``, falla si la corrida ya existe.
    """
    check_database(engine)
    run_id = UUID(str(ds.run["id"]))
    with engine.begin() as conn:
        exists = conn.execute(
            select(models.SyntheticRun.id).where(models.SyntheticRun.id == run_id)
        ).first()
        if exists is not None:
            if not replace:
                raise LoadError(
                    f"La corrida {run_id} ya existe en la base; usa --replace para reemplazarla."
                )
            conn.execute(delete(models.SyntheticRun).where(models.SyntheticRun.id == run_id))
        upsert_catalogs(conn, ds.catalogs)
        conn.execute(
            insert(models.SyntheticRun.__table__),
            [
                {
                    "id": run_id,
                    "seed": ds.run["seed"],
                    "size": ds.run["size"],
                    "scenario": NoShowScenario(str(ds.run["scenario"])).value,
                    "as_of": date.fromisoformat(str(ds.run["as_of"])),
                    "horizon_weeks": ds.run["horizon_weeks"],
                    "reference_source_id": ds.run["reference_source_id"],
                    "targets_sha256": ds.run["targets_sha256"],
                    "params_sha256": ds.run["params_sha256"],
                    "dataset_sha256": ds.run["dataset_sha256"],
                    "generator_version": ds.run["generator_version"],
                    "params": ds.run["params"],
                    "status": RunStatus.LOADING.value,
                    "created_at": datetime.now().astimezone(),
                }
            ],
        )
        raw = conn.connection.driver_connection
        assert raw is not None
        with raw.cursor() as cursor:
            for name in RUN_TABLE_ORDER:
                _copy_frame(cursor, name, ds.tables[name])
        conn.execute(
            models.SyntheticRun.__table__.update()
            .where(models.SyntheticRun.id == run_id)
            .values(status=RunStatus.READY.value)
        )


def count_rows(engine: Engine, run_id: UUID) -> dict[str, int]:
    """Filas por tabla de una corrida (útil para verificar la carga)."""
    out: dict[str, int] = {}
    with engine.connect() as conn:
        for name in RUN_TABLE_ORDER:
            out[name] = int(
                conn.execute(
                    text(f"SELECT count(*) FROM {name} WHERE run_id = :r"), {"r": run_id}
                ).scalar_one()
            )
    return out
