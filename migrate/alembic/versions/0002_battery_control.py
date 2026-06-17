"""battery control settings and override state

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

battery_override_table = sa.Table(
    "battery_override",
    sa.MetaData(),
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("mode", sa.String(length=32), nullable=False, server_default="none"),
    sa.Column("watts", sa.Integer(), nullable=True),
    sa.Column("duration_seconds", sa.Integer(), nullable=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

DEFAULT_SETTINGS = {
    "battery.start_w": "500",
    "battery.stop_w": "150",
    "battery.start_duration": "180",
    "battery.stop_duration": "300",
    "battery.cooldown": "600",
    "battery.max_charge_w": "1440",
    "battery.max_discharge_w": "5000",
    "battery.max_charge_a": "30",
    "battery.nominal_v": "48",
    "battery.inverter_ip": "192.168.1.50",
    "battery.inverter_retries": "5",
    "battery.inverter_delay": "3",
}


def ensure_settings_columns(bind: sa.engine.Connection) -> None:
    """Bring older settings tables up to the baseline shape this migration expects."""
    columns = {column["name"] for column in sa.inspect(bind).get_columns("settings")}
    if "encrypted" not in columns:
        op.add_column("settings", sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "updated_at" not in columns:
        op.add_column("settings", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    if "is_secret" in columns:
        op.execute(sa.text("update settings set is_secret = false where is_secret is null"))
        op.alter_column("settings", "is_secret", server_default=sa.false(), existing_type=sa.Boolean())


def upgrade() -> None:
    bind = op.get_bind()
    ensure_settings_columns(bind)
    battery_override_table.create(bind, checkfirst=True)
    for key, value in DEFAULT_SETTINGS.items():
        op.execute(
            sa.text(
                "insert into settings (key, value, encrypted) values (:key, :value, false) "
                "on conflict (key) do nothing"
            ).bindparams(key=key, value=value)
        )
    op.execute(sa.text("insert into battery_override (id, mode) values (1, 'none') on conflict (id) do nothing"))


def downgrade() -> None:
    bind = op.get_bind()
    battery_override_table.drop(bind, checkfirst=True)
