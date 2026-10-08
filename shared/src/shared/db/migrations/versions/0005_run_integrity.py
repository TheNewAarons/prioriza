"""Integridad entre corridas: FK compuestas con run_id, CHECKs de dominio y comentario de carga.

Revisada a mano (autogenerate no detecta los CHECK). Las FK hijas pasan a ser compuestas
(run_id, x_id) -> (run_id, id) para impedir mezclar filas de corridas distintas; con columnas
nulas la FK (MATCH SIMPLE) no se evalúa, lo cual es lo deseado. Se conserva ON DELETE CASCADE.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYNTHETIC_RUN_OLD_COMMENT = "Corrida de generación sintética; borrarla elimina sus datos."
SYNTHETIC_RUN_COMMENT = (
    "Corrida de generación sintética; borrarla elimina sus datos. La carga es una "
    "sola transacción: una corrida en estado loading no es visible para otras "
    "conexiones y failed queda reservado para futuras cargas no transaccionales."
)


def upgrade() -> None:
    op.create_unique_constraint("uq_patient_run_id_id", "patient", ["run_id", "id"])
    op.create_unique_constraint("uq_waitlist_entry_run_id_id", "waitlist_entry", ["run_id", "id"])
    op.create_unique_constraint("uq_resource_run_id_id", "resource", ["run_id", "id"])
    op.create_unique_constraint("uq_slot_run_id_id", "slot", ["run_id", "id"])
    op.create_unique_constraint("uq_appointment_run_id_id", "appointment", ["run_id", "id"])
    op.create_unique_constraint("uq_schedule_run_run_id_id", "schedule_run", ["run_id", "id"])
    op.drop_constraint("fk_waitlist_entry_patient_id_patient", "waitlist_entry", type_="foreignkey")
    op.create_foreign_key(
        "fk_waitlist_entry_patient",
        "waitlist_entry",
        "patient",
        ["run_id", "patient_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_patient_latent_patient_id_patient", "patient_latent", type_="foreignkey")
    op.create_foreign_key(
        "fk_patient_latent_patient",
        "patient_latent",
        "patient",
        ["run_id", "patient_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_slot_resource_id_resource", "slot", type_="foreignkey")
    op.create_foreign_key(
        "fk_slot_resource",
        "slot",
        "resource",
        ["run_id", "resource_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_patient_id_patient", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_patient",
        "appointment",
        "patient",
        ["run_id", "patient_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_entry_id_waitlist_entry", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_entry",
        "appointment",
        "waitlist_entry",
        ["run_id", "entry_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_slot_id_slot", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_slot",
        "appointment",
        "slot",
        ["run_id", "slot_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_appointment_schedule_run_id_schedule_run", "appointment", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_appointment_schedule_run",
        "appointment",
        "schedule_run",
        ["run_id", "schedule_run_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_appointment_truth_appointment_id_appointment", "appointment_truth", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_appointment_truth_appointment",
        "appointment_truth",
        "appointment",
        ["run_id", "appointment_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_policy_result_schedule_run_id_schedule_run", "policy_result", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_policy_result_schedule_run",
        "policy_result",
        "schedule_run",
        ["run_id", "schedule_run_id"],
        ["run_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("ck_synthetic_run_size_positive", "synthetic_run", "size > 0")
    op.create_check_constraint(
        "ck_waitlist_entry_deadline_after_entry",
        "waitlist_entry",
        "ges_deadline IS NULL OR ges_deadline >= entry_date",
    )
    op.create_check_constraint(
        "ck_waitlist_entry_resolved_on_status",
        "waitlist_entry",
        "resolved_on IS NULL OR status IN ('resolved', 'removed')",
    )
    op.create_check_constraint(
        "ck_schedule_run_horizon_order", "schedule_run", "horizon_end >= horizon_start"
    )
    op.create_check_constraint(
        "ck_appointment_duration_positive", "appointment", "duration_min > 0"
    )
    op.create_check_constraint(
        "ck_appointment_lead_days_nonneg", "appointment", "lead_days IS NULL OR lead_days >= 0"
    )
    op.create_check_constraint(
        "ck_appointment_truth_prob_range", "appointment_truth", "true_noshow_prob BETWEEN 0 AND 1"
    )
    op.create_check_constraint(
        "ck_policy_result_ci_order",
        "policy_result",
        "ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high",
    )
    op.create_table_comment(
        "synthetic_run",
        SYNTHETIC_RUN_COMMENT,
        existing_comment=SYNTHETIC_RUN_OLD_COMMENT,
    )


def downgrade() -> None:
    op.create_table_comment(
        "synthetic_run",
        SYNTHETIC_RUN_OLD_COMMENT,
        existing_comment=SYNTHETIC_RUN_COMMENT,
    )
    op.drop_constraint("ck_policy_result_ci_order", "policy_result", type_="check")
    op.drop_constraint("ck_appointment_truth_prob_range", "appointment_truth", type_="check")
    op.drop_constraint("ck_appointment_lead_days_nonneg", "appointment", type_="check")
    op.drop_constraint("ck_appointment_duration_positive", "appointment", type_="check")
    op.drop_constraint("ck_schedule_run_horizon_order", "schedule_run", type_="check")
    op.drop_constraint("ck_waitlist_entry_resolved_on_status", "waitlist_entry", type_="check")
    op.drop_constraint("ck_waitlist_entry_deadline_after_entry", "waitlist_entry", type_="check")
    op.drop_constraint("ck_synthetic_run_size_positive", "synthetic_run", type_="check")
    op.drop_constraint("fk_policy_result_schedule_run", "policy_result", type_="foreignkey")
    op.create_foreign_key(
        "fk_policy_result_schedule_run_id_schedule_run",
        "policy_result",
        "schedule_run",
        ["schedule_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_truth_appointment", "appointment_truth", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_truth_appointment_id_appointment",
        "appointment_truth",
        "appointment",
        ["appointment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_schedule_run", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_schedule_run_id_schedule_run",
        "appointment",
        "schedule_run",
        ["schedule_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_slot", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_slot_id_slot",
        "appointment",
        "slot",
        ["slot_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_entry", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_entry_id_waitlist_entry",
        "appointment",
        "waitlist_entry",
        ["entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_appointment_patient", "appointment", type_="foreignkey")
    op.create_foreign_key(
        "fk_appointment_patient_id_patient",
        "appointment",
        "patient",
        ["patient_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_slot_resource", "slot", type_="foreignkey")
    op.create_foreign_key(
        "fk_slot_resource_id_resource",
        "slot",
        "resource",
        ["resource_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_patient_latent_patient", "patient_latent", type_="foreignkey")
    op.create_foreign_key(
        "fk_patient_latent_patient_id_patient",
        "patient_latent",
        "patient",
        ["patient_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("fk_waitlist_entry_patient", "waitlist_entry", type_="foreignkey")
    op.create_foreign_key(
        "fk_waitlist_entry_patient_id_patient",
        "waitlist_entry",
        "patient",
        ["patient_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_schedule_run_run_id_id", "schedule_run", type_="unique")
    op.drop_constraint("uq_appointment_run_id_id", "appointment", type_="unique")
    op.drop_constraint("uq_slot_run_id_id", "slot", type_="unique")
    op.drop_constraint("uq_resource_run_id_id", "resource", type_="unique")
    op.drop_constraint("uq_waitlist_entry_run_id_id", "waitlist_entry", type_="unique")
    op.drop_constraint("uq_patient_run_id_id", "patient", type_="unique")
