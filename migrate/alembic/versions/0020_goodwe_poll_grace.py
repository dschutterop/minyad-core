"""Derive bridge stale threshold from GoodWe poll cadence

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted, updated_at)
            values ('battery.goodwe_poll_interval_grace_s', '60', false, now())
            on conflict (key) do nothing
            """
        )
    )
    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted, updated_at)
            values (
                'strategy.bridge_stale_seconds',
                (
                    coalesce((select value::integer from settings where key = 'battery.inverter_poll_interval_s'), 120)
                    + coalesce((select value::integer from settings where key = 'battery.goodwe_poll_interval_grace_s'), 60)
                )::text,
                false,
                now()
            )
            on conflict (key) do update set value = excluded.value, encrypted = false, updated_at = now()
            where settings.value in ('60', '180')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "update settings set value = '60', updated_at = now() "
            "where key = 'strategy.bridge_stale_seconds' and value = '180'"
        )
    )
    op.execute(sa.text("delete from settings where key = 'battery.goodwe_poll_interval_grace_s'"))
