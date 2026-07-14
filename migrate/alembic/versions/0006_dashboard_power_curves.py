"""dashboard power curve telemetry

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "power_curve_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("power_w", sa.Integer(), nullable=False),
        sa.Column("delivered_w", sa.Integer(), nullable=True),
        sa.Column("returned_w", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source in ('solar','battery','grid')", name="ck_power_curve_points_source"),
    )
    op.create_index("ix_power_curve_points_bucket_source", "power_curve_points", ["bucket_start", "source"])
    op.create_index("ix_power_curve_points_source_timestamp", "power_curve_points", ["source", "timestamp"])

    op.create_table(
        "solar_forecast_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("power_w", sa.Integer(), nullable=False),
        sa.Column("forecast_ghi", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="synthetic"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_solar_forecast_points_bucket", "solar_forecast_points", ["bucket_start"])


def downgrade() -> None:
    op.drop_index("ix_solar_forecast_points_bucket", table_name="solar_forecast_points")
    op.drop_table("solar_forecast_points")
    op.drop_index("ix_power_curve_points_source_timestamp", table_name="power_curve_points")
    op.drop_index("ix_power_curve_points_bucket_source", table_name="power_curve_points")
    op.drop_table("power_curve_points")
