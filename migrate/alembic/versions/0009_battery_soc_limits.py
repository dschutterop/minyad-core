"""battery SoC floor and ceiling control limits

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

DEFAULT_SETTINGS = {
    "battery.soc_floor": "20",
    "battery.soc_ceiling": "90",
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
