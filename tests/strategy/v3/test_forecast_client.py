from datetime import datetime
from zoneinfo import ZoneInfo

from minyad.strategy.v3.forecast_client import calibrate_pv_factors, fallback_sunset, interpolate_ghi

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


def test_calibrate_pv_factors_clamped_to_half_and_double():
    prev = [7.0] * 24
    # hour 12: actual way above forecast for every sample -> clamps to 2x prev, then 3-point
    # smoothed with neighbouring (unchanged) hours 11 and 13.
    samples = [(12, 2000.0, 100.0) for _ in range(10)]
    factors = calibrate_pv_factors(samples, prev)
    assert factors[12] == 0.5 * 14.0 + 0.5 * 7.0  # smoothed: 25% h11(7.0) + 50% h12(14.0) + 25% h13(7.0)
    assert factors[11] == 0.75 * 7.0 + 0.25 * 14.0
    assert factors[13] == 0.75 * 7.0 + 0.25 * 14.0
    # every other hour has no samples at all -> stays at prev_factor, unaffected by smoothing
    # against itself.
    assert factors[0] == 7.0


def test_calibrate_pv_factors_exact_ratio_within_clamp_range():
    prev = [7.0] * 24
    samples = [(12, 800.0, 100.0) for _ in range(10)]
    factors = calibrate_pv_factors(samples, prev)
    # exact ratio 8.0 is within [3.5, 14.0], smoothed with untouched neighbours.
    assert factors[12] == 0.5 * 8.0 + 0.5 * 7.0


def test_calibrate_pv_factors_ignores_samples_below_ghi_threshold():
    prev = [7.0] * 24
    # all samples at/under the 50 W/m2 threshold -> excluded, hour keeps its previous factor
    samples = [(12, 2000.0, 50.0) for _ in range(10)]
    factors = calibrate_pv_factors(samples, prev)
    assert factors[12] == 7.0


def test_calibrate_pv_factors_sparse_hour_borrows_neighbours():
    prev = [7.0] * 24
    # hour 12 has one sample of its own -- too few alone (below min_samples_per_hour), but
    # combined with samples borrowed from neighbours 11 and 13 there are enough to move away
    # from the previous factor.
    samples = [(11, 800.0, 100.0), (12, 800.0, 100.0), (13, 800.0, 100.0)]
    factors = calibrate_pv_factors(samples, prev, min_samples_per_hour=3)
    assert factors[12] != 7.0


def test_calibrate_pv_factors_zero_samples_hour_not_borrowed():
    prev = [7.0] * 24
    # hour 12 has abundant samples; hour 11 has none at all -> hour 11 stays at prev rather than
    # inheriting hour 12's factor wholesale.
    samples = [(12, 2000.0, 100.0) for _ in range(10)]
    factors = calibrate_pv_factors(samples, prev)
    assert factors[11] == 0.75 * 7.0 + 0.25 * 14.0


def test_calibrate_pv_factors_empty_samples_keeps_previous():
    prev = [7.0] * 24
    assert calibrate_pv_factors([], prev) == prev


def test_fallback_sunset_is_21_local():
    from datetime import date

    sunset = fallback_sunset(date(2026, 7, 3))
    assert sunset.hour == 21
    assert sunset.tzinfo is not None
