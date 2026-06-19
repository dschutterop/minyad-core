"""household load power curve source

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_power_curve_points_source", "power_curve_points", type_="check")
    op.create_check_constraint(
        "ck_power_curve_points_source",
        "power_curve_points",
        "source in ('solar','battery','grid','household')",
    )
    op.drop_constraint("ck_power_curve_rollups_source", "power_curve_rollups", type_="check")
    op.create_check_constraint(
        "ck_power_curve_rollups_source",
        "power_curve_rollups",
        "source in ('solar','battery','grid','household')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_power_curve_rollups_source", "power_curve_rollups", type_="check")
    op.create_check_constraint(
        "ck_power_curve_rollups_source",
        "power_curve_rollups",
        "source in ('solar','battery','grid')",
    )
    op.drop_constraint("ck_power_curve_points_source", "power_curve_points", type_="check")
    op.create_check_constraint(
        "ck_power_curve_points_source",
        "power_curve_points",
        "source in ('solar','battery','grid')",
    )
