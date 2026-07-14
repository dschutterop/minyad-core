"""dashboard forecast v1: daily forecast accuracy tracking

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_accuracy_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("for_date", sa.Date(), nullable=False),
        sa.Column("curve", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("mae", sa.REAL(), nullable=False),
        sa.Column("bias", sa.REAL(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("for_date", "curve", "horizon", name="uq_forecast_accuracy_daily_date_curve_horizon"),
    )
    op.create_index("ix_forecast_accuracy_daily_date", "forecast_accuracy_daily", ["for_date"])


def downgrade() -> None:
    op.drop_table("forecast_accuracy_daily")
