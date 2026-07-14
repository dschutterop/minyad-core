"""Allow manual override to bypass battery SoC limits

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "battery_override",
        sa.Column("override_soc_limits", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("battery_override", "override_soc_limits")
