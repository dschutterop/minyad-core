"""Rename misleading columns in setpoint_log

- home_load_at_time → apparent_load_at_time: solar was never included so the
  label overstated what was measured.
- charge_rate_w → setpoint_w: the column holds a signed bipolar value (negative
  = charging, positive = discharging); the old name implied charge-only.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("setpoint_log", "home_load_at_time", new_column_name="apparent_load_at_time")
    op.alter_column("setpoint_log", "charge_rate_w", new_column_name="setpoint_w")


def downgrade() -> None:
    op.alter_column("setpoint_log", "setpoint_w", new_column_name="charge_rate_w")
    op.alter_column("setpoint_log", "apparent_load_at_time", new_column_name="home_load_at_time")
