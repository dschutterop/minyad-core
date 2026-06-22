"""Add configurable GoodWe poll interval setting

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SETTING_KEY = "battery.inverter_poll_interval_s"
DEFAULT_VALUE = "120"


def upgrade() -> None:
    op.execute(
        sa.text(
            "insert into settings (key, value, encrypted) values (:key, :value, false) "
            "on conflict (key) do nothing"
        ).bindparams(key=SETTING_KEY, value=DEFAULT_VALUE)
    )


def downgrade() -> None:
    op.execute(sa.text("delete from settings where key = :key").bindparams(key=SETTING_KEY))
