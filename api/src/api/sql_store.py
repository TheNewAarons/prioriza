"""Almacén de planes sobre PostgreSQL.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Guarda el plan con `scheduler.persist.persist_plan` (`schedule_run` pendiente y `appointment`),
la auditoría en `plan_review` y las explicaciones en `schedule_run.params["api"]`. Las reglas
son las de `plans.py` (se aplican con la fila bloqueada); la base las refuerza con el CHECK
`NOT is_current OR review_status = 'approved'`, el índice único parcial de un vigente por
corrida y el CHECK que liga acción y rol en `plan_review`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from scheduler.persist import persist_plan
from shared.db.enums import ReviewAction, ReviewStatus
from shared.db.models import Appointment, PlanReview, ScheduleRun
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer, sessionmaker

from api.auth import User
from api.plans import (
    EXPLANATION_COLUMNS,
    InvalidTransition,
    NewPlan,
    NotFound,
    Page,
    PlanRecord,
    ReviewRecord,
    check_activate,
    check_review,
    project_explanations,
)

_API_KEY = "api"


class SqlPlanStore:
    """`PlanStore` sobre PostgreSQL; requiere la corrida sintética cargada (`make synth`)."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    # ------------------------------------------------------------------ lectura

    @staticmethod
    def _record(row: ScheduleRun, *, with_report: bool = True) -> PlanRecord:
        """Plan desde la fila; sin `with_report` no toca `params` (JSONB grande, diferido)."""
        params: dict[str, Any] = dict(row.params) if with_report else {}
        extra: dict[str, Any] = params.pop(_API_KEY, {})
        return PlanRecord(
            id=row.id,
            run_id=str(row.run_id),
            policy=row.policy.value,
            requested_by=row.requested_by,
            created_at=row.created_at,
            review_status=row.review_status,
            is_current=row.is_current,
            solver_status=row.solver_status,
            objective_value=row.objective_value,
            horizon_start=row.horizon_start,
            horizon_end=row.horizon_end,
            report=params,
            config=extra.get("config", {}),
        )

    @staticmethod
    def _row(session: Session, plan_id: uuid.UUID, *, lock: bool = False) -> ScheduleRun:
        stmt = sa.select(ScheduleRun).where(ScheduleRun.id == plan_id)
        if lock:
            stmt = stmt.with_for_update()
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise NotFound(f"no existe el plan {plan_id}")
        return row

    def get(self, plan_id: uuid.UUID) -> PlanRecord:
        with self._factory() as session:
            return self._record(self._row(session, plan_id))

    def list_plans(
        self,
        *,
        review_status: ReviewStatus | None = None,
        current: bool | None = None,
        run_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[PlanRecord]:
        conds: list[sa.ColumnElement[bool]] = []
        if review_status is not None:
            conds.append(ScheduleRun.review_status == review_status)
        if current is not None:
            conds.append(ScheduleRun.is_current.is_(current))
        if run_id is not None:
            conds.append(ScheduleRun.run_id == uuid.UUID(run_id))
        with self._factory() as session:
            total = session.execute(
                sa.select(sa.func.count()).select_from(ScheduleRun).where(*conds)
            ).scalar_one()
            rows = (
                session.execute(
                    sa.select(ScheduleRun)
                    .options(defer(ScheduleRun.params))
                    .where(*conds)
                    .order_by(ScheduleRun.created_at.desc(), ScheduleRun.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            # Los listados no necesitan el informe: `params` (con las explicaciones) no se lee.
            return Page([self._record(r, with_report=False) for r in rows], int(total))

    def current(self, run_id: str | None = None) -> PlanRecord | None:
        page = self.list_plans(current=True, run_id=run_id, limit=1)
        return self.get(page.items[0].id) if page.items else None

    def assignments(self, plan_id: uuid.UUID, *, limit: int, offset: int) -> Page[dict[str, Any]]:
        with self._factory() as session:
            self._row(session, plan_id)
            total = session.execute(
                sa.select(sa.func.count())
                .select_from(Appointment)
                .where(Appointment.schedule_run_id == plan_id)
            ).scalar_one()
            rows = session.execute(
                sa.select(
                    Appointment.entry_id,
                    Appointment.patient_id,
                    Appointment.slot_id,
                    Appointment.specialty_code,
                    Appointment.scheduled_start,
                    Appointment.duration_min,
                    Appointment.lead_days,
                    Appointment.is_overbooked,
                    Appointment.predicted_noshow_prob,
                )
                .where(Appointment.schedule_run_id == plan_id)
                .order_by(Appointment.scheduled_start, Appointment.entry_id)
                .limit(limit)
                .offset(offset)
            ).all()
        items = [
            {
                **r._asdict(),
                "entry_id": str(r.entry_id),
                "patient_id": str(r.patient_id),
                "slot_id": str(r.slot_id),
            }
            for r in rows
        ]
        return Page(items, int(total))

    def explanations(
        self, plan_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> Page[dict[str, Any]]:
        with self._factory() as session:
            row = self._row(session, plan_id)
            stored: list[dict[str, Any]] = row.params.get(_API_KEY, {}).get("explanations", [])
        rows = [r for r in stored if status is None or r["status"] == status]
        rows.sort(key=lambda r: str(r["entry_id"]))
        return Page(rows[offset : offset + limit], len(rows))

    def reviews(self, plan_id: uuid.UUID) -> list[ReviewRecord]:
        with self._factory() as session:
            row = self._row(session, plan_id)
            rows = (
                session.execute(
                    sa.select(PlanReview)
                    .where(
                        PlanReview.run_id == row.run_id,
                        PlanReview.schedule_run_id == plan_id,
                    )
                    .order_by(PlanReview.created_at, PlanReview.id)
                )
                .scalars()
                .all()
            )
            return [
                ReviewRecord(
                    id=r.id,
                    plan_id=r.schedule_run_id,
                    action=r.action,
                    user_name=r.user_name,
                    role=r.role,
                    note=r.note,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    # ------------------------------------------------------------------ escritura

    def add(self, new: NewPlan) -> PlanRecord:
        explanations = project_explanations(new.plan.explanations)
        with self._factory() as session, session.begin():
            plan_id = persist_plan(
                session,
                new.plan,
                new.instance,
                uuid.UUID(new.run_id),
                new.horizon_end_exclusive,
            )
            row = self._row(session, plan_id)
            row.requested_by = new.requested_by
            row.params = {
                **row.params,
                _API_KEY: {
                    "config": new.config,
                    "explanations": explanations.select(EXPLANATION_COLUMNS).to_dicts(),
                },
            }
            session.flush()
            session.refresh(row)
            return self._record(row)

    @staticmethod
    def _audit(
        session: Session,
        row: ScheduleRun,
        action: ReviewAction,
        actor: User,
        note: str | None,
    ) -> None:
        session.add(
            PlanReview(
                id=uuid.uuid4(),
                run_id=row.run_id,
                schedule_run_id=row.id,
                action=action,
                user_name=actor.name,
                role=actor.role.value,
                note=note,
                created_at=datetime.now(UTC),
            )
        )

    def review(
        self, plan_id: uuid.UUID, actor: User, decision: ReviewStatus, note: str | None
    ) -> PlanRecord:
        with self._factory() as session, session.begin():
            row = self._row(session, plan_id, lock=True)
            action = check_review(
                status=row.review_status,
                requested_by=row.requested_by,
                actor=actor,
                decision=decision,
            )
            row.review_status = decision
            self._audit(session, row, action, actor, note)
            session.flush()
            return self._record(row)

    def activate(self, plan_id: uuid.UUID, actor: User, note: str | None) -> PlanRecord:
        try:
            with self._factory() as session, session.begin():
                row = self._row(session, plan_id, lock=True)
                check_activate(status=row.review_status, is_current=row.is_current, actor=actor)
                previous = (
                    session.execute(
                        sa.select(ScheduleRun)
                        .where(ScheduleRun.run_id == row.run_id, ScheduleRun.is_current.is_(True))
                        .with_for_update()
                    )
                    .scalars()
                    .all()
                )
                for old in previous:
                    old.is_current = False
                    self._audit(
                        session,
                        old,
                        ReviewAction.DEACTIVATE,
                        actor,
                        f"reemplazado por el plan {plan_id}",
                    )
                session.flush()  # el vigente anterior debe liberarse antes del índice único
                row.is_current = True
                self._audit(session, row, ReviewAction.ACTIVATE, actor, note)
                session.flush()
                return self._record(row)
        except IntegrityError as exc:
            raise InvalidTransition(
                "otro plan quedó vigente al mismo tiempo en esta corrida; reintenta"
            ) from exc
