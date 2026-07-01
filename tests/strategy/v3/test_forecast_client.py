from datetime import datetime
from zoneinfo import ZoneInfo

from minyad.strategy.v3.forecast_client import calibrate_pv_factor, fallback_sunset, interpolate_ghi

TZ = ZoneInfo("Europe/Amsterdam")


def test_interpolate_ghi_linear_between_hours():
    points = [
        (datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 100.0),
        (datetime(2026, 7, 3, 11, 0, tzinfo=TZ), 200.0),
    ]
    mid = datetime(2026, 7, 3, 10, 30, tzinfo=TZ)
    assert interpolate_ghi(points, mid) == 150.0


def test_interpolate_ghi_clamps_outside_range():
    points = [
        (datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 100.0),
        (datetime(2026, 7, 3, 11, 0, tzinfo=TZ), 200.0),
    ]
    assert interpolate_ghi(points, datetime(2026, 7, 3, 9, 0, tzinfo=TZ)) == 100.0
    assert interpolate_ghi(points, datetime(2026, 7, 3, 12, 0, tzinfo=TZ)) == 200.0


def test_interpolate_ghi_empty_points_is_zero():
    assert interpolate_ghi([], datetime(2026, 7, 3, 10, 0, tzinfo=TZ)) == 0.0


def test_calibrate_pv_factor_clamped_to_half_and_double():
    # actual way above forecast -> clamp to 2x
    assert calibrate_pv_factor(actual_pv_wh_total=100000, ghi_wh_per_m2_total=1000, prev_factor=7.0) == 14.0
    # actual way below forecast -> clamp to 0.5x
    assert calibrate_pv_factor(actual_pv_wh_total=10, ghi_wh_per_m2_total=1000, prev_factor=7.0) == 3.5
    # actual mid-range -> exact ratio
    assert calibrate_pv_factor(actual_pv_wh_total=8000, ghi_wh_per_m2_total=1000, prev_factor=7.0) == 8.0


def test_calibrate_pv_factor_keeps_previous_when_no_ghi():
    assert calibrate_pv_factor(actual_pv_wh_total=500.0, ghi_wh_per_m2_total=0.0, prev_factor=7.0) == 7.0


def test_fallback_sunset_is_21_local():
    from datetime import date

    sunset = fallback_sunset(date(2026, 7, 3))
    assert sunset.hour == 21
    assert sunset.tzinfo is not None
