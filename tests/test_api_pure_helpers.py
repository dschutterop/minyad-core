"""Unit tests for pure helper functions and request validators in api.main.

These functions have no database or MQTT dependencies, so they can be exercised
directly.  They complement the endpoint-focused tests in test_api_status_payloads
and cover branches (validators, freshness checks, telemetry enrichment) that were
previously unexercised.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from pydantic import ValidationError

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import (
    AssetSteeringSettingsUpdate,
    BatteryOverrideRequest,
    BatterySettingsUpdate,
    TradeSettingsUpdate,
    _numeric_w,
    _status_text,
    active_battery_setpoint_w,
    component_status,
    enrich_bridge_health,
    parse_bridge_last_seen,
    value_is_fresh_iso,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


# --------------------------------------------------------------------------- #
# parse_bridge_last_seen
# --------------------------------------------------------------------------- #
def test_parse_bridge_last_seen_returns_none_for_empty():
    assert parse_bridge_last_seen(None) is None
    assert parse_bridge_last_seen("") is None


def test_parse_bridge_last_seen_rejects_garbage():
    assert parse_bridge_last_seen("not-a-timestamp") is None


def test_parse_bridge_last_seen_accepts_zulu_and_normalizes_to_utc():
    parsed = parse_bridge_last_seen("2026-06-18T09:24:03Z")
    assert parsed == datetime(2026, 6, 18, 9, 24, 3, tzinfo=UTC)


def test_parse_bridge_last_seen_assumes_utc_for_naive_timestamps():
    parsed = parse_bridge_last_seen("2026-06-18T09:24:03")
    assert parsed is not None
    assert parsed.tzinfo == UTC


def test_parse_bridge_last_seen_converts_offset_to_utc():
    parsed = parse_bridge_last_seen("2026-06-18T11:24:03+02:00")
    assert parsed == datetime(2026, 6, 18, 9, 24, 3, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# value_is_fresh_iso
# --------------------------------------------------------------------------- #
def test_value_is_fresh_iso_rejects_non_string_or_empty():
    assert value_is_fresh_iso(None) == (False, None)
    assert value_is_fresh_iso(123) == (False, None)
    assert value_is_fresh_iso("") == (False, None)


def test_value_is_fresh_iso_rejects_unparseable():
    assert value_is_fresh_iso("nonsense") == (False, None)


def test_value_is_fresh_iso_reports_fresh_recent_timestamp():
    recent = _iso(datetime.now(UTC) - timedelta(seconds=10))
    fresh, age = value_is_fresh_iso(recent, max_age_seconds=120)
    assert fresh is True
    assert 0 <= age <= 15


def test_value_is_fresh_iso_reports_stale_old_timestamp():
    old = _iso(datetime.now(UTC) - timedelta(seconds=600))
    fresh, age = value_is_fresh_iso(old, max_age_seconds=120)
    assert fresh is False
    assert age >= 590


# --------------------------------------------------------------------------- #
# enrich_bridge_health
# --------------------------------------------------------------------------- #
def test_enrich_bridge_health_flags_missing_last_seen_and_marks_online_unavailable():
    payload = {"bridge_status": "online"}
    enrich_bridge_health(payload)
    assert payload["bridge_last_seen_valid"] is False
    assert payload["bridge_last_seen_error"] == "missing or invalid bridge last_seen"
    assert payload["available"] is False


def test_enrich_bridge_health_missing_last_seen_leaves_offline_available_untouched():
    payload = {"bridge_status": "offline"}
    enrich_bridge_health(payload)
    assert payload["bridge_last_seen_valid"] is False
    assert "available" not in payload


def test_enrich_bridge_health_marks_recent_last_seen_valid():
    payload = {
        "bridge_status": "online",
        "bridge_last_seen": _iso(datetime.now(UTC) - timedelta(seconds=5)),
    }
    enrich_bridge_health(payload)
    assert payload["bridge_last_seen_valid"] is True
    assert payload["bridge_last_seen_age_seconds"] <= 10
    assert "available" not in payload


def test_enrich_bridge_health_marks_stale_last_seen_unavailable():
    payload = {
        "bridge_status": "online",
        "bridge_last_seen": _iso(datetime.now(UTC) - timedelta(seconds=120)),
    }
    enrich_bridge_health(payload)
    assert payload["bridge_last_seen_valid"] is False
    assert payload["bridge_last_seen_error"] == "bridge last_seen is older than 60 seconds"
    assert payload["available"] is False


# --------------------------------------------------------------------------- #
# active_battery_setpoint_w
# --------------------------------------------------------------------------- #
def test_active_battery_setpoint_prefers_positive_discharge():
    assert active_battery_setpoint_w({"discharge_w": "-800"}) == 800


def test_active_battery_setpoint_negates_charge_setpoint():
    assert active_battery_setpoint_w({"setpoint_w": "600"}) == -600


def test_active_battery_setpoint_none_when_idle():
    assert active_battery_setpoint_w({"discharge_w": "", "setpoint_w": None}) is None
    assert active_battery_setpoint_w({}) is None


def test_active_battery_setpoint_discharge_takes_priority_over_setpoint():
    assert active_battery_setpoint_w({"discharge_w": "400", "setpoint_w": "900"}) == 400


# --------------------------------------------------------------------------- #
# _numeric_w and _status_text
# --------------------------------------------------------------------------- #
def test_numeric_w_parses_float_strings_to_int():
    assert _numeric_w({"power_w": "412.7"}, "power_w") == 412


def test_numeric_w_returns_none_for_missing_or_invalid():
    assert _numeric_w({}, "power_w") is None
    assert _numeric_w({"power_w": ""}, "power_w") is None
    assert _numeric_w({"power_w": "n/a"}, "power_w") is None


def test_status_text_uppercases_and_falls_back():
    assert _status_text("charging") == "CHARGING"
    assert _status_text(None) == "UNKNOWN"
    assert _status_text("", fallback="IDLE") == "IDLE"
    assert _status_text("   ") == "UNKNOWN"


# --------------------------------------------------------------------------- #
# component_status
# --------------------------------------------------------------------------- #
def test_component_status_merges_extra_fields():
    result = component_status("API", "ok", "serving", endpoint="/health", extra=1)
    assert result == {"name": "API", "status": "ok", "detail": "serving", "endpoint": "/health", "extra": 1}


# --------------------------------------------------------------------------- #
# AssetSteeringSettingsUpdate.validate_local_time
# --------------------------------------------------------------------------- #
def test_asset_steering_accepts_valid_local_time():
    update = AssetSteeringSettingsUpdate(daily_recalculate_local_time="06:30")
    assert update.daily_recalculate_local_time == "06:30"


def test_asset_steering_allows_missing_local_time():
    assert AssetSteeringSettingsUpdate().daily_recalculate_local_time is None


@pytest.mark.parametrize("value", ["24:00", "noon", "12:60", ""])
def test_asset_steering_rejects_invalid_local_time(value):
    with pytest.raises(ValidationError):
        AssetSteeringSettingsUpdate(daily_recalculate_local_time=value)


# --------------------------------------------------------------------------- #
# TradeSettingsUpdate.validate_poll_time
# --------------------------------------------------------------------------- #
def test_trade_settings_accepts_valid_poll_time():
    assert TradeSettingsUpdate(poll_time_local="13:45").poll_time_local == "13:45"


@pytest.mark.parametrize("value", ["25:00", "1345", "aa:bb"])
def test_trade_settings_rejects_invalid_poll_time(value):
    with pytest.raises(ValidationError):
        TradeSettingsUpdate(poll_time_local=value)


# --------------------------------------------------------------------------- #
# BatterySettingsUpdate.validate_ip
# --------------------------------------------------------------------------- #
def test_battery_settings_accepts_valid_ipv4():
    assert BatterySettingsUpdate(inverter_ip="192.0.2.20").inverter_ip == "192.0.2.20"


def test_battery_settings_allows_missing_ip():
    assert BatterySettingsUpdate().inverter_ip is None


@pytest.mark.parametrize("value", ["192.0.2", "203.0.113.256", "not.an.ip.addr", "1.2.3.4.5", ""])
def test_battery_settings_rejects_invalid_ipv4(value):
    with pytest.raises(ValidationError):
        BatterySettingsUpdate(inverter_ip=value)


# --------------------------------------------------------------------------- #
# BatteryOverrideRequest.validate_required_fields
# --------------------------------------------------------------------------- #
def test_battery_override_requires_watts_for_force_modes():
    BatteryOverrideRequest.model_rebuild(_types_namespace={"Literal": Literal})
    for mode in ("force_on", "force_charge", "force_discharge"):
        with pytest.raises(ValidationError):
            BatteryOverrideRequest(mode=mode)


def test_battery_override_requires_duration_for_pause():
    BatteryOverrideRequest.model_rebuild(_types_namespace={"Literal": Literal})
    with pytest.raises(ValidationError):
        BatteryOverrideRequest(mode="pause")


def test_battery_override_accepts_none_mode_without_extra_fields():
    BatteryOverrideRequest.model_rebuild(_types_namespace={"Literal": Literal})
    request = BatteryOverrideRequest(mode="none")
    assert request.mode == "none"
    assert request.watts is None
