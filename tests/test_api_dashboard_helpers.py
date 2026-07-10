"""Tests for dashboard curve math and row-serialization helpers in api.main.

These are pure functions (plus one fake-session-backed override lookup) covering
interpolation, plan-slot battery math, cloud classification, log-datetime parsing
and the various row serializers used by the agent/message/decision endpoints.
"""

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api import main as api_main  # noqa: E402
from tests.test_api_settings_endpoints import FakeResult, FakeSession  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# interpolate_points
# --------------------------------------------------------------------------- #
def test_interpolate_points_returns_input_when_too_few():
    points = [{"timestamp": "2026-06-01T00:00:00+00:00", "power_w": 100}]
    assert api_main.interpolate_points(points, 60) is points


def test_interpolate_points_returns_input_for_coarse_step():
    points = [
        {"timestamp": "2026-06-01T00:00:00+00:00", "power_w": 0},
        {"timestamp": "2026-06-01T00:15:00+00:00", "power_w": 900},
    ]
    assert api_main.interpolate_points(points, 900) is points


def test_interpolate_points_fills_intermediate_values():
    points = [
        {"timestamp": "2026-06-01T00:00:00+00:00", "power_w": 0},
        {"timestamp": "2026-06-01T00:10:00+00:00", "power_w": 600},
    ]
    out = api_main.interpolate_points(points, 300)
    # 0, +5min (halfway -> 300), and the final endpoint
    assert out[0]["power_w"] == 0
    assert out[1]["power_w"] == 300
    assert out[-1]["power_w"] == 600
    assert out[-1]["timestamp"].startswith("2026-06-01T00:10:00")


# --------------------------------------------------------------------------- #
# _bucket_expr
# --------------------------------------------------------------------------- #
def test_bucket_expr_builds_floor_sql():
    assert api_main._bucket_expr("timestamp", 300) == (
        "to_timestamp(floor(extract(epoch from timestamp) / 300) * 300)"
    )


# --------------------------------------------------------------------------- #
# _slot_battery_w
# --------------------------------------------------------------------------- #
def test_slot_battery_w_zero_slot_seconds_is_zero():
    assert api_main._slot_battery_w(50.0, 60.0, 10000, 0) == 0


def test_slot_battery_w_charging_is_negative():
    # SoC rising over the slot => charging => negative (GoodWe convention)
    assert api_main._slot_battery_w(50.0, 60.0, 10000.0, 3600) == -1000


def test_slot_battery_w_discharging_is_positive():
    assert api_main._slot_battery_w(60.0, 50.0, 10000.0, 3600) == 1000


# --------------------------------------------------------------------------- #
# _classify_cloud_cover
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "pct,expected",
    [(0.0, "clear"), (24.9, "clear"), (25.0, "partly"), (74.9, "partly"), (75.0, "cloudy"), (100.0, "cloudy")],
)
def test_classify_cloud_cover(pct, expected):
    assert api_main._classify_cloud_cover(pct) == expected


# --------------------------------------------------------------------------- #
# dashboard_window_bounds — period_offset branches
# --------------------------------------------------------------------------- #
def test_dashboard_window_bounds_day_offset():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    start, end, query_until = api_main.dashboard_window_bounds("day", timedelta(days=1), now=now, period_offset=-1)
    assert start < end
    assert query_until == min(now, end)


def test_dashboard_window_bounds_naive_now_is_treated_as_utc():
    naive = datetime(2026, 6, 15, 12, 0)
    start, end, _ = api_main.dashboard_window_bounds("day", timedelta(days=1), now=naive)
    assert start.tzinfo is not None


@pytest.mark.parametrize("window", ["week", "month", "year"])
def test_dashboard_window_bounds_offset_windows(window):
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    start, end, query_until = api_main.dashboard_window_bounds(window, timedelta(days=1), now=now, period_offset=-1)
    assert start < end
    assert query_until <= now


def test_dashboard_window_bounds_non_day_without_offset_uses_duration():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    start, end, query_until = api_main.dashboard_window_bounds("hour", timedelta(hours=6), now=now)
    assert end == now
    assert start == now - timedelta(hours=6)
    assert query_until == now


