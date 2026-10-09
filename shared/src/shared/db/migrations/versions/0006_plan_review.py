"""Revisión humana de planes: vigencia, solicitante y auditoría.

Revisada a mano (autogenerate no detecta los CHECK). Agrega a `schedule_run` las columnas
`is_current` y `requested_by`, el CHECK que solo deja ser vigente a un plan aprobado y el
índice único parcial de un vigente por corrida sintética; crea `plan_review` (auditoría) con
FK compuesta como en 0005.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedule_run",
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="plan vigente de la corrida; solo un plan aprobado puede serlo",
        ),
    )
    op.add_column(
        "schedule_run",
        sa.Column(
            "requested_by",
            sa.String(length=64),
            nullable=True,
            comment="usuario que pidió el plan (para la regla de cuatro ojos)",
        ),
    )
    op.create_check_constraint(
        "ck_schedule_run_current_requires_approved",
        "schedule_run",
        "NOT is_current OR review_status = 'approved'",
    )
    op.create_index(
        "uq_schedule_run_current_per_run",
        "schedule_run",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "plan_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "approve",
                "reject",
                "activate",
                "deactivate",
                name="reviewaction",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("user_name", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(action IN ('approve', 'reject') AND role = 'revisor') "
            "OR (action IN ('activate', 'deactivate') AND role = 'gestor')",
            name=op.f("ck_plan_review_role_matches_action"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "schedule_run_id"],
            ["schedule_run.run_id", "schedule_run.id"],
            name="fk_plan_review_schedule_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["synthetic_run.id"],
            name=op.f("fk_plan_review_run_id_synthetic_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_review")),
        comment="Auditoría de revisión y vigencia de planes: usuario, rol, hora y nota.",
    )
    op.create_index(
        "ix_plan_review_run_id_schedule_run_id",
        "plan_review",
        ["run_id", "schedule_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_plan_review_run_id_schedule_run_id", table_name="plan_review")
    op.drop_table("plan_review")
    op.drop_index("uq_schedule_run_current_per_run", table_name="schedule_run")
    op.drop_constraint("ck_schedule_run_current_requires_approved", "schedule_run", type_="check")
    op.drop_column("schedule_run", "requested_by")
    op.drop_column("schedule_run", "is_current")
