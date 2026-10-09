"""Persistencia de un plan en ``schedule_run`` y ``appointment`` (formulación §9).

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Todo plan nace con ``review_status = pending``: requiere revisión humana antes de usarse.
No se cambia el estado de las entradas en espera hasta que un humano apruebe el plan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from shared.db.enums import AppointmentOrigin, AppointmentStatus, Policy, ReviewStatus
from shared.db.models import Appointment, ScheduleRun, SyntheticRun
from sqlalchemy.orm import Session

from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan, code_version

APPOINTMENT_NAMESPACE = uuid.UUID("6f1c2a1e-7d4b-5b8e-9a50-3c2e1f0d9b7a")


def persist_plan(
    session: Session,
    plan: SchedulePlan,
    instance: SchedulingInstance,
    run_id: uuid.UUID,
    horizon_end_exclusive: date,
) -> uuid.UUID:
    """Inserta el plan y sus citas en una transacción del llamador; devuelve el id del plan.

    Falla si la corrida sintética no está cargada en la base (``make synth``).
    """
    if session.get(SyntheticRun, run_id) is None:
        raise LookupError(
            f"la corrida sintética {run_id} no está en la base; cárgala con `make synth`"
        )
    schedule_id = uuid.uuid4()
    session.add(
        ScheduleRun(
            id=schedule_id,
            run_id=run_id,
            policy=Policy(plan.policy),
            horizon_start=instance.horizon_start,
            horizon_end=horizon_end_exclusive - timedelta(days=1),
            seed=instance.seed,
            params=_jsonable(plan.report),
            solver_status=plan.solver_status,
            objective_value=plan.objective_value,
            review_status=ReviewStatus.PENDING,
            code_version=code_version(),
            finished_at=datetime.now(UTC),
        )
    )
    session.flush()
    rows = [
        {
            "id": uuid.uuid5(APPOINTMENT_NAMESPACE, f"{schedule_id}:{r['entry_id']}"),
            "run_id": run_id,
            "patient_id": uuid.UUID(r["patient_id"]),
            "entry_id": uuid.UUID(r["entry_id"]),
            "slot_id": uuid.UUID(r["slot_id"]),
            "schedule_run_id": schedule_id,
            "origin": AppointmentOrigin.SCHEDULER,
            "status": AppointmentStatus.SCHEDULED,
            "scheduled_start": r["scheduled_start"],
            "duration_min": r["duration_min"],
            "lead_days": r["lead_days"],
            "is_overbooked": r["is_overbooked"],
            "predicted_noshow_prob": r["predicted_noshow_prob"],
            "specialty_code": r["specialty_code"],
        }
        for r in plan.assignments.iter_rows(named=True)
    ]
    if rows:
        session.execute(sa.insert(Appointment), rows)
    return schedule_id


def _jsonable(value: Any) -> Any:
    """Convierte claves y valores a tipos JSON (fechas a texto ISO)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value
