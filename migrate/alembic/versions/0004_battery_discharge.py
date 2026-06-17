"""battery discharge setting

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "insert into settings (key, value, encrypted) values ('battery.max_discharge_w', '5000', false) "
            "on conflict (key) do nothing"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("delete from settings where key = 'battery.max_discharge_w'"))
