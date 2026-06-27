from datetime import datetime, timedelta, timezone

from minyad.strategy.v2 import DayPlan, ExecutorState, Settings, SoCGuard


def plan():
    return DayPlan(datetime(2026, 6, 27, tzinfo=timezone.utc).date(), "NORMAL", 2.0, 20, 90)


def test_discharge_blocked_at_floor():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=20), plan()) == 0


def test_charge_blocked_at_ceiling():
    guard = SoCGuard(Settings())
    assert guard.apply(500, ExecutorState(0, battery_soc=90), plan()) == 0


def test_bridge_stale_suppresses_setpoint():
    guard = SoCGuard(Settings())
    now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)
    state = ExecutorState(0, battery_soc=50, bridge_last_seen=now - timedelta(seconds=61))
    assert guard.apply(500, state, plan(), now) == 0


def test_voltage_guard_suppresses_setpoint():
    guard = SoCGuard(Settings())
    assert guard.apply(-500, ExecutorState(0, battery_soc=50, battery_voltage=45.9), plan()) == 0
