"""battery discharge hysteresis settings

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

DEFAULT_SETTINGS = {
    "battery.discharge_start_w": "-300",
    "battery.discharge_stop_w": "-100",
}


def upgrade() -> None:
    for key, value in DEFAULT_SETTINGS.items():
        op.execute(
            sa.text(
                "insert into settings (key, value, encrypted) values (:key, :value, false) "
                "on conflict (key) do nothing"
            ).bindparams(key=key, value=value)
        )


def downgrade() -> None:
    for key in DEFAULT_SETTINGS:
        op.execute(sa.text("delete from settings where key = :key").bindparams(key=key))
