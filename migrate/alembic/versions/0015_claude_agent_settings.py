"""Add Claude agent runtime settings

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

DEFAULTS = {
    "claude_agent.enabled": "false",
    "claude_agent.token_guard_enabled": "true",
    "claude_agent.min_tokens_remaining": "5000",
}


def upgrade() -> None:
    for key, value in DEFAULTS.items():
        op.execute(
            sa.text(
                "insert into settings (key, value, encrypted) values (:key, :value, false) "
                "on conflict (key) do nothing"
            ).bindparams(key=key, value=value)
        )


def downgrade() -> None:
    op.execute(sa.text("delete from settings where key like 'claude_agent.%'"))
