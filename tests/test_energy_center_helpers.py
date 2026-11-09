"""Unit tests for the Energy Command Center's pure view-model helpers in
api.payload_helpers: day-kWh integration, the canonical self-sufficiency
definition, SoC threshold alerts, freshness classification, sign-label
mapping and alert assembly. These are the sign/threshold/freshness decisions
the new dashboard (frontend/views.py energy_center_body) relies on, so they
are covered directly rather than only through the page's JS.
"""

import os

import pytest

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.payload_helpers import (
    battery_direction_label,
    battery_soc_alert,
    build_energy_center_alerts,
    canonical_self_sufficiency_pct,
    connection_state,
    freshness_state,
    grid_direction_label,
    integrate_day_kwh,
    integrate_day_kwh_checked,
    reading_age_seconds,
    sun_times,
    supply_mix,
)


# --------------------------------------------------------------------------- #
# integrate_day_kwh
# --------------------------------------------------------------------------- #
def test_integrate_day_kwh_trapezoidal():
    points = [
        {"timestamp": "2026-06-01T10:00:00+00:00", "power_w": 1000},
        {"timestamp": "2026-06-01T11:00:00+00:00", "power_w": 2000},
    ]
    # Trapezoid average over 1 hour: (1000+2000)/2 / 1000 kW * 1h = 1.5 kWh
    assert integrate_day_kwh(points, lambda p: p["power_w"]) == pytest.approx(1.5)


def test_integrate_day_kwh_skips_large_gaps():
    points = [
        {"timestamp": "2026-06-01T00:00:00+00:00", "power_w": 1000},
        {"timestamp": "2026-06-01T06:00:00+00:00", "power_w": 1000},  # offline window, not bridged
        {"timestamp": "2026-06-01T06:01:00+00:00", "power_w": 1000},
    ]
    result = integrate_day_kwh(points, lambda p: p["power_w"])
    # Only the final 1-minute segment should count: 1kW * 1/60h
    assert result == pytest.approx(1000 / 1000 * (1 / 60))


def test_integrate_day_kwh_empty_or_single_point():
    assert integrate_day_kwh([], lambda p: p["power_w"]) == 0.0
    assert integrate_day_kwh([{"timestamp": "2026-06-01T00:00:00+00:00", "power_w": 500}], lambda p: p["power_w"]) == 0.0


def test_integrate_day_kwh_ignores_points_with_bad_timestamps():
    points = [
        {"timestamp": "not-a-timestamp", "power_w": 1000},
        {"timestamp": "2026-06-01T01:00:00+00:00", "power_w": 1000},
    ]
    assert integrate_day_kwh(points, lambda p: p["power_w"]) == 0.0


# --------------------------------------------------------------------------- #
# canonical_self_sufficiency_pct
# --------------------------------------------------------------------------- #
def test_self_sufficiency_matches_classic_dashboard_formula():
    # produced=5, exported=1 -> used=4; imported=2 -> 4/(4+2) = 66.7%
    assert canonical_self_sufficiency_pct(5.0, 1.0, 2.0) == pytest.approx(66.66666, rel=1e-4)


def test_self_sufficiency_full_coverage_clamped_to_100():
    assert canonical_self_sufficiency_pct(10.0, 0.0, 0.0) == 100.0


def test_self_sufficiency_missing_input_is_unavailable():
    assert canonical_self_sufficiency_pct(None, 1.0, 2.0) is None
    assert canonical_self_sufficiency_pct(5.0, None, 2.0) is None
    assert canonical_self_sufficiency_pct(5.0, 1.0, None) is None


def test_self_sufficiency_zero_supply_is_unavailable_not_zero_or_hundred():
    # No solar kept on-site and no import recorded for the day at all.
    assert canonical_self_sufficiency_pct(0.0, 0.0, 0.0) is None


def test_self_sufficiency_never_negative_despite_export_exceeding_production():
    # Export larger than production shouldn't be possible, but a negative
    # "used" must still clamp to zero rather than go negative/above 100.
    assert canonical_self_sufficiency_pct(1.0, 5.0, 2.0) == 0.0


