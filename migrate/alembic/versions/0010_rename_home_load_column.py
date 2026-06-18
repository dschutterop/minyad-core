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
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='home_load_at_time') THEN
                ALTER TABLE setpoint_log RENAME COLUMN home_load_at_time TO apparent_load_at_time;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='charge_rate_w') THEN
                ALTER TABLE setpoint_log RENAME COLUMN charge_rate_w TO setpoint_w;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    op.alter_column("setpoint_log", "setpoint_w", new_column_name="charge_rate_w")
    op.alter_column("setpoint_log", "apparent_load_at_time", new_column_name="home_load_at_time")
