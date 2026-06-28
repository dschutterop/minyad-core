"""strategy v2 day plans

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_date", sa.Date(), nullable=False, unique=True),
        sa.Column("solar_mode", sa.Text(), nullable=False),
        sa.Column("forecast_ghi_kwh_m2", sa.REAL(), nullable=True),
        sa.Column("effective_soc_floor", sa.Integer(), nullable=False),
        sa.Column("effective_soc_ceiling", sa.Integer(), nullable=False),
        sa.Column("grid_charge_windows", postgresql.JSONB(), nullable=True),
        sa.Column("price_discharge_windows", postgresql.JSONB(), nullable=True),
        sa.Column("planned_soc_at_sunset", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted) values
              ('strategy.price_cheap_threshold_eur_kwh', '0.08', false),
              ('strategy.price_expensive_threshold_eur_kwh', '0.25', false),
              ('strategy.grid_charge_enabled', 'false', false),
              ('strategy.ramp_floor_w', '200', false),
              ('strategy.ramp_hold_seconds', '90', false),
              ('strategy.ramp_ceiling_w', '800', false),
              ('strategy.balance_gain', '0.6', false),
              ('strategy.jitter_w', '50', false),
              ('strategy.export_block_threshold_w', '100', false),
              ('strategy.price_discharge_bias_w', '200', false),
              ('strategy.control_refresh_interval_sec', '300', false),
              ('strategy.active_command_retry_interval_sec', '60', false),
              ('strategy.bridge_stale_seconds', '180', false),
              ('strategy.voltage_floor_v', '46.0', false)
            on conflict (key) do nothing
            """
        )
    )


def downgrade() -> None:
    op.drop_table("day_plans")
