"""dashboard forecast v1: PV forecast P10-P90 uncertainty bands

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pv_uncertainty_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("calibration_date", sa.Date(), nullable=False),
        sa.Column("cloud_class", sa.Text(), nullable=False),
        sa.Column("p10_multiplier", sa.REAL(), nullable=False),
        sa.Column("p90_multiplier", sa.REAL(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("calibration_date", "cloud_class", name="uq_pv_uncertainty_bands_date_class"),
    )
    op.create_index("ix_pv_uncertainty_bands_date", "pv_uncertainty_bands", ["calibration_date"])


def downgrade() -> None:
    op.drop_table("pv_uncertainty_bands")
