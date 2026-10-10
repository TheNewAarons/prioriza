"""Dominio de los planes: reglas de revisión y vigencia, y almacén en memoria.

Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de
gestión real sin validación institucional.

Las reglas viven aquí y no en las rutas; `PlanStore.review` y `PlanStore.activate` las aplican
tanto en memoria como en SQL (`sql_store.py`, donde la base las refuerza con un CHECK y un
índice único). El sistema apoya, no decide: todo plan nace `pending` y solo una persona con
rol `revisor` lo aprueba o rechaza.

1. Solo `revisor` aprueba o rechaza.
2. El revisor no puede revisar un plan que pidió él mismo (cuatro ojos, por nombre de usuario
   normalizado con `same_person`). Un plan sin solicitante registrado (por ejemplo, escrito por
   la CLI con `--persist`) no se puede revisar por la API: la regla falla cerrada.
3. La decisión es final: solo se pasa de `pending` a `approved` o `rejected`.
4. Solo `gestor` activa, y solo un plan `approved`; activar uno desactiva el vigente anterior de
   la misma corrida sintética (un vigente por corrida).
5. Cada acción deja un `ReviewRecord` (usuario, rol, hora y nota).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import polars as pl
from scheduler.instance import SchedulingInstance
from scheduler.plan import SchedulePlan
from shared.db.enums import ReviewAction, ReviewStatus

from api.auth import Role, User

ASSIGNMENT_COLUMNS = (
    "entry_id",
    "patient_id",
    "slot_id",
    "specialty_code",
    "scheduled_start",
    "duration_min",
    "lead_days",
    "is_overbooked",
    "predicted_noshow_prob",
)
EXPLANATION_COLUMNS = ("entry_id", "status", "detail", "text")


class PlanError(Exception):
    """Error de dominio de los planes."""


class NotFound(PlanError):
    """El plan no existe."""


class PermissionDenied(PlanError):
    """El usuario no puede hacer la acción (rol insuficiente o cuatro ojos)."""


class InvalidTransition(PlanError):
    """La acción no corresponde al estado actual del plan."""


@dataclass(frozen=True)
class NewPlan:
    """Plan recién calculado, listo para guardarse como pendiente."""

    run_id: str
    plan: SchedulePlan
    instance: SchedulingInstance
    horizon_end_exclusive: date
    requested_by: str
    config: dict[str, Any]


@dataclass(frozen=True)
class PlanRecord:
    """Estado de un plan guardado (sin las filas de asignaciones ni explicaciones)."""

    id: uuid.UUID
    run_id: str
    policy: str
    requested_by: str | None
    created_at: datetime
    review_status: ReviewStatus
    is_current: bool
    solver_status: str | None
    objective_value: float | None
    horizon_start: date
    horizon_end: date  # inclusive
    report: dict[str, Any]
    config: dict[str, Any]


@dataclass(frozen=True)
class ReviewRecord:
    """Registro de auditoría de una acción sobre un plan."""

    id: uuid.UUID
    plan_id: uuid.UUID
    action: ReviewAction
    user_name: str
    role: str
    note: str | None
    created_at: datetime


@dataclass(frozen=True)
class Page[T]:
    """Página de resultados con el total sin paginar."""

    items: list[T]
    total: int


@dataclass(frozen=True)
class EntryRows:
    """Lo que el plan guardó de una entrada: explicación, cita propuesta y garantía GES."""

    explanation: dict[str, Any] | None
    assignment: dict[str, Any] | None
    ges: dict[str, Any] | None


def same_person(a: str, b: str) -> bool:
    """Compara nombres de usuario sin distinguir mayúsculas ni espacios en los extremos."""
    return a.strip().casefold() == b.strip().casefold()


def check_review(
    *, status: ReviewStatus, requested_by: str | None, actor: User, decision: ReviewStatus
) -> ReviewAction:
    """Valida una decisión de revisión y devuelve la acción a auditar."""
    if decision not in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
        raise ValueError("la decisión debe ser 'approved' o 'rejected'")
    if actor.role is not Role.REVISOR:
        raise PermissionDenied("solo un usuario con rol 'revisor' puede aprobar o rechazar planes")
    if requested_by is None:
        raise PermissionDenied(
            "el plan no tiene solicitante registrado; no se puede revisar por la API "
            "(regla de cuatro ojos)"
        )
    if same_person(requested_by, actor.name):
        raise PermissionDenied(
            "el revisor no puede revisar un plan que pidió él mismo (regla de cuatro ojos)"
        )
    if status is not ReviewStatus.PENDING:
        raise InvalidTransition(
            f"el plan ya está '{status.value}'; la decisión de revisión es final"
        )
    return ReviewAction.APPROVE if decision is ReviewStatus.APPROVED else ReviewAction.REJECT


def check_activate(*, status: ReviewStatus, is_current: bool, actor: User) -> None:
    """Valida que `actor` pueda marcar el plan como vigente."""
    if actor.role is not Role.GESTOR:
        raise PermissionDenied("solo un usuario con rol 'gestor' puede marcar un plan como vigente")
    if status is not ReviewStatus.APPROVED:
        raise InvalidTransition(
            f"solo un plan 'approved' puede ser vigente; este está '{status.value}'"
        )
    if is_current:
        raise InvalidTransition("el plan ya es el vigente de su corrida")


GES_COLUMNS = (
    "entry_id",
    "obligation",
    "ges_deadline",
    "met",
    "on_time",
    "scheduled_date",
    "days_late",
    "first_possible_date",
    "cause",
    "text",
)


class PlanStore(Protocol):
    """Almacén de planes; aplica las reglas de revisión y vigencia."""

    def add(self, new: NewPlan) -> PlanRecord:
        """Guarda un plan como `pending` y no vigente."""
        ...

    def get(self, plan_id: uuid.UUID) -> PlanRecord:
        """Plan por id; `NotFound` si no existe."""
        ...

    def list_plans(
        self,
        *,
        review_status: ReviewStatus | None = None,
        current: bool | None = None,
        run_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[PlanRecord]:
        """Planes del más reciente al más antiguo."""
        ...

    def current(self, run_id: str | None = None) -> PlanRecord | None:
        """Plan vigente de la corrida (o el más reciente entre las corridas si `run_id` es None)."""
        ...

    def assignments(self, plan_id: uuid.UUID, *, limit: int, offset: int) -> Page[dict[str, Any]]:
        """Asignaciones (columnas de `ASSIGNMENT_COLUMNS`) por fecha de inicio y entrada."""
        ...

    def explanations(
        self, plan_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> Page[dict[str, Any]]:
        """Explicaciones por entrada (columnas de `EXPLANATION_COLUMNS`), filtrables por estado."""
        ...

    def ges(
        self, plan_id: uuid.UUID, *, met: bool | None, cause: str | None, limit: int, offset: int
    ) -> Page[dict[str, Any]]:
        """Garantías GES del plan, filtrables por cumplimiento y causa."""
        ...

    def ges_causes(self, plan_id: uuid.UUID) -> dict[str, int]:
        """Garantías GES no cumplidas del plan, contadas por causa."""
        ...

    def slot_counts(self, plan_id: uuid.UUID) -> pl.DataFrame:
        """Citas por cupo: columnas `slot_id`, `scheduled` (sin sobrecupo) y `overbooked`."""
        ...

    def entry_reason(self, plan_id: uuid.UUID, entry_id: str) -> EntryRows:
        """Fila de explicación, asignación y GES de una entrada (`None` donde no existe)."""
        ...

    def reviews(self, plan_id: uuid.UUID) -> list[ReviewRecord]:
        """Auditoría del plan en orden cronológico."""
        ...

    def review(
        self, plan_id: uuid.UUID, actor: User, decision: ReviewStatus, note: str | None
    ) -> PlanRecord:
        """Aprueba o rechaza un plan pendiente (solo `revisor`, nunca el solicitante)."""
        ...

    def activate(self, plan_id: uuid.UUID, actor: User, note: str | None) -> PlanRecord:
        """Marca vigente un plan aprobado (solo `gestor`); desactiva el vigente anterior."""
        ...


def project_assignments(df: pl.DataFrame) -> pl.DataFrame:
    """Deja las columnas públicas de las asignaciones, en orden estable."""
    return df.select(ASSIGNMENT_COLUMNS).sort("scheduled_start", "entry_id")


def project_explanations(df: pl.DataFrame) -> pl.DataFrame:
    """Deja las columnas públicas de las explicaciones, en orden estable."""
    return df.select(EXPLANATION_COLUMNS).sort("entry_id")


def project_ges(df: pl.DataFrame) -> pl.DataFrame:
    """Deja las columnas públicas de las garantías GES, en orden estable.

    El DataFrame interno puede tener columnas extra (p. ej. `occupants`); se descartan.
    """
    if "entry_id" not in df.columns:
        return pl.DataFrame(schema={"entry_id": pl.String})
    cols = [c for c in GES_COLUMNS if c in df.columns]
    return df.select(cols).sort("entry_id")


def filter_ges(
    rows: list[dict[str, Any]], *, met: bool | None, cause: str | None
) -> list[dict[str, Any]]:
    """Filtra filas de garantías GES por cumplimiento y causa."""
    return [
        r
        for r in rows
        if (met is None or r["met"] is met) and (cause is None or r["cause"] == cause)
    ]


def count_causes(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta por causa las garantías no cumplidas (ordenado de mayor a menor)."""
    counts: dict[str, int] = {}
    for r in rows:
        if not r["met"]:
            key = r["cause"] or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


