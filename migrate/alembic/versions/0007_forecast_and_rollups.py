"""open meteo forecast and scalable power rollups

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("power_curve_points", sa.Column("net_w", sa.Integer(), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("forecast_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("direct_w_m2", sa.Float(), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("diffuse_w_m2", sa.Float(), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("estimated_w", sa.Integer(), nullable=True))
    op.add_column("solar_forecast_points", sa.Column("source", sa.String(length=64), nullable=False, server_default="open-meteo"))
    op.execute("update power_curve_points set net_w = power_w where net_w is null")
    op.execute("update solar_forecast_points set forecast_time = timestamp, estimated_w = power_w, source = provider where forecast_time is null")
    op.create_unique_constraint("uq_solar_forecast_points_forecast_time", "solar_forecast_points", ["forecast_time"])

    op.create_table(
        "power_curve_rollups",
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity_seconds", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("power_w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_w", sa.Integer(), nullable=True),
        sa.Column("returned_w", sa.Integer(), nullable=True),
        sa.Column("net_w", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("bucket_start", "granularity_seconds", "source", name="pk_power_curve_rollups"),
        sa.CheckConstraint("source in ('solar','battery','grid')", name="ck_power_curve_rollups_source"),
    )
    op.create_index("ix_power_curve_rollups_source_bucket", "power_curve_rollups", ["source", "granularity_seconds", "bucket_start"])


def downgrade() -> None:
    op.drop_index("ix_power_curve_rollups_source_bucket", table_name="power_curve_rollups")
    op.drop_table("power_curve_rollups")
    op.drop_constraint("uq_solar_forecast_points_forecast_time", "solar_forecast_points", type_="unique")
    op.drop_column("solar_forecast_points", "source")
    op.drop_column("solar_forecast_points", "estimated_w")
    op.drop_column("solar_forecast_points", "diffuse_w_m2")
    op.drop_column("solar_forecast_points", "direct_w_m2")
    op.drop_column("solar_forecast_points", "forecast_time")
    op.drop_column("solar_forecast_points", "fetched_at")
    op.drop_column("power_curve_points", "net_w")
