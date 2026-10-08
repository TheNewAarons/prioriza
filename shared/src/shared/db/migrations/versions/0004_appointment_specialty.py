"""Especialidad en la cita (el historial sintético la necesita para el modelo de inasistencias).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointment",
        sa.Column(
            "specialty_code",
            sa.String(length=80),
            nullable=True,
            comment=(
                "especialidad de la cita; en el historial sintético "
                "identifica la especialidad atendida"
            ),
        ),
    )
    op.create_index(
        "ix_appointment_specialty_code", "appointment", ["specialty_code"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_appointment_specialty_code_specialty"),
        "appointment",
        "specialty",
        ["specialty_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_appointment_specialty_code_specialty"), "appointment", type_="foreignkey"
    )
    op.drop_index("ix_appointment_specialty_code", table_name="appointment")
    op.drop_column("appointment", "specialty_code")
