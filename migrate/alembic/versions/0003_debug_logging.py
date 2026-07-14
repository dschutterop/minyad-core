"""system debug logging setting

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "insert into settings (key, value, encrypted) values ('system.debug_logging', 'false', false) "
            "on conflict (key) do nothing"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("delete from settings where key = 'system.debug_logging'"))