@dataclass
class _Stored:
    record: PlanRecord
    assignments: pl.DataFrame
    explanations: pl.DataFrame
    ges: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    reviews: list[ReviewRecord] = field(default_factory=list)


class MemoryPlanStore:
    """Almacén en memoria (se pierde al reiniciar); seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._plans: dict[uuid.UUID, _Stored] = {}
        self._tick = 0

    def _now(self) -> datetime:
        # Reloj monótono: dos acciones seguidas nunca comparten hora (orden estable).
        with self._lock:
            self._tick += 1
            return datetime.now(UTC) + timedelta(microseconds=self._tick)

    def _stored(self, plan_id: uuid.UUID) -> _Stored:
        stored = self._plans.get(plan_id)
        if stored is None:
            raise NotFound(f"no existe el plan {plan_id}")
        return stored

    def add(self, new: NewPlan) -> PlanRecord:
        plan = new.plan
        horizon_start = new.instance.horizon_start
        with self._lock:
            record = PlanRecord(
                id=uuid.uuid4(),
                run_id=new.run_id,
                policy=plan.policy,
                requested_by=new.requested_by,
                created_at=self._now(),
                review_status=ReviewStatus.PENDING,
                is_current=False,
                solver_status=plan.solver_status,
                objective_value=plan.objective_value,
                horizon_start=horizon_start,
                horizon_end=new.horizon_end_exclusive - timedelta(days=1),
                report=plan.report,
                config=new.config,
            )
            self._plans[record.id] = _Stored(
                record,
                project_assignments(plan.assignments),
                project_explanations(plan.explanations),
                project_ges(plan.ges),
            )
            return record

    def get(self, plan_id: uuid.UUID) -> PlanRecord:
        with self._lock:
            return self._stored(plan_id).record

    def list_plans(
        self,
        *,
        review_status: ReviewStatus | None = None,
        current: bool | None = None,
        run_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[PlanRecord]:
        with self._lock:
            rows = [
                s.record
                for s in self._plans.values()
                if (review_status is None or s.record.review_status is review_status)
                and (current is None or s.record.is_current is current)
                and (run_id is None or s.record.run_id == run_id)
            ]
        rows.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        return Page(rows[offset : offset + limit], len(rows))

    def current(self, run_id: str | None = None) -> PlanRecord | None:
        page = self.list_plans(current=True, run_id=run_id, limit=1)
        return page.items[0] if page.items else None

    def assignments(self, plan_id: uuid.UUID, *, limit: int, offset: int) -> Page[dict[str, Any]]:
        with self._lock:
            df = self._stored(plan_id).assignments
        return Page(df.slice(offset, limit).to_dicts(), df.height)

    def explanations(
        self, plan_id: uuid.UUID, *, status: str | None, limit: int, offset: int
    ) -> Page[dict[str, Any]]:
        with self._lock:
            df = self._stored(plan_id).explanations
        if status is not None:
            df = df.filter(pl.col("status") == status)
        return Page(df.slice(offset, limit).to_dicts(), df.height)

    def ges(
        self, plan_id: uuid.UUID, *, met: bool | None, cause: str | None, limit: int, offset: int
    ) -> Page[dict[str, Any]]:
        with self._lock:
            rows = self._stored(plan_id).ges.to_dicts()
        rows = filter_ges(rows, met=met, cause=cause)
        return Page(rows[offset : offset + limit], len(rows))

    def ges_causes(self, plan_id: uuid.UUID) -> dict[str, int]:
        with self._lock:
            rows = self._stored(plan_id).ges.to_dicts()
        return count_causes(rows)

    def slot_counts(self, plan_id: uuid.UUID) -> pl.DataFrame:
        with self._lock:
            df = self._stored(plan_id).assignments
        return df.group_by("slot_id").agg(
            (~pl.col("is_overbooked")).sum().cast(pl.Int64).alias("scheduled"),
            pl.col("is_overbooked").sum().cast(pl.Int64).alias("overbooked"),
        )

    def entry_reason(self, plan_id: uuid.UUID, entry_id: str) -> EntryRows:
        with self._lock:
            stored = self._stored(plan_id)
            frames = (stored.explanations, stored.assignments, stored.ges)

        def one(df: pl.DataFrame) -> dict[str, Any] | None:
            if "entry_id" not in df.columns:
                return None
            found = df.filter(pl.col("entry_id") == entry_id)
            return found.row(0, named=True) if found.height else None

        return EntryRows(*(one(df) for df in frames))

    def reviews(self, plan_id: uuid.UUID) -> list[ReviewRecord]:
        with self._lock:
            return list(self._stored(plan_id).reviews)

    def review(
        self, plan_id: uuid.UUID, actor: User, decision: ReviewStatus, note: str | None
    ) -> PlanRecord:
        with self._lock:
            stored = self._stored(plan_id)
            rec = stored.record
            action = check_review(
                status=rec.review_status,
                requested_by=rec.requested_by,
                actor=actor,
                decision=decision,
            )
            stored.record = replace(rec, review_status=decision)
            stored.reviews.append(self._audit(plan_id, action, actor, note))
            return stored.record

    def activate(self, plan_id: uuid.UUID, actor: User, note: str | None) -> PlanRecord:
        with self._lock:
            stored = self._stored(plan_id)
            rec = stored.record
            check_activate(status=rec.review_status, is_current=rec.is_current, actor=actor)
            for other in self._plans.values():
                if other.record.run_id == rec.run_id and other.record.is_current:
                    other.record = replace(other.record, is_current=False)
                    other.reviews.append(
                        self._audit(
                            other.record.id,
                            ReviewAction.DEACTIVATE,
                            actor,
                            f"reemplazado por el plan {plan_id}",
                        )
                    )
            stored.record = replace(rec, is_current=True)
            stored.reviews.append(self._audit(plan_id, ReviewAction.ACTIVATE, actor, note))
            return stored.record

    def _audit(
        self, plan_id: uuid.UUID, action: ReviewAction, actor: User, note: str | None
    ) -> ReviewRecord:
        return ReviewRecord(
            id=uuid.uuid4(),
            plan_id=plan_id,
            action=action,
            user_name=actor.name,
            role=actor.role.value,
            note=note,
            created_at=self._now(),
        )
