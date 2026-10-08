"""Modelo de datos central: catálogos, corridas sintéticas, citas y resultados.

Revisada a mano. El downgrade elimina todo en orden inverso de dependencias.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commune",
        sa.Column("code", sa.String(length=5), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("region_code", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_commune")),
        comment="Catálogo de comunas.",
    )
    op.create_table(
        "health_service",
        sa.Column("code", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_health_service")),
        sa.UniqueConstraint("name", name=op.f("uq_health_service_name")),
        comment="Catálogo de servicios de salud.",
    )
    op.create_table(
        "specialty",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "care_type",
            sa.Enum(
                "consultation",
                "surgery",
                "unspecified",
                name="caretype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "care_subtype",
            sa.Enum(
                "medical",
                "dental",
                "major",
                "minor",
                name="caresubtype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_specialty")),
        sa.UniqueConstraint(
            "name",
            "care_type",
            "care_subtype",
            name="uq_specialty_name_care_type_care_subtype",
            postgresql_nulls_not_distinct=True,
        ),
        comment="Catálogo de especialidades; el código es un slug (p. ej. cne_medical:x).",
    )
    op.create_table(
        "synthetic_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column(
            "scenario",
            sa.Enum(
                "neutral",
                "baseline",
                "ses_gradient",
                name="noshowscenario",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("horizon_weeks", sa.Integer(), nullable=False),
        sa.Column("reference_source_id", sa.String(length=64), nullable=False),
        sa.Column("targets_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("params_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("dataset_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("generator_version", sa.String(length=32), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "loading",
                "ready",
                "failed",
                name="runstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthetic_run")),
        comment="Corrida de generación sintética; borrarla elimina sus datos.",
    )
    op.create_table(
        "establishment",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("health_service_code", sa.SmallInteger(), nullable=False),
        sa.Column("commune_code", sa.String(length=5), nullable=False),
        sa.Column("complexity", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["commune_code"], ["commune.code"], name=op.f("fk_establishment_commune_code_commune")
        ),
        sa.ForeignKeyConstraint(
            ["health_service_code"],
            ["health_service.code"],
            name=op.f("fk_establishment_health_service_code_health_service"),
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_establishment")),
        comment="Catálogo de establecimientos de salud.",
    )
    op.create_table(
        "ges_problem",
        sa.Column("code", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("deadline_days", sa.SmallInteger(), nullable=True),
        sa.Column("specialty_code", sa.String(length=80), nullable=True),
        sa.Column(
            "care_type",
            sa.Enum(
                "consultation",
                "surgery",
                "unspecified",
                name="caretype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["specialty_code"],
            ["specialty.code"],
            name=op.f("fk_ges_problem_specialty_code_specialty"),
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ges_problem")),
        comment="Catálogo de problemas GES mapeados a especialidad.",
    )
    op.create_table(
        "patient",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("health_service_code", sa.SmallInteger(), nullable=False),
        sa.Column("commune_code", sa.String(length=5), nullable=False),
        sa.Column(
            "age_group",
            sa.Enum(
                "0_14",
                "15_19",
                "20_44",
                "45_64",
                "65_plus",
                name="agegroup",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "insurance",
            sa.Enum(
                "fonasa_a",
                "fonasa_b",
                "fonasa_c",
                "fonasa_d",
                "other",
                name="insurance",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["commune_code"], ["commune.code"], name=op.f("fk_patient_commune_code_commune")
        ),
        sa.ForeignKeyConstraint(
            ["health_service_code"],
            ["health_service.code"],
            name=op.f("fk_patient_health_service_code_health_service"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_patient_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient")),
        comment="Paciente sintético; solo atributos agregados (grupo etario, previsión).",
    )
    op.create_index(
        "ix_patient_run_id_age_group_insurance",
        "patient",
        ["run_id", "age_group", "insurance"],
        unique=False,
    )
    op.create_index(
        "ix_patient_run_id_commune_code", "patient", ["run_id", "commune_code"], unique=False
    )
    op.create_index(
        "ix_patient_run_id_health_service_code",
        "patient",
        ["run_id", "health_service_code"],
        unique=False,
    )
    op.create_table(
        "schedule_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "policy",
            sa.Enum(
                "fifo",
                "priority",
                "optimized",
                name="policy",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("horizon_start", sa.Date(), nullable=False),
        sa.Column("horizon_end", sa.Date(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("solver_status", sa.String(length=32), nullable=True),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="reviewstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("code_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_schedule_run_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_run")),
        comment="Plan de programación; todo plan nace pendiente de revisión humana.",
    )
    op.create_table(
        "patient_latent",
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "noshow_frailty",
            sa.Float(),
            nullable=False,
            comment="verdad sintética, prohibido como feature",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.id"],
            name=op.f("fk_patient_latent_patient_id_patient"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_patient_latent_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("patient_id", name=op.f("pk_patient_latent")),
        comment="verdad sintética, prohibido como feature",
    )
    op.create_table(
        "policy_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "policy",
            sa.Enum(
                "fifo",
                "priority",
                "optimized",
                name="policy",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("group_dimension", sa.String(length=32), nullable=True),
        sa.Column("group_value", sa.String(length=64), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("ci_low", sa.Float(), nullable=True),
        sa.Column("ci_high", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_policy_result_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_run_id"],
            ["schedule_run.id"],
            name=op.f("fk_policy_result_schedule_run_id_schedule_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_result")),
        sa.UniqueConstraint(
            "experiment_id",
            "policy",
            "metric",
            "group_dimension",
            "group_value",
            name="uq_policy_result_key",
            postgresql_nulls_not_distinct=True,
        ),
        comment="Resultados de políticas por métrica y grupo (incluye los negativos).",
    )
    op.create_index(
        op.f("ix_policy_result_experiment_id"), "policy_result", ["experiment_id"], unique=False
    )
    op.create_table(
        "procedure",
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("specialty_code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "care_subtype",
            sa.Enum(
                "medical",
                "dental",
                "major",
                "minor",
                name="caresubtype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("duration_min", sa.SmallInteger(), nullable=False),
        sa.Column("ges_problem_code", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("duration_min > 0", name="ck_procedure_duration_positive"),
        sa.ForeignKeyConstraint(
            ["ges_problem_code"],
            ["ges_problem.code"],
            name=op.f("fk_procedure_ges_problem_code_ges_problem"),
        ),
        sa.ForeignKeyConstraint(
            ["specialty_code"],
            ["specialty.code"],
            name=op.f("fk_procedure_specialty_code_specialty"),
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_procedure")),
        comment="Catálogo de procedimientos con duración en minutos.",
    )
    op.create_table(
        "resource",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "operating_room",
                "specialist_agenda",
                name="resourcekind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("establishment_code", sa.String(length=16), nullable=False),
        sa.Column("health_service_code", sa.SmallInteger(), nullable=False),
        sa.Column("specialty_code", sa.String(length=80), nullable=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["establishment_code"],
            ["establishment.code"],
            name=op.f("fk_resource_establishment_code_establishment"),
        ),
        sa.ForeignKeyConstraint(
            ["health_service_code"],
            ["health_service.code"],
            name=op.f("fk_resource_health_service_code_health_service"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_resource_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialty_code"],
            ["specialty.code"],
            name=op.f("fk_resource_specialty_code_specialty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource")),
        comment="Recurso programable (pabellón o agenda de especialista).",
    )
    op.create_index(
        "ix_resource_run_id_health_service_code_kind",
        "resource",
        ["run_id", "health_service_code", "kind"],
        unique=False,
    )
    op.create_table(
        "slot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("specialty_code", sa.String(length=80), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column(
            "unit_min",
            sa.SmallInteger(),
            nullable=True,
            comment="Minutos por consulta en CNE; nulo en pabellón.",
        ),
        sa.CheckConstraint("duration_min > 0", name="ck_slot_duration_positive"),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource.id"],
            name=op.f("fk_slot_resource_id_resource"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_slot_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialty_code"], ["specialty.code"], name=op.f("fk_slot_specialty_code_specialty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_slot")),
        sa.UniqueConstraint("resource_id", "start_at", name="uq_slot_resource_id_start_at"),
        comment="Bloque de sesión de un recurso (consultas CNE o bloque de pabellón).",
    )
    op.create_index(
        "ix_slot_run_id_specialty_code_start_at",
        "slot",
        ["run_id", "specialty_code", "start_at"],
        unique=False,
    )
    op.create_table(
        "waitlist_entry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("health_service_code", sa.SmallInteger(), nullable=False),
        sa.Column("establishment_code", sa.String(length=16), nullable=False),
        sa.Column("specialty_code", sa.String(length=80), nullable=False),
        sa.Column("procedure_code", sa.String(length=80), nullable=False),
        sa.Column(
            "care_type",
            sa.Enum(
                "consultation",
                "surgery",
                "unspecified",
                name="caretype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "care_subtype",
            sa.Enum(
                "medical",
                "dental",
                "major",
                "minor",
                name="caresubtype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "clinical_priority",
            sa.Enum(
                "p1",
                "p2",
                "p3",
                "p4",
                name="clinicalpriority",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_ges", sa.Boolean(), nullable=False),
        sa.Column("ges_problem_code", sa.SmallInteger(), nullable=True),
        sa.Column("ges_deadline", sa.Date(), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "waiting",
                "scheduled",
                "resolved",
                "removed",
                name="entrystatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="waiting",
            nullable=False,
        ),
        sa.Column("resolved_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "(ges_problem_code IS NULL) = (ges_deadline IS NULL)",
            name="ck_waitlist_entry_ges_fields_together",
        ),
        sa.CheckConstraint(
            "is_ges = (ges_problem_code IS NOT NULL AND ges_deadline IS NOT NULL)",
            name="ck_waitlist_entry_ges_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["establishment_code"],
            ["establishment.code"],
            name=op.f("fk_waitlist_entry_establishment_code_establishment"),
        ),
        sa.ForeignKeyConstraint(
            ["ges_problem_code"],
            ["ges_problem.code"],
            name=op.f("fk_waitlist_entry_ges_problem_code_ges_problem"),
        ),
        sa.ForeignKeyConstraint(
            ["health_service_code"],
            ["health_service.code"],
            name=op.f("fk_waitlist_entry_health_service_code_health_service"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.id"],
            name=op.f("fk_waitlist_entry_patient_id_patient"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["procedure_code"],
            ["procedure.code"],
            name=op.f("fk_waitlist_entry_procedure_code_procedure"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_waitlist_entry_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specialty_code"],
            ["specialty.code"],
            name=op.f("fk_waitlist_entry_specialty_code_specialty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_entry")),
        comment="Entrada en lista de espera (sintética).",
    )
    op.create_index("ix_waitlist_entry_patient_id", "waitlist_entry", ["patient_id"], unique=False)
    op.create_index(
        "ix_waitlist_entry_run_id_ges_deadline",
        "waitlist_entry",
        ["run_id", "ges_deadline"],
        unique=False,
        postgresql_where=sa.text("is_ges"),
    )
    op.create_index(
        "ix_waitlist_entry_run_id_health_service_code_specialty_code",
        "waitlist_entry",
        ["run_id", "health_service_code", "specialty_code"],
        unique=False,
    )
    op.create_index(
        "ix_waitlist_entry_run_id_status", "waitlist_entry", ["run_id", "status"], unique=False
    )
    op.create_table(
        "appointment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=True),
        sa.Column("slot_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "origin",
            sa.Enum(
                "history",
                "scheduler",
                "simulation",
                name="appointmentorigin",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "attended",
                "no_show",
                "cancelled",
                name="appointmentstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=True),
        sa.Column("is_overbooked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("predicted_noshow_prob", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "origin = 'history' OR slot_id IS NOT NULL", name="ck_appointment_slot_unless_history"
        ),
        sa.CheckConstraint(
            "predicted_noshow_prob IS NULL OR (predicted_noshow_prob BETWEEN 0 AND 1)",
            name="ck_appointment_predicted_prob_range",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["waitlist_entry.id"],
            name=op.f("fk_appointment_entry_id_waitlist_entry"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patient.id"],
            name=op.f("fk_appointment_patient_id_patient"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_appointment_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_run_id"],
            ["schedule_run.id"],
            name=op.f("fk_appointment_schedule_run_id_schedule_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"], ["slot.id"], name=op.f("fk_appointment_slot_id_slot"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment")),
        comment="Cita de un paciente sintético.",
    )
    op.create_index("ix_appointment_entry_id", "appointment", ["entry_id"], unique=False)
    op.create_index(
        "ix_appointment_run_id_patient_id_scheduled_start",
        "appointment",
        ["run_id", "patient_id", "scheduled_start"],
        unique=False,
    )
    op.create_index(
        "ix_appointment_schedule_run_id", "appointment", ["schedule_run_id"], unique=False
    )
    op.create_index("ix_appointment_slot_id", "appointment", ["slot_id"], unique=False)
    op.create_table(
        "appointment_truth",
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "true_noshow_prob",
            sa.Float(),
            nullable=False,
            comment="verdad sintética, prohibido como feature",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointment.id"],
            name=op.f("fk_appointment_truth_appointment_id_appointment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_appointment_truth_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("appointment_id", name=op.f("pk_appointment_truth")),
        comment="verdad sintética, prohibido como feature",
    )


def downgrade() -> None:
    op.drop_table("appointment_truth")
    op.drop_index("ix_appointment_slot_id", table_name="appointment")
    op.drop_index("ix_appointment_schedule_run_id", table_name="appointment")
    op.drop_index("ix_appointment_run_id_patient_id_scheduled_start", table_name="appointment")
    op.drop_index("ix_appointment_entry_id", table_name="appointment")
    op.drop_table("appointment")
    op.drop_index("ix_waitlist_entry_run_id_status", table_name="waitlist_entry")
    op.drop_index(
        "ix_waitlist_entry_run_id_health_service_code_specialty_code", table_name="waitlist_entry"
    )
    op.drop_index(
        "ix_waitlist_entry_run_id_ges_deadline",
        table_name="waitlist_entry",
        postgresql_where=sa.text("is_ges"),
    )
    op.drop_index("ix_waitlist_entry_patient_id", table_name="waitlist_entry")
    op.drop_table("waitlist_entry")
    op.drop_index("ix_slot_run_id_specialty_code_start_at", table_name="slot")
    op.drop_table("slot")
    op.drop_index("ix_resource_run_id_health_service_code_kind", table_name="resource")
    op.drop_table("resource")
    op.drop_table("procedure")
    op.drop_index(op.f("ix_policy_result_experiment_id"), table_name="policy_result")
    op.drop_table("policy_result")
    op.drop_table("patient_latent")
    op.drop_table("schedule_run")
    op.drop_index("ix_patient_run_id_health_service_code", table_name="patient")
    op.drop_index("ix_patient_run_id_commune_code", table_name="patient")
    op.drop_index("ix_patient_run_id_age_group_insurance", table_name="patient")
    op.drop_table("patient")
    op.drop_table("ges_problem")
    op.drop_table("establishment")
    op.drop_table("synthetic_run")
    op.drop_table("specialty")
    op.drop_table("health_service")
    op.drop_table("commune")
