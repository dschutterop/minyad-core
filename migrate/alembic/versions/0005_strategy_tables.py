"""strategy decision and replay logging tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("soc_floor", sa.Integer(), nullable=False),
        sa.Column("soc_ceiling", sa.Integer(), nullable=False),
        sa.Column("forecast_ghi", sa.Float(), nullable=True),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "setpoint_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("soc_floor", sa.Integer(), nullable=False),
        sa.Column("soc_ceiling", sa.Integer(), nullable=False),
        sa.Column("charge_rate_w", sa.Integer(), nullable=True),
        sa.Column("discharge_allowed", sa.Boolean(), nullable=False),
        sa.Column("battery_soc_at_time", sa.Float(), nullable=True),
        sa.Column("grid_power_at_time", sa.Integer(), nullable=True),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("ack_received", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ack_latency_ms", sa.Integer(), nullable=True),
    )
    op.create_table(
        "telemetry_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_strategy_decisions_timestamp", "strategy_decisions", ["timestamp"])
    op.create_index("ix_setpoint_log_timestamp", "setpoint_log", ["timestamp"])
    op.create_index("ix_telemetry_log_timestamp", "telemetry_log", ["timestamp"])
    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted) values
              ('strategy.ghi_solar_rich_threshold', '4.5', false),
              ('strategy.ghi_solar_poor_threshold', '1.5', false),
              ('strategy.dynamic_tariff_ceiling_eur_kwh', '0.10', false),
              ('strategy.daily_recalculate_local_time', '22:00', false)
            on conflict (key) do nothing
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("delete from settings where key like 'strategy.%'"))
    op.drop_index("ix_telemetry_log_timestamp", table_name="telemetry_log")
    op.drop_index("ix_setpoint_log_timestamp", table_name="setpoint_log")
    op.drop_index("ix_strategy_decisions_timestamp", table_name="strategy_decisions")
    op.drop_table("telemetry_log")
    op.drop_table("setpoint_log")
    op.drop_table("strategy_decisions")
