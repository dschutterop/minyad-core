"""agent operator mailbox

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("related_decision_id", sa.BigInteger(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False, server_default="normal"),
        sa.CheckConstraint("sender in ('agent','operator')", name="ck_agent_messages_sender"),
        sa.CheckConstraint("category in ('anomaly','suggestion','info','reply')", name="ck_agent_messages_category"),
        sa.CheckConstraint("severity in ('low','normal','high')", name="ck_agent_messages_severity"),
        sa.ForeignKeyConstraint(["related_decision_id"], ["agent_decisions.id"], name="fk_agent_messages_related_decision_id"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_messages.id"], name="fk_agent_messages_thread_id"),
    )
    op.create_index("ix_agent_messages_created_at", "agent_messages", ["created_at"])
    op.create_index("ix_agent_messages_unread_sender", "agent_messages", ["sender", "read_at"])
    op.create_index("ix_agent_messages_thread_id", "agent_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_thread_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_unread_sender", table_name="agent_messages")
    op.drop_index("ix_agent_messages_created_at", table_name="agent_messages")
    op.drop_table("agent_messages")
