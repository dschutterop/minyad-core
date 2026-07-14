"""Ensure setpoint_log has strategy v2 fields

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='setpoint_log' AND column_name='setpoint_delta') THEN
                ALTER TABLE setpoint_log ADD COLUMN setpoint_delta integer;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='setpoint_log' AND column_name='trigger_reason') THEN
                ALTER TABLE setpoint_log ADD COLUMN trigger_reason text;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='setpoint_log' AND column_name='ack_received') THEN
                ALTER TABLE setpoint_log ADD COLUMN ack_received boolean NOT NULL DEFAULT false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='setpoint_log' AND column_name='ack_latency_ms') THEN
                ALTER TABLE setpoint_log ADD COLUMN ack_latency_ms integer;
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
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='setpoint_delta') THEN
                ALTER TABLE setpoint_log DROP COLUMN setpoint_delta;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='trigger_reason') THEN
                ALTER TABLE setpoint_log DROP COLUMN trigger_reason;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='ack_received') THEN
                ALTER TABLE setpoint_log DROP COLUMN ack_received;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='setpoint_log' AND column_name='ack_latency_ms') THEN
                ALTER TABLE setpoint_log DROP COLUMN ack_latency_ms;
            END IF;
        END $$;
    """))
