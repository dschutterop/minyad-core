"""dashboard forecast v1: site config, slot_plans vintage metadata

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("slot_plans", sa.Column("strategy_version", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            """
            insert into settings (key, value, encrypted) values
              ('site.latitude', '51.9788', false),
              ('site.longitude', '4.3158', false),
              ('site.pv_peak_w', '5000', false),
              ('site.inverter_ac_max_w', '4600', false)
            on conflict (key) do nothing
            """
        )
    )

    # dashboard_forecast_v1 spec 3.1: api/main.py no longer writes to this table
    # (the v3 planner's slot_plans is now the single forecast source). Kept for
    # historical data only.
    op.execute(sa.text("comment on table solar_forecast_points is 'DEPRECATED: superseded by slot_plans (dashboard_forecast_v1); kept for historical data only'"))


def downgrade() -> None:
    op.execute(sa.text("comment on table solar_forecast_points is null"))
    op.execute(
        sa.text(
            """
            delete from settings where key in (
              'site.latitude', 'site.longitude', 'site.pv_peak_w', 'site.inverter_ac_max_w'
            )
            """
        )
    )
    op.drop_column("slot_plans", "strategy_version")
