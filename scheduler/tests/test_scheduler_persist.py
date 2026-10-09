"""Persistencia del plan en ``schedule_run`` y ``appointment`` (formulación §9).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional. Ningún dato corresponde a pacientes reales.

Cobertura (sin base de datos, con sesión falsa):
- ``ScheduleRun`` con ``review_status = PENDING``, política, horizonte y parámetros JSON.
- Una fila de ``appointment`` por asignación, con ids uuid5 deterministas.
- ``LookupError`` cuando la corrida sintética no existe.
- Un test marcado ``db`` contra PostgreSQL real (se omite sin conexión).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from scheduler.instance import Block, Entry, SchedulingInstance
from scheduler.persist import APPOINTMENT_NAMESPACE, persist_plan
from scheduler.plan import SchedulePlan
from shared.db.enums import (
    AppointmentOrigin,
    AppointmentStatus,
    Policy,
    ReviewStatus,
)
from shared.db.models import ScheduleRun, SyntheticRun

# ---------------------------------------------------------------------------
# Sesión falsa
# ---------------------------------------------------------------------------


@dataclass
class _FakeSession:
    """Sesión mínima: registra ``add``, ``flush`` y ``execute`` para verificar persistencia."""

    added: list[Any]
    inserted: list[dict[str, Any]]
    synthetic_run: SyntheticRun | None

    def get(self, model: type, pk: uuid.UUID) -> SyntheticRun | None:
        return self.synthetic_run

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def execute(self, stmt: Any, rows: list[dict[str, Any]]) -> None:
        self.inserted.extend(rows)


def _make_session(synthetic_run: SyntheticRun | None) -> _FakeSession:
    return _FakeSession(added=[], inserted=[], synthetic_run=synthetic_run)


# ---------------------------------------------------------------------------
# Instancia con ids uuid
# ---------------------------------------------------------------------------


def _uuid_instance() -> tuple[SchedulingInstance, uuid.UUID]:
    """Instancia chica con ids uuid para que la persistencia acepte ``uuid.UUID(...)``."""
    run_id = uuid.uuid4()
    namespace = run_id
    entries = [
        Entry(
            entry_id=str(uuid.uuid5(namespace, f"entry:{i}")),
            patient_id=str(uuid.uuid5(namespace, f"patient:{i}")),
            health_service_code=1,
            establishment_code="H1",
            specialty_code="cne_medical:x",
            care_type="consultation",
            duration_min=20,
            clinical_priority="p2",
            is_ges=False,
            ges_deadline=None,
            entry_date=date(2025, 8, 1),
            score=40.0,
            rank=i + 1,
        )
        for i in range(3)
    ]
    blocks = [
        Block(
            slot_id=str(uuid.uuid5(namespace, f"slot:{i}")),
            resource_id=str(uuid.uuid5(namespace, f"resource:{i}")),
            resource_kind="specialist_agenda",
            health_service_code=1,
            establishment_code="H1",
            specialty_code="cne_medical:x",
            start_at=datetime(2025, 10, 7 + i, 11, 30, tzinfo=UTC),
            duration_min=60,
            unit_min=20,
        )
        for i in range(2)
    ]
    instance = SchedulingInstance(
        as_of=date(2025, 9, 30),
        horizon_start=date(2025, 10, 6),
        entries=tuple(entries),
        blocks=tuple(blocks),
        noshow={},
        groups={},
        rules_digest="digest-test",
        rules_version="v0",
        seed=42,
    )
    return instance, run_id


def _stub_plan(
    instance: SchedulingInstance,
    *,
    policy: str = "optimized",
    overbooked_entry: str | None = None,
    prob: float = 0.25,
) -> SchedulePlan:
    """Plan mínimo: asigna las tres entradas a los dos bloques, una con sobrecupo."""
    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(instance.entries):
        block = instance.blocks[min(i, len(instance.blocks) - 1)]
        rows.append(
            {
                "entry_id": entry.entry_id,
                "patient_id": entry.patient_id,
                "slot_id": block.slot_id,
                "specialty_code": entry.specialty_code,
                "resource_kind": block.resource_kind,
                "scheduled_start": block.start_at + timedelta(minutes=20 * (i % 3)),
                "duration_min": entry.duration_min,
                "lead_days": (block.local_date - instance.as_of).days,
                "is_overbooked": entry.entry_id == overbooked_entry,
                "predicted_noshow_prob": prob if entry.entry_id == overbooked_entry else 0.05,
                "phase_added": "3b" if entry.entry_id == overbooked_entry else "3a",
                "coef": 1000 + i,
            }
        )
    schema = {
        "entry_id": pl.String,
        "patient_id": pl.String,
        "slot_id": pl.String,
        "specialty_code": pl.String,
        "resource_kind": pl.String,
        "scheduled_start": pl.Datetime("us", "UTC"),
        "duration_min": pl.Int64,
        "lead_days": pl.Int64,
        "is_overbooked": pl.Boolean,
        "predicted_noshow_prob": pl.Float64,
        "phase_added": pl.String,
        "coef": pl.Int64,
    }
    assignments = pl.DataFrame(rows, schema=schema, orient="row")
    report = {
        "policy": policy,
        "summary": {"scheduled": assignments.height},
        "ges": {"met": 0, "unmet": 0, "on_time": 0, "obligated": 0},
    }
    return SchedulePlan(
        policy=policy,
        assignments=assignments,
        explanations=pl.DataFrame(
            schema={
                "entry_id": pl.String,
                "status": pl.String,
                "detail": pl.String,
                "text": pl.String,
            },
        ),
        ges=pl.DataFrame(
            schema={
                "entry_id": pl.String,
                "obligation": pl.String,
                "ges_deadline": pl.Date,
                "met": pl.Boolean,
                "on_time": pl.Boolean,
                "scheduled_date": pl.Date,
                "days_late": pl.Int64,
                "first_possible_date": pl.Date,
                "cause": pl.String,
                "occupants": pl.String,
                "text": pl.String,
            }
        ),
        standby=pl.DataFrame(
            schema={"slot_id": pl.String, "position": pl.Int64, "entry_id": pl.String}
        ),
        report=report,
        solver_status="OPTIMAL",
        objective_value=42.0,
        gap=0.0,
    )


# ---------------------------------------------------------------------------
# Tests sin base de datos
# ---------------------------------------------------------------------------


def test_persist_creates_pending_schedule_run() -> None:
    """El plan se guarda con ``review_status = PENDING`` y política correcta."""
    instance, run_id = _uuid_instance()
    plan = _stub_plan(instance, policy="priority")
    synthetic_run = SyntheticRun(id=run_id)  # type: ignore[call-arg]
    session = _make_session(synthetic_run)

    horizon_end = instance.horizon_start + timedelta(days=7 * 4)
    schedule_id = persist_plan(session, plan, instance, run_id, horizon_end)

    assert isinstance(schedule_id, uuid.UUID)
    assert len(session.added) == 1
    run = session.added[0]
    assert isinstance(run, ScheduleRun)
    assert run.review_status == ReviewStatus.PENDING
    assert run.policy == Policy.PRIORITY
    assert run.horizon_start == instance.horizon_start
    # §9: horizon_end es el último día inclusive (exclusivo - 1 día).
    assert run.horizon_end == horizon_end - timedelta(days=1)
    assert run.run_id == run_id
    assert run.seed == instance.seed
    # Los parámetros deben ser JSON-serializables.
    json.dumps(run.params)


def test_persist_creates_appointments_with_deterministic_ids() -> None:
    """Una fila por asignación, con id uuid5 de ``(schedule_run_id, entry_id)``."""
    instance, run_id = _uuid_instance()
    overbooked = instance.entries[0].entry_id
    plan = _stub_plan(instance, policy="optimized", overbooked_entry=overbooked, prob=0.42)
    synthetic_run = SyntheticRun(id=run_id)  # type: ignore[call-arg]
    session = _make_session(synthetic_run)

    horizon_end = instance.horizon_start + timedelta(days=7 * 4)
    schedule_id = persist_plan(session, plan, instance, run_id, horizon_end)

    assert len(session.inserted) == plan.assignments.height
    for row in session.inserted:
        assert row["origin"] == AppointmentOrigin.SCHEDULER
        assert row["status"] == AppointmentStatus.SCHEDULED
        assert row["schedule_run_id"] == schedule_id
        expected_id = uuid.uuid5(APPOINTMENT_NAMESPACE, f"{schedule_id}:{row['entry_id']}")
        assert row["id"] == expected_id
    flagged = [r for r in session.inserted if r["is_overbooked"]]
    assert len(flagged) == 1
    assert flagged[0]["predicted_noshow_prob"] == pytest.approx(0.42)


def test_persist_without_synthetic_run_raises_lookup_error() -> None:
    """``persist_plan`` falla si la corrida no está en la base (``make synth``)."""
    instance, run_id = _uuid_instance()
    plan = _stub_plan(instance)
    session = _make_session(None)

    horizon_end = instance.horizon_start + timedelta(days=7 * 4)
    with pytest.raises(LookupError, match="no está en la base"):
        persist_plan(session, plan, instance, run_id, horizon_end)


# ---------------------------------------------------------------------------
# Test con PostgreSQL real (marcador ``db``)
# ---------------------------------------------------------------------------


def _admin_engine():
    """Motor admin para crear/borrar la base temporal; ``None`` si no hay PostgreSQL."""
    import sqlalchemy as sa
    from shared.config import get_settings
    from sqlalchemy.engine import make_url

    try:
        url = make_url(get_settings().sqlalchemy_url).set(database="postgres")
    except Exception:
        return None
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError:
        engine.dispose()
        return None
    return engine


@pytest.fixture
def pg_engine(monkeypatch):
    """Motor sobre base temporal migrada; se omite si no hay PostgreSQL alcanzable."""
    import os

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from shared.config import get_settings
    from sqlalchemy.engine import make_url

    admin = _admin_engine()
    if admin is None:
        pytest.skip("No hay PostgreSQL alcanzable")
    scratch = f"prioriza_test_scheduler_persist_{os.getpid()}"
    base_url = make_url(get_settings().sqlalchemy_url)
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        try:
            conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
        except sa.exc.ProgrammingError as exc:
            admin.dispose()
            if "permission denied" in str(exc).lower():
                pytest.skip("El usuario no tiene permiso CREATEDB")
            raise
    url = base_url.set(database=scratch).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "shared/src/shared/db/migrations"))
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.db
def test_persist_against_real_postgresql(pg_engine, tmp_path: Path) -> None:
    """Carga una corrida sintética chica, persiste un plan voraz y verifica filas y FK."""
    import sqlalchemy as sa
    from scheduler.adapters import instance_from_run
    from scheduler.config import OverbookingConfig, SchedulerConfig
    from scheduler.plan import greedy_schedule
    from shared.db.enums import NoShowScenario
    from sqlalchemy.orm import Session
    from synthetic.config import RunConfig
    from synthetic.io import write_parquet
    from synthetic.load import load_dataset
    from synthetic.pipeline import generate

    ds = generate(RunConfig(size=1_000, seed=7, scenario=NoShowScenario.BASELINE))
    load_dataset(ds, pg_engine)
    run_dir = write_parquet(ds, tmp_path)
    cfg = SchedulerConfig(overbooking=OverbookingConfig(enabled=False))
    instance, info = instance_from_run(run_dir, cfg)
    plan = greedy_schedule(instance, cfg, "fifo")
    run_id = uuid.UUID(info.run_id)
    horizon_end = instance.horizon_start + timedelta(days=7 * cfg.horizon_weeks)

    with Session(pg_engine) as session, session.begin():
        schedule_id = persist_plan(session, plan, instance, run_id, horizon_end)

    with pg_engine.connect() as conn:
        run_row = conn.execute(
            sa.text("SELECT policy, review_status, horizon_end FROM schedule_run WHERE id = :i"),
            {"i": schedule_id},
        ).one()
        assert run_row[0] == Policy.FIFO.value
        assert run_row[1] == ReviewStatus.PENDING.value
        assert run_row[2] == horizon_end - timedelta(days=1)
        appt_count = conn.execute(
            sa.text("SELECT count(*) FROM appointment WHERE schedule_run_id = :i"),
            {"i": schedule_id},
        ).scalar_one()
        assert appt_count == plan.assignments.height
        waiting = conn.execute(
            sa.text("SELECT count(*) FROM waitlist_entry WHERE run_id = :r AND status = 'waiting'"),
            {"r": run_id},
        ).scalar_one()
        assert waiting == len(instance.entries)  # el plan pendiente no cambia la lista
