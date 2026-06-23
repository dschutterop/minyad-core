import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from datetime import datetime, timedelta, timezone

from api.main import dashboard_window_bounds


def test_day_dashboard_window_starts_at_local_midnight(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc)

    start, end = dashboard_window_bounds("day", timedelta(days=1), now)

    assert start == datetime(2026, 6, 22, 22, 0, tzinfo=timezone.utc)
    assert end == now


def test_non_day_dashboard_windows_stay_rolling(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=timezone.utc)

    start, end = dashboard_window_bounds("hour", timedelta(hours=1), now)

    assert start == datetime(2026, 6, 23, 9, 30, tzinfo=timezone.utc)
    assert end == now