# --------------------------------------------------------------------------- #
# battery_soc_alert -- spec's explicit acceptance-criteria case: SOC=14%, floor=15%
# --------------------------------------------------------------------------- #
def test_soc_14_floor_15_is_not_healthy():
    alert = battery_soc_alert(14, 15, 90)
    assert alert is not None
    assert alert["severity"] == "warning"
    assert "15" in alert["description"]


def test_soc_within_window_has_no_alert():
    assert battery_soc_alert(50, 15, 90) is None
    assert battery_soc_alert(15, 15, 90) is None  # at the floor is not "below"


def test_soc_far_below_floor_is_critical():
    alert = battery_soc_alert(3, 15, 90)
    assert alert["severity"] == "critical"


def test_soc_above_ceiling_is_warning():
    alert = battery_soc_alert(95, 15, 90)
    assert alert["severity"] == "warning"
    assert "maximum" in alert["title"]


def test_soc_alert_none_when_soc_or_limits_missing():
    assert battery_soc_alert(None, 15, 90) is None
    assert battery_soc_alert(14, None, None) is None


# --------------------------------------------------------------------------- #
# freshness_state
# --------------------------------------------------------------------------- #
def test_freshness_state_thresholds():
    assert freshness_state(10, 60) == "live"
    assert freshness_state(120, 60) == "live"  # exactly 2x
    assert freshness_state(121, 60) == "delayed"
    assert freshness_state(300, 60) == "delayed"  # exactly 5x
    assert freshness_state(301, 60) == "offline"


def test_freshness_state_missing_age_is_offline():
    assert freshness_state(None, 60) == "offline"
    assert freshness_state(10, 0) == "offline"


# --------------------------------------------------------------------------- #
# sign/direction labels -- spec's PV=0.01/home=0.40/grid=+0.39/battery=0.00 case
# --------------------------------------------------------------------------- #
def test_grid_and_battery_direction_labels_match_acceptance_snapshot():
    assert grid_direction_label(0.39) == "import"
    assert battery_direction_label(0.00) == "idle"


def test_grid_direction_label_sign_mapping():
    assert grid_direction_label(1.0) == "import"
    assert grid_direction_label(-1.0) == "export"
    assert grid_direction_label(0.0) == "neutral"
    assert grid_direction_label(None) == "unknown"


def test_battery_direction_label_sign_mapping():
    assert battery_direction_label(1.0) == "discharge"
    assert battery_direction_label(-1.0) == "charge"
    assert battery_direction_label(0.0) == "idle"
    assert battery_direction_label(None) == "unknown"


# --------------------------------------------------------------------------- #
# build_energy_center_alerts
# --------------------------------------------------------------------------- #
def test_build_alerts_empty_means_all_clear():
    alerts = build_energy_center_alerts(soc_alert=None, household=None, health_components=None, plan_status="ok")
    assert alerts == []


def test_build_alerts_soc_mismatch_and_health_are_all_included_and_ranked():
    soc_alert = {"id": "x", "severity": "warning", "title": "t", "description": "d"}
    household = {"mismatch": True, "deviation_pct": 22.5}
    health_components = [
        {"name": "DSMR / grid meter", "status": "error", "detail": "offline", "last_seen": None, "endpoint": "/dsmr/status"},
        {"name": "Trade prices", "status": "ok", "detail": "fine"},
    ]
    alerts = build_energy_center_alerts(soc_alert=soc_alert, household=household, health_components=health_components, plan_status="stale")
    severities = [a["severity"] for a in alerts]
    # critical (health error) ranked before warning (soc/mismatch) before info (plan status)
    assert severities[0] == "critical"
    assert severities[-1] == "info"
    assert len(alerts) == 4


def test_build_alerts_plan_status_ok_produces_no_forecast_alert():
    alerts = build_energy_center_alerts(soc_alert=None, household=None, health_components=None, plan_status="ok")
    assert all(a["id"] != "forecast-plan-unavailable" for a in alerts)


