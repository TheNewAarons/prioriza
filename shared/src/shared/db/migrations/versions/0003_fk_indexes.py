"""Índices sobre FK sin índice líder (acelera el DELETE en cascada de una corrida).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_appointment_patient_id", "appointment", ["patient_id"], unique=False)
    op.create_index("ix_appointment_truth_run_id", "appointment_truth", ["run_id"], unique=False)
    op.create_index(
        "ix_establishment_commune_code", "establishment", ["commune_code"], unique=False
    )
    op.create_index(
        "ix_establishment_health_service_code",
        "establishment",
        ["health_service_code"],
        unique=False,
    )
    op.create_index(
        "ix_ges_problem_specialty_code", "ges_problem", ["specialty_code"], unique=False
    )
    op.create_index("ix_patient_commune_code", "patient", ["commune_code"], unique=False)
    op.create_index(
        "ix_patient_health_service_code", "patient", ["health_service_code"], unique=False
    )
    op.create_index("ix_patient_latent_run_id", "patient_latent", ["run_id"], unique=False)
    op.create_index("ix_policy_result_run_id", "policy_result", ["run_id"], unique=False)
    op.create_index(
        "ix_policy_result_schedule_run_id", "policy_result", ["schedule_run_id"], unique=False
    )
    op.create_index(
        "ix_procedure_ges_problem_code", "procedure", ["ges_problem_code"], unique=False
    )
    op.create_index("ix_procedure_specialty_code", "procedure", ["specialty_code"], unique=False)
    op.create_index(
        "ix_resource_establishment_code", "resource", ["establishment_code"], unique=False
    )
    op.create_index(
        "ix_resource_health_service_code", "resource", ["health_service_code"], unique=False
    )
    op.create_index("ix_resource_specialty_code", "resource", ["specialty_code"], unique=False)
    op.create_index("ix_schedule_run_run_id", "schedule_run", ["run_id"], unique=False)
    op.create_index("ix_slot_specialty_code", "slot", ["specialty_code"], unique=False)
    op.create_index(
        "ix_waitlist_entry_establishment_code",
        "waitlist_entry",
        ["establishment_code"],
        unique=False,
    )
    op.create_index(
        "ix_waitlist_entry_ges_problem_code", "waitlist_entry", ["ges_problem_code"], unique=False
    )
    op.create_index(
        "ix_waitlist_entry_health_service_code",
        "waitlist_entry",
        ["health_service_code"],
        unique=False,
    )
    op.create_index(
        "ix_waitlist_entry_procedure_code", "waitlist_entry", ["procedure_code"], unique=False
    )
    op.create_index(
        "ix_waitlist_entry_specialty_code", "waitlist_entry", ["specialty_code"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_waitlist_entry_specialty_code", table_name="waitlist_entry")
    op.drop_index("ix_waitlist_entry_procedure_code", table_name="waitlist_entry")
    op.drop_index("ix_waitlist_entry_health_service_code", table_name="waitlist_entry")
    op.drop_index("ix_waitlist_entry_ges_problem_code", table_name="waitlist_entry")
    op.drop_index("ix_waitlist_entry_establishment_code", table_name="waitlist_entry")
    op.drop_index("ix_slot_specialty_code", table_name="slot")
    op.drop_index("ix_schedule_run_run_id", table_name="schedule_run")
    op.drop_index("ix_resource_specialty_code", table_name="resource")
    op.drop_index("ix_resource_health_service_code", table_name="resource")
    op.drop_index("ix_resource_establishment_code", table_name="resource")
    op.drop_index("ix_procedure_specialty_code", table_name="procedure")
    op.drop_index("ix_procedure_ges_problem_code", table_name="procedure")
    op.drop_index("ix_policy_result_schedule_run_id", table_name="policy_result")
    op.drop_index("ix_policy_result_run_id", table_name="policy_result")
    op.drop_index("ix_patient_latent_run_id", table_name="patient_latent")
    op.drop_index("ix_patient_health_service_code", table_name="patient")
    op.drop_index("ix_patient_commune_code", table_name="patient")
    op.drop_index("ix_ges_problem_specialty_code", table_name="ges_problem")
    op.drop_index("ix_establishment_health_service_code", table_name="establishment")
    op.drop_index("ix_establishment_commune_code", table_name="establishment")
    op.drop_index("ix_appointment_truth_run_id", table_name="appointment_truth")
    op.drop_index("ix_appointment_patient_id", table_name="appointment")
