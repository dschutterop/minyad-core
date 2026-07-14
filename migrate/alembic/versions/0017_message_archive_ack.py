"""message archive and acknowledgements

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_messages", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_messages", sa.Column("operator_ack_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_messages", sa.Column("agent_ack_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_agent_messages_archived_at", "agent_messages", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_archived_at", table_name="agent_messages")
    op.drop_column("agent_messages", "agent_ack_at")
    op.drop_column("agent_messages", "operator_ack_at")
    op.drop_column("agent_messages", "archived_at")
