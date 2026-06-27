"""Ensure setpoint_log tracks battery power

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='setpoint_log' AND column_name='battery_power_at_time') THEN
                ALTER TABLE setpoint_log ADD COLUMN battery_power_at_time integer;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='battery_power_at_time') THEN
                ALTER TABLE setpoint_log DROP COLUMN battery_power_at_time;
            END IF;
        END $$;
    """))
