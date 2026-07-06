from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from minyad.strategy.v2.consumption_profile import ConsumptionProfile
from minyad.strategy.v3.consumption_profile import (
    HouseholdLoadProfile,
    fit_temperature_betas,
    split_rows_by_daytype,
)

TZ = ZoneInfo("Europe/Amsterdam")
UTC = timezone.utc


def test_split_rows_by_daytype_classifies_weekday_vs_weekend():
    # 2026-06-29 is a Monday, 2026-07-04 is a Saturday
    monday = datetime(2026, 6, 29, 12, 0, tzinfo=TZ)
    saturday = datetime(2026, 7, 4, 12, 0, tzinfo=TZ)
    rows = [(monday, 500.0), (saturday, 300.0)]
    weekday_rows, weekend_rows, _, _ = split_rows_by_daytype(rows, TZ)
    assert weekday_rows == [(monday, 500.0)]
    assert weekend_rows == [(saturday, 300.0)]


def test_split_rows_by_daytype_enough_days_flag():
    # 6 distinct Mondays -> weekday_ok True; only 2 distinct Saturdays -> weekend_ok False
    first_monday = datetime(2026, 6, 1, 12, 0, tzinfo=TZ)  # 2026-06-01 is a Monday
    first_saturday = datetime(2026, 6, 6, 12, 0, tzinfo=TZ)
    weekday_rows = [(first_monday + timedelta(weeks=i), 500.0) for i in range(6)]
    weekend_rows = [(first_saturday + timedelta(weeks=i), 300.0) for i in range(2)]
    _, _, weekday_ok, weekend_ok = split_rows_by_daytype(weekday_rows + weekend_rows, TZ, min_days=5)
    assert weekday_ok is True
    assert weekend_ok is False


def test_fit_temperature_betas_recovers_known_slope():
    # residual = 50 * heat_excess exactly, all samples in the afternoon daypart (hour 14)
    rows = []
    temp_points = []
    profile_baseline_w = 500.0
    for i, temp_c in enumerate([22.0, 24.0, 26.0, 28.0, 30.0]):
        ts = datetime(2026, 7, 1 + i, 14, 0, tzinfo=UTC)
        heat_excess = max(0.0, temp_c - 22.0)
        rows.append((ts, profile_baseline_w + 50.0 * heat_excess))
        temp_points.append((ts, temp_c))
    betas = fit_temperature_betas(rows, temp_points, lambda ts: profile_baseline_w, TZ, t_ref_c=22.0)
    assert betas["afternoon"] == pytest.approx(50.0)
    assert betas["night"] == 0.0  # no samples in this daypart


def test_fit_temperature_betas_no_heat_excess_samples_is_zero():
    rows = [(datetime(2026, 7, 1, 14, 0, tzinfo=UTC), 500.0)]
    temp_points = [(datetime(2026, 7, 1, 14, 0, tzinfo=UTC), 15.0)]  # below t_ref, no excess
    betas = fit_temperature_betas(rows, temp_points, lambda ts: 500.0, TZ, t_ref_c=22.0)
    assert all(beta == 0.0 for beta in betas.values())


def test_household_load_profile_selects_weekday_vs_weekend():
    weekday = ConsumptionProfile(slot_watts={48: 500.0}, tz=TZ, fallback_w=300.0)  # slot 48 = 12:00
    weekend = ConsumptionProfile(slot_watts={48: 800.0}, tz=TZ, fallback_w=300.0)
    profile = HouseholdLoadProfile(weekday=weekday, weekend=weekend, tz=TZ)
    monday_noon = datetime(2026, 6, 29, 12, 0, tzinfo=TZ)
    saturday_noon = datetime(2026, 7, 4, 12, 0, tzinfo=TZ)
    assert profile.expected_w(monday_noon) == 500.0
    assert profile.expected_w(saturday_noon) == 800.0


def test_household_load_profile_applies_temperature_correction():
    weekday = ConsumptionProfile(slot_watts={56: 500.0}, tz=TZ, fallback_w=300.0)  # slot 56 = 14:00
    weekend = ConsumptionProfile(slot_watts={56: 500.0}, tz=TZ, fallback_w=300.0)
    profile = HouseholdLoadProfile(weekday=weekday, weekend=weekend, temp_betas={"afternoon": 50.0}, t_ref_c=22.0, tz=TZ)
    moment = datetime(2026, 6, 29, 14, 0, tzinfo=TZ)  # Monday afternoon
    assert profile.expected_w(moment, temperature_c=26.0) == 500.0 + 50.0 * 4.0
    assert profile.expected_w(moment, temperature_c=18.0) == 500.0  # below t_ref -> no correction
    assert profile.expected_w(moment) == 500.0  # no temperature supplied -> plain base
