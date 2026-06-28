import asyncio
from datetime import datetime, timedelta, timezone

from minyad.strategy.v2 import DayPlan, ExecutorState, OverrideManager, Settings


def plan():
    return DayPlan(datetime(2026, 6, 27, tzinfo=timezone.utc).date(), "NORMAL", 2.0, 20, 90)


def test_force_idle_suppresses_all_setpoints():
    manager = OverrideManager(Settings())
    asyncio.run(manager.apply_payload({"mode": "force_idle"}))
    result = asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), plan()))
    assert result == 0
    adjusted, reason = asyncio.run(manager.apply_with_reason(700, ExecutorState(0, battery_soc=50), plan()))
    assert adjusted == 0
    assert reason == "override: force_idle"


def test_pause_auto_expires():
    current = {"now": datetime(2026, 6, 27, 12, tzinfo=timezone.utc)}
    manager = OverrideManager(Settings(), now=lambda: current["now"])
    asyncio.run(manager.apply_payload({"mode": "pause", "duration_seconds": 10}))
    assert asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), plan())) == 0
    current["now"] += timedelta(seconds=11)
    assert asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), plan())) == 700


def test_force_charge_overrides_discharge_decision():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 700}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), plan()))
    assert result == 700
    adjusted, reason = asyncio.run(manager.apply_with_reason(-500, ExecutorState(0, battery_soc=50), plan()))
    assert adjusted == 700
    assert reason == "override: force_charge"


def test_force_charge_clamps_requested_watts_to_effective_limit():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 2000}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), plan()))
    assert result == 1440


def test_legacy_force_on_alias_charges_under_v2():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_on", "watts": 700}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), plan()))
    assert result == 700


def test_legacy_force_off_alias_idles_under_v2():
    manager = OverrideManager(Settings())
    asyncio.run(manager.apply_payload({"mode": "force_off"}))
    result = asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), plan()))
    assert result == 0
