"""Tests for two api.routers.dashboard helpers that had no direct coverage:

_forecast_stale_status is the pure plan-freshness/fallback classifier shared by /api/forecast
and /dashboard/curves (fresh vs. stale vs. missing vs. solver-fallback) — worth testing
directly since it's plain branching logic with no DB involved. latest_pv_uncertainty_bands
builds the optional p25/p50/quantile_grid fields conditionally from nullable DB columns,
which is real (if thin) assembly logic.

The router's actual HTTP handlers (dashboard_curves, api_state, api_surplus, ...) are mostly
SQL-and-glue around helpers that already have their own direct tests (battery_status,
grid_status, build_surplus_payload, build_plan_curves — see test_dashboard_plan_curves.py and
test_api_dashboard_helpers.py), so they aren't duplicated here.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.routers import dashboard as dashboard_router


def run(coro):
    return asyncio.run(coro)


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeSession:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "max(calibration_date)" in sql:
            return self
        return self

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return list(self._rows)


# --------------------------------------------------------------------------- #
# _forecast_stale_status
# --------------------------------------------------------------------------- #
def test_forecast_stale_status_missing_when_no_plan_and_no_prior_status():
    now_ = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert dashboard_router._forecast_stale_status(None, None, now_) == "missing"


def test_forecast_stale_status_fallback_when_no_plan_but_latest_was_fallback():
    now_ = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert dashboard_router._forecast_stale_status(None, "FALLBACK", now_) == "fallback"


def test_forecast_stale_status_none_when_plan_is_fresh():
    now_ = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    plan_row = {"generated_at": now_ - timedelta(minutes=5)}
    assert dashboard_router._forecast_stale_status(plan_row, "OPTIMAL", now_) is None


def test_forecast_stale_status_stale_when_plan_older_than_threshold():
    now_ = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    plan_row = {"generated_at": now_ - timedelta(minutes=dashboard_router.PLAN_STALE_MINUTES + 5)}
    assert dashboard_router._forecast_stale_status(plan_row, "OPTIMAL", now_) == "stale"


def test_forecast_stale_status_treats_naive_generated_at_as_utc():
    now_ = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    plan_row = {"generated_at": (now_ - timedelta(minutes=5)).replace(tzinfo=None)}
    assert dashboard_router._forecast_stale_status(plan_row, "OPTIMAL", now_) is None


# --------------------------------------------------------------------------- #
# latest_pv_uncertainty_bands
# --------------------------------------------------------------------------- #
def test_latest_pv_uncertainty_bands_empty_when_no_calibration_run_yet():
    session = FakeSession(scalar=None)
    assert run(dashboard_router.latest_pv_uncertainty_bands(session)) == {}


def test_latest_pv_uncertainty_bands_omits_null_optional_fields():
    session = FakeSession(
        scalar="2026-06-01",
        rows=[_Row(cloud_class="clear", p10_multiplier=0.5, p90_multiplier=1.2, p25_multiplier=None, p50_multiplier=None, quantile_grid=None)],
    )
    bands = run(dashboard_router.latest_pv_uncertainty_bands(session))
    assert bands == {"clear": {"p10_multiplier": 0.5, "p90_multiplier": 1.2}}


def test_latest_pv_uncertainty_bands_includes_present_optional_fields():
    session = FakeSession(
        scalar="2026-06-01",
        rows=[
            _Row(
                cloud_class="cloudy",
                p10_multiplier=0.3,
                p90_multiplier=1.5,
                p25_multiplier=0.5,
                p50_multiplier=0.9,
                quantile_grid={"p50": [0.1, 0.2]},
            )
        ],
    )
    bands = run(dashboard_router.latest_pv_uncertainty_bands(session))
    assert bands["cloudy"]["p25_multiplier"] == 0.5
    assert bands["cloudy"]["p50_multiplier"] == 0.9
    assert bands["cloudy"]["quantile_grid"] == {"p50": [0.1, 0.2]}
