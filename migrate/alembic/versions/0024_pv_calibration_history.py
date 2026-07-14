"""dashboard forecast v1: per-hour PV calibration history

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pv_calibration_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("calibration_date", sa.Date(), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=False),
        sa.Column("factor", sa.REAL(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("calibration_date", "hour_of_day", name="uq_pv_calibration_history_date_hour"),
    )
    op.create_index("ix_pv_calibration_history_date", "pv_calibration_history", ["calibration_date"])


def downgrade() -> None:
    op.drop_table("pv_calibration_history")
