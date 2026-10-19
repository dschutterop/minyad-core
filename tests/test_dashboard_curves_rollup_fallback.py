"""dashboard_curves falls back to 15-minute rollups for past days without raw points."""

import asyncio
import os
from datetime import UTC, datetime

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.routers import dashboard as dashboard_router

ROLLUP_ROW = {
    "ts": datetime(2026, 6, 14, 10, 0),
    "source": "solar",
    "power_w": 1500.0,
    "delivered_w": None,
    "returned_w": None,
    "net_w": None,
}


class FakeSession:
    def __init__(self, raw_rows, rollup_rows):
        self.raw_rows = raw_rows
        self.rollup_rows = rollup_rows
        self.tables = []
        self._current = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        table = "power_curve_rollups" if "from power_curve_rollups" in sql else "power_curve_points"
        self.tables.append(table)
        self._current = self.rollup_rows if table == "power_curve_rollups" else self.raw_rows
        return self

    def mappings(self):
        return self

    def all(self):
        return list(self._current)


async def _no_plan(session, now_, end, step_seconds):  # noqa: RUF029
    return "missing", None, {key: [] for key in (
        "forecast", "load_forecast", "battery_forecast", "grid_forecast",
        "curtailment_forecast", "pv_p10_forecast", "pv_p90_forecast",
    )}, []


def _curves(session, offset, monkeypatch):
    monkeypatch.setattr(dashboard_router, "_dashboard_forecast_curves", _no_plan)
    return asyncio.run(dashboard_router.dashboard_curves(session, window="day", offset=offset))


def test_past_day_without_raw_points_uses_rollups(monkeypatch):
    session = FakeSession([], [ROLLUP_ROW])
    result = _curves(session, -1, monkeypatch)
    assert session.tables == ["power_curve_points", "power_curve_rollups"]
    assert result["granularity_seconds"] == 900
    assert result["series"]["solar"][0]["power_w"] == 1500
    assert result["series"]["solar"][0]["timestamp"] == datetime(2026, 6, 14, 10, tzinfo=UTC).isoformat()


def test_past_day_with_raw_points_skips_rollups(monkeypatch):
    session = FakeSession([ROLLUP_ROW], [])
    result = _curves(session, -1, monkeypatch)
    assert session.tables == ["power_curve_points"]
    assert result["granularity_seconds"] == 60


def test_today_never_falls_back(monkeypatch):
    session = FakeSession([], [ROLLUP_ROW])
    result = _curves(session, None, monkeypatch)
    assert session.tables == ["power_curve_points"]
    assert result["series"]["solar"] == []
