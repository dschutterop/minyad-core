import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from datetime import UTC, datetime, timedelta

from api.main import dashboard_window_bounds


def test_day_dashboard_window_starts_at_local_midnight(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=UTC)

    start, end, now_ = dashboard_window_bounds("day", timedelta(days=1), now)

    assert start == datetime(2026, 6, 22, 22, 0, tzinfo=UTC)
    # end should be end-of-local-day, not now
    assert end == datetime(2026, 6, 23, 21, 59, 59, tzinfo=UTC)
    assert now_ == now


def test_non_day_dashboard_windows_stay_rolling(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=UTC)

    start, end, now_ = dashboard_window_bounds("hour", timedelta(hours=1), now)

    assert start == datetime(2026, 6, 23, 9, 30, tzinfo=UTC)
    assert end == now
    assert now_ == now


def test_calendar_week_offset_uses_local_monday_to_sunday(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=UTC)

    start, end, now_ = dashboard_window_bounds("week", timedelta(weeks=1), now, period_offset=-1)

    assert start == datetime(2026, 6, 14, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 21, 21, 59, 59, tzinfo=UTC)
    assert now_ == end


def test_calendar_month_offset_uses_full_local_month(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=UTC)

    start, end, now_ = dashboard_window_bounds("month", timedelta(days=31), now, period_offset=-1)

    assert start == datetime(2026, 4, 30, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 5, 31, 21, 59, 59, tzinfo=UTC)
    assert now_ == end


def test_current_calendar_month_clips_query_at_now(monkeypatch):
    monkeypatch.setenv("MINYAD_TIMEZONE", "Europe/Amsterdam")

    now = datetime(2026, 6, 23, 10, 30, tzinfo=UTC)

    start, end, now_ = dashboard_window_bounds("month", timedelta(days=31), now, period_offset=0)

    assert start == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 30, 21, 59, 59, tzinfo=UTC)
    assert now_ == now
