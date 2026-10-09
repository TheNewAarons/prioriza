"""`SqlPlanStore` contra PostgreSQL real (marcador `db`; se omite sin base alcanzable).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Verifica que las reglas del dominio y las
restricciones de la base (CHECK de vigente aprobado, índice único parcial, CHECK rol-acción)
coincidan.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from api.auth import Role, User, UserDirectory
from api.jobs import InlineExecutor
from api.main import create_app
from api.plans import InvalidTransition, PermissionDenied
from api.settings import ApiSettings
from api.sql_store import SqlPlanStore
from fastapi.testclient import TestClient
from shared.db.enums import NoShowScenario, ReviewStatus
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.db

GESTOR = User("gestora.test", Role.GESTOR)
REVISOR = User("revisor.test", Role.REVISOR)


@pytest.fixture
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[sa.Engine]:
    """Base temporal migrada con `alembic upgrade head`; se omite sin PostgreSQL."""
    from alembic import command
    from alembic.config import Config
    from shared.config import get_settings
    from sqlalchemy.engine import make_url

    try:
        admin = sa.create_engine(
            make_url(get_settings().sqlalchemy_url).set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        with admin.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError:
        pytest.skip("No hay PostgreSQL alcanzable")
    scratch = f"prioriza_test_api_store_{os.getpid()}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        try:
            conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
        except sa.exc.ProgrammingError:
            admin.dispose()
            pytest.skip("El usuario no tiene permiso CREATEDB")
    url = make_url(get_settings().sqlalchemy_url).set(database=scratch)
    rendered = url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", rendered)
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "shared/src/shared/db/migrations"))
    command.upgrade(cfg, "head")
    engine = sa.create_engine(rendered)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def loaded(pg_engine: sa.Engine, tmp_path: Path) -> tuple[Path, sa.Engine]:
    """Corrida sintética chica cargada en la base y escrita a parquet."""
    from synthetic.config import RunConfig
    from synthetic.io import write_parquet
    from synthetic.load import load_dataset
    from synthetic.pipeline import generate

    ds = generate(RunConfig(size=1000, seed=7, scenario=NoShowScenario.BASELINE, horizon_weeks=4))
    load_dataset(ds, pg_engine)
    return write_parquet(ds, tmp_path / "data"), pg_engine


def _client(run_dir: Path, engine: sa.Engine, tmp_path: Path) -> TestClient:
    store = SqlPlanStore(sessionmaker(bind=engine, expire_on_commit=False))
    users = UserDirectory({"g": GESTOR, "r": REVISOR})
    settings = ApiSettings(run_dir=run_dir, results_dir=tmp_path, models_dir=tmp_path)
    return TestClient(create_app(settings, store=store, executor=InlineExecutor(), users=users))


def test_flow_and_database_constraints(loaded: tuple[Path, sa.Engine], tmp_path: Path) -> None:
    run_dir, engine = loaded
    client = _client(run_dir, engine, tmp_path)
    ids = []
    for _ in range(2):
        job = client.post(
            "/v1/schedule-runs",
            json={"policy": "fifo", "horizon_weeks": 4},
            headers={"X-API-Key": "g"},
        ).json()
        job = client.get(f"/v1/schedule-runs/{job['job_id']}", headers={"X-API-Key": "g"}).json()
        assert job["status"] == "succeeded", job
        ids.append(job["plan_id"])

    for plan_id in ids:
        r = client.post(
            f"/v1/plans/{plan_id}/review",
            json={"decision": "approved", "note": "ok"},
            headers={"X-API-Key": "r"},
        )
        assert r.status_code == 200
    first, second = ids
    assert client.post(f"/v1/plans/{first}/activate", headers={"X-API-Key": "g"}).status_code == 200
    assert (
        client.post(f"/v1/plans/{second}/activate", headers={"X-API-Key": "g"}).status_code == 200
    )
    current = client.get("/v1/plans/current", headers={"X-API-Key": "g"}).json()
    assert current["plan_id"] == second
    assert (
        client.get(f"/v1/plans/{first}", headers={"X-API-Key": "g"}).json()["is_current"] is False
    )
    audit = client.get(f"/v1/plans/{first}/reviews", headers={"X-API-Key": "g"}).json()["items"]
    assert [a["action"] for a in audit] == ["approve", "activate", "deactivate"]
    page = client.get(f"/v1/plans/{first}/assignments?limit=2", headers={"X-API-Key": "g"}).json()
    assert page["total"] > 0
    expl = client.get(f"/v1/plans/{first}/explanations?limit=2", headers={"X-API-Key": "g"}).json()
    assert expl["total"] > 0

    # La base rechaza lo que el dominio ya prohíbe, aunque se salte la API.
    with engine.begin() as conn:
        pending = client.post(
            "/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": "g"}
        ).json()["job_id"]
        plan = client.get(f"/v1/schedule-runs/{pending}", headers={"X-API-Key": "g"}).json()
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.execute(
                sa.text("UPDATE schedule_run SET is_current = true WHERE id = :i"),
                {"i": plan["plan_id"]},
            )
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.execute(
                sa.text("UPDATE schedule_run SET is_current = true WHERE id = :i"),
                {"i": first},
            )  # ya hay otro vigente en la corrida
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.execute(
                sa.text(
                    "INSERT INTO plan_review (id, run_id, schedule_run_id, action, user_name,"
                    " role) SELECT :i, run_id, id, 'approve', 'x', 'gestor' "
                    "FROM schedule_run WHERE id = :p"
                ),
                {"i": uuid.uuid4(), "p": first},
            )  # aprobar con rol gestor


def test_store_rules_in_sql(loaded: tuple[Path, sa.Engine], tmp_path: Path) -> None:
    run_dir, engine = loaded
    client = _client(run_dir, engine, tmp_path)
    store = SqlPlanStore(sessionmaker(bind=engine, expire_on_commit=False))
    job = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": "g"})
    plan_id = uuid.UUID(
        client.get(f"/v1/schedule-runs/{job.json()['job_id']}", headers={"X-API-Key": "g"}).json()[
            "plan_id"
        ]
    )
    with pytest.raises(PermissionDenied):
        store.review(plan_id, GESTOR, ReviewStatus.APPROVED, None)
    with pytest.raises(PermissionDenied):  # cuatro ojos: el revisor es quien lo pidió
        store.review(plan_id, User("gestora.test", Role.REVISOR), ReviewStatus.APPROVED, None)
    with pytest.raises(InvalidTransition):
        store.activate(plan_id, GESTOR, None)
    store.review(plan_id, REVISOR, ReviewStatus.REJECTED, "no")
    with pytest.raises(InvalidTransition):
        store.review(plan_id, REVISOR, ReviewStatus.APPROVED, None)
    with pytest.raises(InvalidTransition):
        store.activate(plan_id, GESTOR, None)
    with Session(engine) as s:
        assert s.execute(sa.text("SELECT count(*) FROM plan_review")).scalar_one() == 1


def test_migrations_match_models(pg_engine: sa.Engine) -> None:
    """La base migrada a `head` coincide con los modelos (revisión de P12, M4: FK faltante)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from shared.db.models import Base

    with pg_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_plan_without_requester_cannot_be_reviewed(
    loaded: tuple[Path, sa.Engine], tmp_path: Path
) -> None:
    """Un plan escrito sin solicitante (CLI `--persist`) no se puede aprobar por la API (A2)."""
    run_dir, engine = loaded
    client = _client(run_dir, engine, tmp_path)
    r = client.post("/v1/schedule-runs", json={"policy": "fifo"}, headers={"X-API-Key": "g"})
    plan_id = uuid.UUID(
        client.get(r.headers["Location"], headers={"X-API-Key": "g"}).json()["plan_id"]
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE schedule_run SET requested_by = NULL WHERE id = :id"), {"id": plan_id}
        )
    store = SqlPlanStore(sessionmaker(bind=engine, expire_on_commit=False))
    with pytest.raises(PermissionDenied):
        store.review(plan_id, REVISOR, ReviewStatus.APPROVED, None)
    assert store.get(plan_id).review_status is ReviewStatus.PENDING
