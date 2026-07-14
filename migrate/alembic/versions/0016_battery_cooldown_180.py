"""set battery cooldown default to 180 seconds

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted) values ('battery.cooldown', '180', false)
            on conflict (key) do update set value='180', updated_at=now()
            where settings.value in ('120', '600')
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("update settings set value='120', updated_at=now() where key='battery.cooldown' and value='180'"))
