"""strategy v3 slot plans and shadow log

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slot_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_seconds", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("solver_status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_slot_plans_generated_at", "slot_plans", ["generated_at"])

    op.create_table(
        "strategy_shadow_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("v2_setpoint_w", sa.Integer(), nullable=True),
        sa.Column("v3_setpoint_w", sa.Integer(), nullable=False),
        sa.Column("soc", sa.REAL(), nullable=True),
        sa.Column("net_grid_w", sa.Integer(), nullable=True),
        sa.Column("v3_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_strategy_shadow_log_ts", "strategy_shadow_log", ["ts"])

    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted) values
              ('battery.capacity_wh', '10240', false),
              ('strategy3.plan_interval_min', '15', false),
              ('strategy3.horizon_slots', '96', false),
              ('strategy3.one_way_efficiency', '0.95', false),
              ('strategy3.cycle_cost_eur_kwh', '0.03', false),
              ('strategy3.fixed_price_import', '0.25', false),
              ('strategy3.fixed_price_export', '0.00', false),
              ('strategy3.export_cap_w', '0', false),
              ('strategy3.grid_charge_relax_w', '0', false),
              ('strategy3.terminal_soc_pct', '30', false),
              ('strategy3.traj_tau_hours', '2.0', false),
              ('strategy3.traj_bias_max_w', '400', false),
              ('strategy3.traj_deadband_pct', '3', false),
              ('strategy3.traj_band_pct', '8', false),
              ('strategy3.pv_calibration_factor', '7.0', false),
              ('strategy3.consumption_lookback_days', '14', false),
              ('strategy3.consumption_fallback_w', '300', false)
            on conflict (key) do nothing
            """
        )
    )


def downgrade() -> None:
    op.drop_table("strategy_shadow_log")
    op.drop_table("slot_plans")
