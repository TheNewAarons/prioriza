"""Modelos ORM del modelo de datos central (catálogos, corridas sintéticas y programación).

Aviso: herramienta de investigación con datos sintéticos. No hay nombres, RUT, fecha de
nacimiento ni sexo en ninguna tabla. Las tablas `patient_latent` y `appointment_truth`
contienen la verdad sintética del generador y no pueden usarse como features.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base
from shared.db.enums import (
    AgeGroup,
    AppointmentOrigin,
    AppointmentStatus,
    ClinicalPriority,
    EntryStatus,
    Insurance,
    NoShowScenario,
    Policy,
    ResourceKind,
    ReviewStatus,
    RunStatus,
)
from shared.schemas import CareSubtype, CareType

_TRUTH_COMMENT = "verdad sintética, prohibido como feature"


def _enum(cls: type[enum.StrEnum]) -> sa.Enum:
    """Enum almacenado como texto con CHECK, usando los valores (minúscula) del StrEnum."""
    return sa.Enum(
        cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        name=cls.__name__.lower(),
    )


def _tstz() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        sa.Uuid, sa.ForeignKey("synthetic_run.id", ondelete="CASCADE"), nullable=False
    )


# ---------------------------------------------------------------- Catálogos globales


class HealthService(Base):
    """Servicio de salud del SNSS."""

    __tablename__ = "health_service"
    __table_args__ = ({"comment": "Catálogo de servicios de salud."},)

    code: Mapped[int] = mapped_column(sa.SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(sa.String(80), unique=True)


class Commune(Base):
    """Comuna."""

    __tablename__ = "commune"
    __table_args__ = ({"comment": "Catálogo de comunas."},)

    code: Mapped[str] = mapped_column(sa.String(5), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    region_code: Mapped[int] = mapped_column(sa.SmallInteger)


class Establishment(Base):
    """Establecimiento de salud."""

    __tablename__ = "establishment"
    __table_args__ = ({"comment": "Catálogo de establecimientos de salud."},)

    code: Mapped[str] = mapped_column(sa.String(16), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(160))
    health_service_code: Mapped[int] = mapped_column(sa.ForeignKey("health_service.code"))
    commune_code: Mapped[str] = mapped_column(sa.ForeignKey("commune.code"))
    complexity: Mapped[str | None] = mapped_column(sa.String(32))


class Specialty(Base):
    """Especialidad (taxonomías CNE e IQ separadas)."""

    __tablename__ = "specialty"
    __table_args__ = (
        sa.UniqueConstraint(
            "name",
            "care_type",
            "care_subtype",
            name="uq_specialty_name_care_type_care_subtype",
            postgresql_nulls_not_distinct=True,
        ),
        {"comment": "Catálogo de especialidades; el código es un slug (p. ej. cne_medical:x)."},
    )

    code: Mapped[str] = mapped_column(sa.String(80), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(160))
    care_type: Mapped[CareType] = mapped_column(_enum(CareType))
    care_subtype: Mapped[CareSubtype | None] = mapped_column(_enum(CareSubtype))


class GesProblem(Base):
    """Problema de salud GES."""

    __tablename__ = "ges_problem"
    __table_args__ = ({"comment": "Catálogo de problemas GES mapeados a especialidad."},)

    code: Mapped[int] = mapped_column(sa.SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(sa.String(200))
    deadline_days: Mapped[int | None] = mapped_column(sa.SmallInteger)
    specialty_code: Mapped[str | None] = mapped_column(sa.ForeignKey("specialty.code"))
    care_type: Mapped[CareType | None] = mapped_column(_enum(CareType))


class Procedure(Base):
    """Procedimiento (consulta nueva o intervención genérica)."""

    __tablename__ = "procedure"
    __table_args__ = (
        sa.CheckConstraint("duration_min > 0", name="ck_procedure_duration_positive"),
        {"comment": "Catálogo de procedimientos con duración en minutos."},
    )

    code: Mapped[str] = mapped_column(sa.String(80), primary_key=True)
    specialty_code: Mapped[str] = mapped_column(sa.ForeignKey("specialty.code"))
    name: Mapped[str] = mapped_column(sa.String(160))
    care_subtype: Mapped[CareSubtype | None] = mapped_column(_enum(CareSubtype))
    duration_min: Mapped[int] = mapped_column(sa.SmallInteger)
    ges_problem_code: Mapped[int | None] = mapped_column(sa.ForeignKey("ges_problem.code"))


# ---------------------------------------------------------------- Versionado


class SyntheticRun(Base):
    """Corrida de generación de población sintética (id determinista)."""

    __tablename__ = "synthetic_run"
    __table_args__ = (
        sa.CheckConstraint("size > 0", name="ck_synthetic_run_size_positive"),
        {
            "comment": (
                "Corrida de generación sintética; borrarla elimina sus datos. La carga es una "
                "sola transacción: una corrida en estado loading no es visible para otras "
                "conexiones y failed queda reservado para futuras cargas no transaccionales."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    seed: Mapped[int] = mapped_column(sa.BigInteger)
    size: Mapped[int] = mapped_column(sa.Integer)
    scenario: Mapped[NoShowScenario] = mapped_column(_enum(NoShowScenario))
    as_of: Mapped[date] = mapped_column(sa.Date)
    horizon_weeks: Mapped[int] = mapped_column(sa.Integer)
    reference_source_id: Mapped[str] = mapped_column(sa.String(64))
    targets_sha256: Mapped[str] = mapped_column(sa.CHAR(64))
    params_sha256: Mapped[str] = mapped_column(sa.CHAR(64))
    dataset_sha256: Mapped[str] = mapped_column(sa.CHAR(64))
    generator_version: Mapped[str] = mapped_column(sa.String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus))
    created_at: Mapped[datetime] = mapped_column(_tstz(), server_default=sa.func.now())


# ---------------------------------------------------------------- Tablas por corrida


class Patient(Base):
    """Paciente sintético (sin nombre, RUT, fecha de nacimiento ni sexo)."""

    __tablename__ = "patient"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_patient_run_id_id"),
        sa.Index("ix_patient_run_id_health_service_code", "run_id", "health_service_code"),
        sa.Index("ix_patient_run_id_commune_code", "run_id", "commune_code"),
        sa.Index("ix_patient_run_id_age_group_insurance", "run_id", "age_group", "insurance"),
        {"comment": "Paciente sintético; solo atributos agregados (grupo etario, previsión)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    health_service_code: Mapped[int] = mapped_column(sa.ForeignKey("health_service.code"))
    commune_code: Mapped[str] = mapped_column(sa.ForeignKey("commune.code"))
    age_group: Mapped[AgeGroup] = mapped_column(_enum(AgeGroup))
    insurance: Mapped[Insurance] = mapped_column(_enum(Insurance))


class PatientLatent(Base):
    """Variable latente de inasistencia: verdad del generador."""

    __tablename__ = "patient_latent"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.id"],
            ondelete="CASCADE",
            name="fk_patient_latent_patient",
        ),
        {"comment": _TRUTH_COMMENT},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    noshow_frailty: Mapped[float] = mapped_column(sa.Float, comment=_TRUTH_COMMENT)


class WaitlistEntry(Base):
    """Entrada en lista de espera; la prioridad clínica es un dato de entrada."""

    __tablename__ = "waitlist_entry"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_waitlist_entry_run_id_id"),
        sa.ForeignKeyConstraint(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.id"],
            ondelete="CASCADE",
            name="fk_waitlist_entry_patient",
        ),
        sa.CheckConstraint(
            "ges_deadline IS NULL OR ges_deadline >= entry_date",
            name="ck_waitlist_entry_deadline_after_entry",
        ),
        sa.CheckConstraint(
            "resolved_on IS NULL OR status IN ('resolved', 'removed')",
            name="ck_waitlist_entry_resolved_on_status",
        ),
        sa.CheckConstraint(
            "is_ges = (ges_problem_code IS NOT NULL AND ges_deadline IS NOT NULL)",
            name="ck_waitlist_entry_ges_consistency",
        ),
        sa.CheckConstraint(
            "(ges_problem_code IS NULL) = (ges_deadline IS NULL)",
            name="ck_waitlist_entry_ges_fields_together",
        ),
        sa.Index("ix_waitlist_entry_run_id_status", "run_id", "status"),
        sa.Index(
            "ix_waitlist_entry_run_id_health_service_code_specialty_code",
            "run_id",
            "health_service_code",
            "specialty_code",
        ),
        sa.Index("ix_waitlist_entry_patient_id", "patient_id"),
        sa.Index(
            "ix_waitlist_entry_run_id_ges_deadline",
            "run_id",
            "ges_deadline",
            postgresql_where=sa.text("is_ges"),
        ),
        {"comment": "Entrada en lista de espera (sintética)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    patient_id: Mapped[uuid.UUID] = mapped_column()
    health_service_code: Mapped[int] = mapped_column(sa.ForeignKey("health_service.code"))
    establishment_code: Mapped[str] = mapped_column(sa.ForeignKey("establishment.code"))
    specialty_code: Mapped[str] = mapped_column(sa.ForeignKey("specialty.code"))
    procedure_code: Mapped[str] = mapped_column(sa.ForeignKey("procedure.code"))
    care_type: Mapped[CareType] = mapped_column(_enum(CareType))
    care_subtype: Mapped[CareSubtype | None] = mapped_column(_enum(CareSubtype))
    clinical_priority: Mapped[ClinicalPriority] = mapped_column(_enum(ClinicalPriority))
    is_ges: Mapped[bool] = mapped_column(sa.Boolean)
    ges_problem_code: Mapped[int | None] = mapped_column(sa.ForeignKey("ges_problem.code"))
    ges_deadline: Mapped[date | None] = mapped_column(sa.Date)
    entry_date: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[EntryStatus] = mapped_column(
        _enum(EntryStatus), default=EntryStatus.WAITING, server_default=EntryStatus.WAITING.value
    )
    resolved_on: Mapped[date | None] = mapped_column(sa.Date)


class Resource(Base):
    """Recurso programable: pabellón o agenda de especialista."""

    __tablename__ = "resource"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_resource_run_id_id"),
        sa.Index(
            "ix_resource_run_id_health_service_code_kind", "run_id", "health_service_code", "kind"
        ),
        {"comment": "Recurso programable (pabellón o agenda de especialista)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    kind: Mapped[ResourceKind] = mapped_column(_enum(ResourceKind))
    establishment_code: Mapped[str] = mapped_column(sa.ForeignKey("establishment.code"))
    health_service_code: Mapped[int] = mapped_column(sa.ForeignKey("health_service.code"))
    specialty_code: Mapped[str | None] = mapped_column(sa.ForeignKey("specialty.code"))
    label: Mapped[str] = mapped_column(sa.String(64))


class Slot(Base):
    """Bloque de sesión de un recurso."""

    __tablename__ = "slot"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_slot_run_id_id"),
        sa.ForeignKeyConstraint(
            ["run_id", "resource_id"],
            ["resource.run_id", "resource.id"],
            ondelete="CASCADE",
            name="fk_slot_resource",
        ),
        sa.CheckConstraint("duration_min > 0", name="ck_slot_duration_positive"),
        sa.UniqueConstraint("resource_id", "start_at", name="uq_slot_resource_id_start_at"),
        sa.Index("ix_slot_run_id_specialty_code_start_at", "run_id", "specialty_code", "start_at"),
        {"comment": "Bloque de sesión de un recurso (consultas CNE o bloque de pabellón)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    resource_id: Mapped[uuid.UUID] = mapped_column()
    specialty_code: Mapped[str] = mapped_column(sa.ForeignKey("specialty.code"))
    start_at: Mapped[datetime] = mapped_column(_tstz())
    duration_min: Mapped[int] = mapped_column(sa.Integer)
    unit_min: Mapped[int | None] = mapped_column(
        sa.SmallInteger, comment="Minutos por consulta en CNE; nulo en pabellón."
    )


class ScheduleRun(Base):
    """Plan de programación generado por una política; requiere revisión humana."""

    __tablename__ = "schedule_run"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_schedule_run_run_id_id"),
        sa.CheckConstraint("horizon_end >= horizon_start", name="ck_schedule_run_horizon_order"),
        {"comment": "Plan de programación; todo plan nace pendiente de revisión humana."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    policy: Mapped[Policy] = mapped_column(_enum(Policy))
    horizon_start: Mapped[date] = mapped_column(sa.Date)
    horizon_end: Mapped[date] = mapped_column(sa.Date)
    seed: Mapped[int] = mapped_column(sa.BigInteger)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    solver_status: Mapped[str | None] = mapped_column(sa.String(32))
    objective_value: Mapped[float | None] = mapped_column(sa.Float)
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus),
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    code_version: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(_tstz(), server_default=sa.func.now())
    finished_at: Mapped[datetime | None] = mapped_column(_tstz())


class Appointment(Base):
    """Cita (historial sintético, programada o simulada)."""

    __tablename__ = "appointment"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "id", name="uq_appointment_run_id_id"),
        sa.ForeignKeyConstraint(
            ["run_id", "patient_id"],
            ["patient.run_id", "patient.id"],
            ondelete="CASCADE",
            name="fk_appointment_patient",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "entry_id"],
            ["waitlist_entry.run_id", "waitlist_entry.id"],
            ondelete="CASCADE",
            name="fk_appointment_entry",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "slot_id"],
            ["slot.run_id", "slot.id"],
            ondelete="CASCADE",
            name="fk_appointment_slot",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "schedule_run_id"],
            ["schedule_run.run_id", "schedule_run.id"],
            ondelete="CASCADE",
            name="fk_appointment_schedule_run",
        ),
        sa.CheckConstraint("duration_min > 0", name="ck_appointment_duration_positive"),
        sa.CheckConstraint(
            "lead_days IS NULL OR lead_days >= 0", name="ck_appointment_lead_days_nonneg"
        ),
        sa.CheckConstraint(
            "origin = 'history' OR slot_id IS NOT NULL", name="ck_appointment_slot_unless_history"
        ),
        sa.CheckConstraint(
            "predicted_noshow_prob IS NULL OR (predicted_noshow_prob BETWEEN 0 AND 1)",
            name="ck_appointment_predicted_prob_range",
        ),
        sa.Index(
            "ix_appointment_run_id_patient_id_scheduled_start",
            "run_id",
            "patient_id",
            "scheduled_start",
        ),
        sa.Index("ix_appointment_slot_id", "slot_id"),
        sa.Index("ix_appointment_schedule_run_id", "schedule_run_id"),
        sa.Index("ix_appointment_entry_id", "entry_id"),
        {"comment": "Cita de un paciente sintético."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    patient_id: Mapped[uuid.UUID] = mapped_column()
    entry_id: Mapped[uuid.UUID | None] = mapped_column()
    slot_id: Mapped[uuid.UUID | None] = mapped_column()
    schedule_run_id: Mapped[uuid.UUID | None] = mapped_column()
    origin: Mapped[AppointmentOrigin] = mapped_column(_enum(AppointmentOrigin))
    status: Mapped[AppointmentStatus] = mapped_column(_enum(AppointmentStatus))
    scheduled_start: Mapped[datetime] = mapped_column(_tstz())
    duration_min: Mapped[int] = mapped_column(sa.Integer)
    lead_days: Mapped[int | None] = mapped_column(sa.Integer)
    is_overbooked: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    predicted_noshow_prob: Mapped[float | None] = mapped_column(sa.Float)
    specialty_code: Mapped[str | None] = mapped_column(
        sa.ForeignKey("specialty.code"),
        comment=(
            "especialidad de la cita; en el historial sintético identifica la especialidad atendida"
        ),
    )


class AppointmentTruth(Base):
    """Probabilidad verdadera de inasistencia: verdad del generador."""

    __tablename__ = "appointment_truth"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["run_id", "appointment_id"],
            ["appointment.run_id", "appointment.id"],
            ondelete="CASCADE",
            name="fk_appointment_truth_appointment",
        ),
        sa.CheckConstraint(
            "true_noshow_prob BETWEEN 0 AND 1", name="ck_appointment_truth_prob_range"
        ),
        {"comment": _TRUTH_COMMENT},
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    true_noshow_prob: Mapped[float] = mapped_column(sa.Float, comment=_TRUTH_COMMENT)


class PolicyResult(Base):
    """Métrica de una política en un experimento, global o por grupo."""

    __tablename__ = "policy_result"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["run_id", "schedule_run_id"],
            ["schedule_run.run_id", "schedule_run.id"],
            ondelete="CASCADE",
            name="fk_policy_result_schedule_run",
        ),
        sa.CheckConstraint(
            "ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high",
            name="ck_policy_result_ci_order",
        ),
        sa.UniqueConstraint(
            "experiment_id",
            "policy",
            "metric",
            "group_dimension",
            "group_value",
            name="uq_policy_result_key",
            postgresql_nulls_not_distinct=True,
        ),
        {"comment": "Resultados de políticas por métrica y grupo (incluye los negativos)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    experiment_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, index=True)
    schedule_run_id: Mapped[uuid.UUID | None] = mapped_column()
    policy: Mapped[Policy] = mapped_column(_enum(Policy))
    metric: Mapped[str] = mapped_column(sa.String(64))
    group_dimension: Mapped[str | None] = mapped_column(sa.String(32))
    group_value: Mapped[str | None] = mapped_column(sa.String(64))
    value: Mapped[float] = mapped_column(sa.Float)
    n: Mapped[int] = mapped_column(sa.Integer)
    ci_low: Mapped[float | None] = mapped_column(sa.Float)
    ci_high: Mapped[float | None] = mapped_column(sa.Float)
    created_at: Mapped[datetime] = mapped_column(_tstz(), server_default=sa.func.now())


# Índices sobre columnas FK que no encabezan ningún índice, PK o único existente. Son
# necesarios para que el DELETE en cascada de una corrida no recorra la tabla hija por fila.
_FK_INDEXES: tuple[tuple[type[Base], str], ...] = (
    (Establishment, "health_service_code"),
    (Establishment, "commune_code"),
    (GesProblem, "specialty_code"),
    (Procedure, "specialty_code"),
    (Procedure, "ges_problem_code"),
    (Patient, "health_service_code"),
    (Patient, "commune_code"),
    (PatientLatent, "run_id"),
    (WaitlistEntry, "specialty_code"),
    (WaitlistEntry, "health_service_code"),
    (WaitlistEntry, "procedure_code"),
    (WaitlistEntry, "establishment_code"),
    (WaitlistEntry, "ges_problem_code"),
    (Resource, "establishment_code"),
    (Resource, "health_service_code"),
    (Resource, "specialty_code"),
    (Slot, "specialty_code"),
    (ScheduleRun, "run_id"),
    (Appointment, "patient_id"),
    (Appointment, "specialty_code"),
    (AppointmentTruth, "run_id"),
    (PolicyResult, "run_id"),
    (PolicyResult, "schedule_run_id"),
)

for _model, _column in _FK_INDEXES:
    _table = cast(sa.Table, _model.__table__)
    sa.Index(f"ix_{_table.name}_{_column}", _table.c[_column])
