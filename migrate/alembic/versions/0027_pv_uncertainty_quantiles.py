"""minyad_forecast contract: P25/P50 + quantile grid on pv_uncertainty_bands

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable and backfilled by the next daily RollingPlanner uncertainty-band recompute
    # (upsert keyed on calibration_date/cloud_class) — no data migration needed. Rows without
    # a quantile_grid yet simply can't back a scenario forecast until then; the API layer
    # treats that as "insufficient scenario data" rather than fabricating one.
    op.add_column("pv_uncertainty_bands", sa.Column("p25_multiplier", sa.REAL(), nullable=True))
    op.add_column("pv_uncertainty_bands", sa.Column("p50_multiplier", sa.REAL(), nullable=True))
    op.add_column("pv_uncertainty_bands", sa.Column("quantile_grid", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("pv_uncertainty_bands", "quantile_grid")
    op.drop_column("pv_uncertainty_bands", "p50_multiplier")
    op.drop_column("pv_uncertainty_bands", "p25_multiplier")
