"""Initial Minyad schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "grid_readings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("import_w", sa.Integer(), nullable=False),
        sa.Column("export_w", sa.Integer(), nullable=False),
        sa.Column("import_kwh_t1", sa.Numeric(12, 3)),
        sa.Column("import_kwh_t2", sa.Numeric(12, 3)),
        sa.Column("export_kwh_t1", sa.Numeric(12, 3)),
        sa.Column("export_kwh_t2", sa.Numeric(12, 3)),
        sa.Column("raw", postgresql.JSONB()),
    )
    op.create_table(
        "solar_readings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("production_w", sa.Integer(), nullable=False),
        sa.Column("lifetime_wh", sa.BigInteger()),
        sa.Column("raw", postgresql.JSONB()),
    )
    op.create_table(
        "battery_readings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("soc_pct", sa.Numeric(5, 2)),
        sa.Column("charge_w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discharge_w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mode", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("grid_feed_w", sa.Integer()),
        sa.Column("raw", postgresql.JSONB()),
    )
    op.create_table(
        "control_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_w", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_w", sa.Integer()),
        sa.Column("details", postgresql.JSONB()),
    )
    op.create_table(
        "solar_forecast",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp_forecast", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timestamp_target", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("ghi_wm2", sa.Numeric(8, 2)),
        sa.Column("dni_wm2", sa.Numeric(8, 2)),
        sa.Column("cloud_cover_pct", sa.Numeric(5, 2)),
        sa.Column("predicted_w", sa.Integer(), nullable=False),
        sa.UniqueConstraint("timestamp_forecast", "timestamp_target", name="uq_solar_forecast_run_target"),
    )
    op.create_table(
        "service_status",
        sa.Column("service", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("details", postgresql.JSONB()),
    )

    settings = sa.table(
        "settings",
        sa.column("key", sa.Text),
        sa.column("value", sa.Text),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        settings,
        [
            {"key": "export_tolerance_w", "value": "50", "description": "Max toegestane export in Watt"},
            {"key": "min_soc_pct", "value": "15", "description": "Minimale SOC voor ontladen"},
            {"key": "max_soc_pct", "value": "95", "description": "Maximale SOC voor laden"},
            {"key": "charge_threshold_w", "value": "200", "description": "Min solar-overschot om te starten met laden"},
            {"key": "control_loop_interval_s", "value": "10", "description": "Control loop interval in seconden"},
            {"key": "forecast_lookahead_h", "value": "36", "description": "Uren vooruit voor forecast"},
            {"key": "enphase_poll_interval_s", "value": "10", "description": "Poll interval Enphase Envoy"},
            {"key": "goodwe_poll_interval_s", "value": "5", "description": "Poll interval GoodWe"},
            {"key": "forecast_refresh_interval_s", "value": "21600", "description": "Forecast refresh interval in seconden"},
            {"key": "strategy", "value": "zero_export_self_consumption", "description": "Actieve strategie"},
            {"key": "battery_max_charge_w", "value": "4600", "description": "Max laadvermogen batterij"},
            {"key": "battery_max_discharge_w", "value": "4600", "description": "Max ontlaadvermogen batterij"},
            {"key": "min_forecast_soc_pct", "value": "35", "description": "Min SOC bij lage zonverwachting"},
            {"key": "low_solar_forecast_kwh", "value": "8", "description": "Drempel voor lage verwachte productie morgen"},
        ],
    )


def downgrade() -> None:
    op.drop_table("service_status")
    op.drop_table("solar_forecast")
    op.drop_table("control_log")
    op.drop_table("battery_readings")
    op.drop_table("solar_readings")
    op.drop_table("grid_readings")
    op.drop_table("settings")