# --------------------------------------------------------------------------- #
# serialize_agent_decision
# --------------------------------------------------------------------------- #
def test_serialize_agent_decision_parses_json_snapshot():
    row = {"created_at": datetime(2026, 6, 1, 8, 0), "input_snapshot": json.dumps({"soc": 50})}
    data = api_main.serialize_agent_decision(row)
    assert data["created_at"] == "2026-06-01T08:00:00+00:00"
    assert data["input_snapshot"] == {"soc": 50}


def test_serialize_agent_decision_wraps_invalid_json_snapshot():
    row = {"created_at": None, "input_snapshot": "{not-json"}
    data = api_main.serialize_agent_decision(row)
    assert data["input_snapshot"] == {"raw": "{not-json"}


# --------------------------------------------------------------------------- #
# _parse_log_datetime
# --------------------------------------------------------------------------- #
def test_parse_log_datetime_none():
    assert api_main._parse_log_datetime(None) is None


def test_parse_log_datetime_zulu_and_naive():
    assert api_main._parse_log_datetime("2026-06-01T08:00:00Z") == datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    assert api_main._parse_log_datetime("2026-06-01T08:00:00").tzinfo == timezone.utc


# --------------------------------------------------------------------------- #
# _serialize_log_row
# --------------------------------------------------------------------------- #
def test_serialize_log_row_serializes_datetime_and_date():
    row = {"ts": datetime(2026, 6, 1, 8, 0), "day": date(2026, 6, 1), "count": 3}
    data = api_main._serialize_log_row(row)
    assert data["ts"] == "2026-06-01T08:00:00+00:00"
    assert data["day"] == "2026-06-01"
    assert data["count"] == 3


# --------------------------------------------------------------------------- #
# _normalize_battery_override_mode
# --------------------------------------------------------------------------- #
def test_normalize_battery_override_mode():
    assert api_main._normalize_battery_override_mode("force_on") == "force_charge"
    assert api_main._normalize_battery_override_mode("force_off") == "force_idle"
    assert api_main._normalize_battery_override_mode("force_discharge") == "force_discharge"
    assert api_main._normalize_battery_override_mode(None) == "none"


# --------------------------------------------------------------------------- #
# serialize_agent_message
# --------------------------------------------------------------------------- #
def test_serialize_agent_message_serializes_all_timestamps():
    ts = datetime(2026, 6, 1, 8, 0)
    row = {
        "created_at": ts,
        "read_at": None,
        "archived_at": ts,
        "operator_ack_at": None,
        "agent_ack_at": ts,
        "subject": "hi",
    }
    data = api_main.serialize_agent_message(row)
    assert data["created_at"] == "2026-06-01T08:00:00+00:00"
    assert data["read_at"] is None
    assert data["archived_at"] == "2026-06-01T08:00:00+00:00"
    assert data["subject"] == "hi"


# --------------------------------------------------------------------------- #
# current_battery_override (fake session)
# --------------------------------------------------------------------------- #
def test_current_battery_override_none_when_mode_none():
    session = FakeSession([("from battery_override", FakeResult(rows=[{"mode": "none"}]))])
    assert run(api_main.current_battery_override(session)) is None


def test_current_battery_override_none_when_expired():
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    row = {"mode": "force_charge", "watts": 700, "duration_seconds": 900, "expires_at": expired, "override_soc_limits": False}
    session = FakeSession([("from battery_override", FakeResult(rows=[row]))])
    assert run(api_main.current_battery_override(session)) is None


def test_current_battery_override_active():
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    row = {"mode": "force_discharge", "watts": 900, "duration_seconds": 900, "expires_at": future, "override_soc_limits": True}
    session = FakeSession([("from battery_override", FakeResult(rows=[row]))])
    result = run(api_main.current_battery_override(session))
    assert result["mode"] == "force_discharge"
    assert result["override_soc_limits"] is True
    assert result["preserved"] is True
