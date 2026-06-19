"""agent decisions audit log

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("action_taken", sa.Text(), nullable=False),
        sa.Column("setpoint_w", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("model", sa.Text(), nullable=False, server_default="claude-sonnet-4-6"),
        sa.CheckConstraint("action_taken in ('charge','discharge','hold')", name="ck_agent_decisions_action_taken"),
        sa.CheckConstraint("confidence in ('low','medium','high')", name="ck_agent_decisions_confidence"),
    )
    op.create_index("ix_agent_decisions_created_at", "agent_decisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_decisions_created_at", table_name="agent_decisions")
    op.drop_table("agent_decisions")
