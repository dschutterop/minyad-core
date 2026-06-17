"""baseline settings and api key schema

Revision ID: 0001
Revises:
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

settings_table = sa.Table(
    "settings",
    sa.MetaData(),
    sa.Column("key", sa.String(length=255), primary_key=True),
    sa.Column("value", sa.Text(), nullable=True),
    sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

api_keys_table = sa.Table(
    "api_keys",
    sa.MetaData(),
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("name", sa.String(length=255), nullable=False, unique=True),
    sa.Column("key_hash", sa.String(length=255), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
)


def upgrade() -> None:
    bind = op.get_bind()
    settings_table.create(bind, checkfirst=True)
    api_keys_table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    api_keys_table.drop(bind, checkfirst=True)
    settings_table.drop(bind, checkfirst=True)
