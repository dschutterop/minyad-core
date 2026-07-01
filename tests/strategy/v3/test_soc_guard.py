from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.constants import Settings
from minyad.strategy.v3.models import ExecutorState
from minyad.strategy.v3.soc_guard import SoCGuard


def test_discharge_blocked_at_floor():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=20), 20.0, 90.0) == 0


def test_charge_blocked_at_ceiling():
    guard = SoCGuard(Settings())
    assert guard.apply(500, ExecutorState(0, battery_soc=90), 20.0, 90.0) == 0


def test_invariant_4_bridge_stale_forces_zero_even_with_soc_limit_skip():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    stale = ExecutorState(0, battery_soc=90, bridge_last_seen=now - timedelta(seconds=181))
    assert guard.apply(500, stale, 20.0, 90.0, now, skip_soc_limits=True) == 0
    # sanity: skip_soc_limits does let a *fresh* bridge bypass SoC limits
    assert guard.apply(500, ExecutorState(0, battery_soc=90), 20.0, 90.0, now, skip_soc_limits=True) == 500


def test_bridge_stale_suppresses_setpoint():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    state = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=181))
    assert guard.apply(500, state, 20.0, 90.0, now) == 0
    adjusted, reason = guard.apply_with_reason(500, state, 20.0, 90.0, now)
    assert adjusted == 0
    assert reason == "guard: bridge stale (181s > 180s)"


def test_invariant_5_low_voltage_forces_zero_regardless_of_soc():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=50, battery_voltage=45.9), 20.0, 90.0) == 0
    adjusted, reason = guard.apply_with_reason(-500, ExecutorState(0, battery_soc=50, battery_voltage=45.9), 20.0, 90.0)
    assert adjusted == 0
    assert reason == "guard: battery voltage low (45.9V < 46.0V)"


def test_invariant_5_low_voltage_forces_zero_even_with_soc_limit_skip():
    guard = SoCGuard(Settings())
    state = ExecutorState(0, battery_soc=50, battery_voltage=45.9)
    assert guard.apply(-500, state, 20.0, 90.0, skip_soc_limits=True) == 0


def test_invariant_6_discharge_blocked_at_dynamic_floor_released_only_past_hysteresis():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    floor_dyn = 35.0
    guard.apply(-500, ExecutorState(0, battery_soc=floor_dyn), floor_dyn, 90.0)  # engage block
    # Still inside the 2% band above the dynamic floor -> stays blocked
    assert guard.apply(-500, ExecutorState(0, battery_soc=floor_dyn + 1), floor_dyn, 90.0) == 0
    # Past floor_dyn + hysteresis -> released
    assert guard.apply(-500, ExecutorState(0, battery_soc=floor_dyn + 2.1), floor_dyn, 90.0) == -500


def test_charge_stays_blocked_within_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(500, ExecutorState(0, battery_soc=90), 20.0, 90.0)
    assert guard.apply(500, ExecutorState(0, battery_soc=89), 20.0, 90.0) == 0


def test_charge_releases_below_hysteresis_band():
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    guard.apply(500, ExecutorState(0, battery_soc=90), 20.0, 90.0)
    assert guard.apply(500, ExecutorState(0, battery_soc=87.9), 20.0, 90.0) == 500


def test_dynamic_limits_follow_replan_immediately_no_upward_ratchet():
    """Invariant 15 as seen from the guard: it has no memory of the previous floor/ceiling."""
    guard = SoCGuard(Settings(initial={"strategy.soc_hysteresis_pct": "2"}))
    # Engage a block against a high floor from a stale plan.
    guard.apply(-500, ExecutorState(0, battery_soc=60), 60.0, 90.0)
    # A fresh replan re-anchors to a much lower floor -- the guard must respect it immediately.
    assert guard.apply(-500, ExecutorState(0, battery_soc=60), 25.0, 90.0) == -500
