from datetime import datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from minyad.strategy.v2 import ConsumptionProfile, build_floor_schedule, night_horizon
from minyad.strategy.v2.consumption_profile import SLOTS_PER_DAY
from minyad.strategy.v2.floor_schedule import DRIFT_MAX, DRIFT_MIN

TZ = ZoneInfo("Europe/Amsterdam")


def night_profile() -> ConsumptionProfile:
    """Realistic load: a high evening, a low overnight trough, a daytime base."""
    slot_watts: dict[int, float] = {}
    for slot in range(SLOTS_PER_DAY):
        hour = (slot * 15) // 60
        if hour >= 21 or hour < 1:
            slot_watts[slot] = 700.0  # evening cooking/lights
        elif 1 <= hour < 7:
            slot_watts[slot] = 300.0  # overnight trough
        else:
            slot_watts[slot] = 450.0  # daytime base (irrelevant to night horizon)
    return ConsumptionProfile(slot_watts=slot_watts, tz=TZ)


def horizon(start_day: datetime) -> tuple[datetime, datetime]:
    return night_horizon(start_day, time(21, 0), time(7, 0), tz=TZ)


def step_range(start: datetime, end: datetime, minutes: int = 15):
    cursor = start
    while cursor < end:
        yield cursor
        cursor += timedelta(minutes=minutes)


def test_normal_night_drift_near_one_and_monotone_glide():
    profile = night_profile()
    start = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = horizon(start)
    schedule = build_floor_schedule(h_start, 80.0, 20.0, h_start, h_end, profile)

    floors = []
    prev = h_start
    for now in step_range(h_start + timedelta(minutes=15), h_end + timedelta(minutes=15)):
        # Feed actual consumption exactly equal to the expectation for the slot.
        hours = (now - prev).total_seconds() / 3600.0
        matched_w = profile.expected_wh_between(prev, now) / hours
        schedule.observe(now, matched_w)
        floors.append(schedule.recompute(now, 80.0))
        prev = now

    # Actual tracks expected, so drift collapses to ~1.0.
    assert abs(schedule.drift_factor - 1.0) < 1e-6
    # Floor glides down monotonically...
    assert all(b <= a + 1e-9 for a, b in pairwise(floors))
    # ...starting well above the hard floor and ending exactly on it.
    assert floors[0] > 60.0
    assert abs(floors[-1] - 20.0) < 1e-6


def test_consumption_spike_clamps_drift_factor():
    profile = night_profile()
    start = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = horizon(start)

    spike_at = datetime(2026, 6, 30, 0, 0, tzinfo=TZ)

    def run(spike_w: float) -> "tuple[float, float]":
        schedule = build_floor_schedule(h_start, 80.0, 20.0, h_start, h_end, profile)
        prev = h_start
        drift_at_spike = 1.0
        for now in step_range(h_start + timedelta(minutes=15), spike_at + timedelta(minutes=15)):
            hours = (now - prev).total_seconds() / 3600.0
            # Feed matched consumption every slot except one mid-night spike.
            schedule.observe(now, spike_w if now == spike_at else profile.expected_wh_between(prev, now) / hours)
            floor = schedule.recompute(now, 80.0)
            if now == spike_at:
                drift_at_spike = schedule.drift_factor
                floor_at_spike = floor
            prev = now
        return floor_at_spike, drift_at_spike

    spike_floor, spike_drift = run(6000.0)
    matched_floor, matched_drift = run(profile.expected_w(spike_at))

    # A violent mid-night peak pushes raw drift past the cap; it is clamped.
    assert spike_drift == DRIFT_MAX
    assert DRIFT_MIN <= spike_drift <= DRIFT_MAX
    assert abs(matched_drift - 1.0) < 1e-6
    # The clamped over-consumption keeps a strictly higher reserve than a normal night.
    assert spike_floor > matched_floor


def test_june_29_to_30_winds_down_instead_of_cliffing():
    """Reproduce the 03:30 cliff and show the schedule descends gradually."""
    profile = night_profile()
    start = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = horizon(start)
    assert h_start == datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    assert h_end == datetime(2026, 6, 30, 7, 0, tzinfo=TZ)

    static_floor = 20.0
    schedule = build_floor_schedule(h_start, 75.0, static_floor, h_start, h_end, profile)

    curve: dict[datetime, float] = {}
    prev = h_start
    # Hold SoC high so we observe the planned glide path itself (real SoC tracks below).
    for now in step_range(h_start + timedelta(minutes=15), h_end + timedelta(minutes=1)):
        hours = (now - prev).total_seconds() / 3600.0
        matched_w = profile.expected_wh_between(prev, now) / hours
        schedule.observe(now, matched_w)
        curve[now] = schedule.recompute(now, 75.0)
        prev = now

    floors = list(curve.values())
    # Monotone non-increasing: a descending staircase, never a step back up.
    assert all(b <= a + 1e-9 for a, b in pairwise(floors))
    # No cliff: the largest single 15-minute drop stays gentle, unlike the
    # static floor's instant 0%->full discharge block.
    max_drop = max(a - b for a, b in pairwise(floors))
    assert max_drop < 6.0

    # At 03:30 — where the static floor cliffed — the dynamic floor sits between
    # the hard floor and the start SoC: discharge is already being rationed,
    # not unrestricted-then-blocked.
    floor_0330 = curve[datetime(2026, 6, 30, 3, 30, tzinfo=TZ)]
    assert static_floor < floor_0330 < 75.0
    # And it is meaningfully above the static floor the old logic would apply.
    assert floor_0330 - static_floor > 5.0

    # Horizon end lands exactly on the hard floor.
    assert abs(floors[-1] - static_floor) < 1e-6


def test_floor_never_exceeds_current_soc():
    profile = night_profile()
    start = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = horizon(start)
    schedule = build_floor_schedule(h_start, 80.0, 20.0, h_start, h_end, profile)

    # SoC has already dropped below the planned glide early in the night.
    now = h_start + timedelta(minutes=30)
    schedule.observe(now, 300.0)
    floor = schedule.recompute(now, 40.0)
    assert floor <= 40.0
    assert floor >= 20.0