# --------------------------------------------------------------------------- #
# connection_state / reading_age_seconds / integrate_day_kwh_checked
# --------------------------------------------------------------------------- #


def test_connection_state_uses_worst_source_and_health_floor():
    assert connection_state([3, 5], "ok") == "live"
    assert connection_state([3, 40], "ok") == "delayed"
    assert connection_state([3, 120], "ok") == "offline"
    assert connection_state([3, 5], "warning") == "delayed"  # health is a floor
    assert connection_state([3, 5], "error") == "offline"


def test_connection_state_is_never_live_without_any_timestamp():
    assert connection_state([None, None], "ok") == "delayed"
    assert connection_state([], "ok") == "delayed"
    assert connection_state([], "error") == "offline"


def test_reading_age_seconds_handles_missing_and_future_timestamps():
    from datetime import UTC, datetime

    now = datetime(2026, 6, 1, 10, 0, 10, tzinfo=UTC)
    assert reading_age_seconds("2026-06-01T10:00:00+00:00", now) == 10.0
    assert reading_age_seconds(None, now) is None
    assert reading_age_seconds("not a date", now) is None
    assert reading_age_seconds("2026-06-01T10:00:30+00:00", now) == 0.0  # clock skew is not negative age


def _pt(hour, minute, w):
    return {"timestamp": f"2026-06-01T{hour:02d}:{minute:02d}:00+00:00", "power_w": w}


def test_integrate_day_kwh_checked_none_when_nothing_to_integrate():
    assert integrate_day_kwh_checked([], lambda p: p["power_w"]) == (None, 0.0)
    assert integrate_day_kwh_checked([_pt(8, 0, 100)], lambda p: p["power_w"]) == (None, 0.0)


def test_integrate_day_kwh_checked_zero_power_is_a_real_zero():
    kwh, skipped = integrate_day_kwh_checked([_pt(8, 0, 0), _pt(9, 0, 0)], lambda p: p["power_w"])
    assert kwh == 0.0 and skipped == 0.0


def test_integrate_day_kwh_checked_reports_skipped_gap_hours():
    points = [_pt(8, 0, 1000), _pt(9, 0, 1000), _pt(12, 0, 1000)]
    kwh, skipped = integrate_day_kwh_checked(points, lambda p: p["power_w"])
    assert kwh == 1.0
    assert skipped == 3.0


# --------------------------------------------------------------------------- #
# sun_times / supply_mix
# --------------------------------------------------------------------------- #


def test_sun_times_are_ordered_and_seasonally_plausible_for_the_netherlands():
    from datetime import date
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Amsterdam")
    winter_rise, winter_set = sun_times(51.9788, 4.3158, date(2026, 11, 8), tz)
    summer_rise, summer_set = sun_times(51.9788, 4.3158, date(2026, 6, 21), tz)

    assert winter_rise < winter_set and summer_rise < summer_set
    assert 8.5 < (winter_set - winter_rise).total_seconds() / 3600 < 10
    assert 16 < (summer_set - summer_rise).total_seconds() / 3600 < 17.5
    assert winter_rise.tzinfo is not None and winter_rise.utcoffset().total_seconds() == 3600  # CET in November


def test_sun_times_none_in_polar_night():
    from datetime import date

    assert sun_times(89.0, 0.0, date(2026, 12, 21)) == (None, None)


def test_supply_mix_shares_sum_to_100_of_one_defined_total():
    mix = supply_mix(pv_kwh=1.0, grid_export_kwh=0.2, battery_charge_kwh=0.3, grid_import_kwh=0.5, battery_discharge_kwh=0.1)

    assert mix["totalKwh"] == 1.1
    assert mix["parts"]["solar"] == {"kwh": 0.5, "pct": 45.5}
    assert round(sum(part["pct"] for part in mix["parts"].values())) == 100


def test_supply_mix_unavailable_when_any_input_missing_or_nothing_supplied():
    assert supply_mix(None, 0, 0, 0, 0) is None
    assert supply_mix(1, 0, 0, None, 0) is None
    assert supply_mix(0, 0, 0, 0, 0) is None
