from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from minyad.strategy.v2 import (
    ConsumptionProfile,
    DayPlan,
    ExecutorState,
    Settings,
    SoCGuard,
    build_floor_schedule,
    night_horizon,
)

TZ = ZoneInfo("Europe/Amsterdam")


def plan():
    return DayPlan(datetime(2026, 6, 27, tzinfo=timezone.utc).date(), "NORMAL", 2.0, 20, 90)


def test_discharge_blocked_at_floor():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=20), plan()) == 0


def test_charge_blocked_at_ceiling():
    guard = SoCGuard(Settings())
    assert guard.apply(500, ExecutorState(0, battery_soc=90), plan()) == 0


def test_soc_limit_bypass_keeps_non_soc_guards_active():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    stale = ExecutorState(0, battery_soc=90, bridge_last_seen=now - timedelta(seconds=181))
    assert guard.apply(500, stale, plan(), now, skip_soc_limits=True) == 0
    assert guard.apply(500, ExecutorState(0, battery_soc=90), plan(), now, skip_soc_limits=True) == 500


def test_bridge_stale_suppresses_setpoint():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    state = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=181))
    assert guard.apply(500, state, plan(), now) == 0
    adjusted, reason = guard.apply_with_reason(500, state, plan(), now)
    assert adjusted == 0
    assert reason == "guard: bridge stale (181s > 180s)"


def test_bridge_stale_guard_tolerates_goodwe_poll_interval():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    state = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=120))
    assert guard.apply(500, state, plan(), now) == 500


def test_bridge_stale_seconds_comes_from_poll_interval_plus_grace():
    guard = SoCGuard(Settings(initial={"battery.inverter_poll_interval_s": "90", "battery.goodwe_poll_interval_grace_s": "15"}))
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    fresh = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=105))
    stale = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=106))
    assert guard.apply(500, fresh, plan(), now) == 500
    adjusted, reason = guard.apply_with_reason(500, stale, plan(), now)
    assert adjusted == 0
    assert reason == "guard: bridge stale (106s > 105s)"


def test_voltage_guard_suppresses_setpoint():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=50, battery_voltage=45.9), plan()) == 0
    adjusted, reason = guard.apply_with_reason(-500, ExecutorState(0, battery_soc=50, battery_voltage=45.9), plan())
    assert adjusted == 0
    assert reason == "guard: battery voltage low (45.9V < 46.0V)"


def test_discharge_stays_blocked_within_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(-500, ExecutorState(0, battery_soc=20), plan())  # engage block
    # SoC at 21% — still inside the 2% band, must remain blocked
    assert guard.apply(-500, ExecutorState(0, battery_soc=21), plan()) == 0


def test_discharge_releases_above_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(-500, ExecutorState(0, battery_soc=20), plan())  # engage block
    # SoC at 22.1% — past floor + band, block should lift
    assert guard.apply(-500, ExecutorState(0, battery_soc=22.1), plan()) == -500


def test_charge_stays_blocked_within_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(500, ExecutorState(0, battery_soc=90), plan())  # engage block
    # SoC at 89% — still inside the 2% band
    assert guard.apply(500, ExecutorState(0, battery_soc=89), plan()) == 0


def test_charge_releases_below_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(500, ExecutorState(0, battery_soc=90), plan())  # engage block
    # SoC at 87.9% — past ceiling - band, block should lift
    assert guard.apply(500, ExecutorState(0, battery_soc=87.9), plan()) == 500


def test_floor_schedule_blocks_discharge_above_static_floor():
    """The dynamic floor gates discharge gradually, above the static floor."""
    profile = ConsumptionProfile(slot_watts={slot: 500.0 for slot in range(96)}, tz=TZ)
    night = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = night_horizon(night, time(21, 0), time(7, 0), tz=TZ)
    schedule = build_floor_schedule(h_start, 80.0, 20.0, h_start, h_end, profile)

    # Early in the night the gliding floor sits well above the static floor (20).
    early = h_start + timedelta(hours=1)
    schedule.observe(early, 500.0)
    floor = schedule.recompute(early, 80.0)
    assert floor > 20.0

    guard = SoCGuard(Settings())
    guard.set_floor_schedule(schedule)
    # SoC at 60% is far above the static floor, but below the dynamic floor:
    # discharge is throttled where the old logic would have allowed it.
    state = ExecutorState(0, battery_soc=floor - 1)
    adjusted, reason = guard.apply_with_reason(-500, state, plan(), early)
    assert adjusted == 0
    assert "SoC floor hold" in reason


def test_floor_schedule_falls_back_to_static_floor_outside_horizon():
    profile = ConsumptionProfile(slot_watts={slot: 500.0 for slot in range(96)}, tz=TZ)
    night = datetime(2026, 6, 29, 21, 0, tzinfo=TZ)
    h_start, h_end = night_horizon(night, time(21, 0), time(7, 0), tz=TZ)
    schedule = build_floor_schedule(h_start, 80.0, 20.0, h_start, h_end, profile)

    guard = SoCGuard(Settings())
    guard.set_floor_schedule(schedule)
    # After horizon end the schedule reports the hard floor, so 50% discharges freely.
    after = h_end + timedelta(minutes=30)
    assert guard.apply(-500, ExecutorState(0, battery_soc=50), plan(), after) == -500
