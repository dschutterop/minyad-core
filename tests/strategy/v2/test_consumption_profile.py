from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from minyad.strategy.v2 import ConsumptionProfile
from minyad.strategy.v2.consumption_profile import build_profile_from_rows, slot_of

TZ = ZoneInfo("Europe/Amsterdam")


def test_slot_of_uses_local_time():
    # 23:00 UTC in summer is 01:00 Amsterdam (CEST, +2) -> slot 4 (01:00-01:15).
    moment = datetime(2026, 6, 29, 23, 0, tzinfo=UTC)
    assert slot_of(moment, TZ) == 4


def test_build_profile_averages_per_slot():
    # Two rollup rows in the same local slot average together.
    base = datetime(2026, 6, 29, 22, 0, tzinfo=TZ)  # slot 88
    rows = [
        (base, 400),
        (base + timedelta(days=1), 600),
        (base + timedelta(minutes=30), 1000),  # slot 90
    ]
    profile = build_profile_from_rows(rows, tz=TZ)
    assert profile.expected_w(base) == 500.0
    assert profile.expected_w(base + timedelta(minutes=30)) == 1000.0


def test_expected_wh_between_integrates_partial_slots():
    # Flat 400 W profile -> 400 W over 30 minutes = 200 Wh.
    profile = ConsumptionProfile(slot_watts={slot: 400.0 for slot in range(96)}, tz=TZ)
    start = datetime(2026, 6, 29, 21, 7, tzinfo=TZ)
    end = start + timedelta(minutes=30)
    assert abs(profile.expected_wh_between(start, end) - 200.0) < 1e-6


def test_expected_w_falls_back_without_history():
    profile = ConsumptionProfile(slot_watts={}, tz=TZ, fallback_w=300.0)
    assert profile.expected_w(datetime(2026, 6, 29, 3, 0, tzinfo=TZ)) == 300.0
    assert not profile.has_history
