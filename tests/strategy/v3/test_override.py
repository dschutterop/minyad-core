import asyncio
from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.constants import Settings
from minyad.strategy.v3.models import ExecutorState
from minyad.strategy.v3.override import OverrideManager

FLOOR = 20.0
CEIL = 90.0


def test_force_idle_suppresses_all_setpoints():
    manager = OverrideManager(Settings())
    asyncio.run(manager.apply_payload({"mode": "force_idle"}))
    result = asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert result == 0
    adjusted, reason = asyncio.run(manager.apply_with_reason(700, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert adjusted == 0
    assert reason == "override: force_idle"


def test_pause_auto_expires():
    current = {"now": datetime(2026, 6, 27, 12, tzinfo=timezone.utc)}
    manager = OverrideManager(Settings(), now=lambda: current["now"])
    asyncio.run(manager.apply_payload({"mode": "pause", "duration_seconds": 10}))
    assert asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), FLOOR, CEIL)) == 0
    current["now"] += timedelta(seconds=11)
    assert asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), FLOOR, CEIL)) == 700


def test_force_charge_overrides_discharge_decision():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 700}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert result == 700
    adjusted, reason = asyncio.run(manager.apply_with_reason(-500, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert adjusted == 700
    assert reason == "override: force_charge"


def test_force_charge_blocked_at_dynamic_ceiling():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 700}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=95), FLOOR, CEIL))
    assert result == 0


def test_force_charge_clamps_requested_watts_to_effective_limit():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 2000}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert result == 1440


def test_force_charge_can_override_soc_ceiling_for_one_cycle():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440", "strategy.jitter_w": "30"}))
    asyncio.run(manager.apply_payload({"mode": "force_charge", "watts": 700, "override_soc_limits": True}))

    adjusted, reason = asyncio.run(manager.apply_with_reason(0, ExecutorState(0, battery_soc=95, battery_power_w=-600), FLOOR, CEIL))
    assert adjusted == 700
    assert reason == "override: force_charge (SoC limit override active)"
    assert manager.bypasses_soc_limits()

    adjusted, reason = asyncio.run(manager.apply_with_reason(0, ExecutorState(0, battery_soc=95, battery_power_w=0), FLOOR, CEIL))
    assert adjusted == 0
    assert reason == "override: expired after one charge/discharge cycle"
    assert not manager.bypasses_soc_limits()


def test_force_discharge_can_override_soc_floor_for_one_cycle():
    manager = OverrideManager(Settings(initial={"battery.max_discharge_w": "1500", "strategy.jitter_w": "30"}))
    asyncio.run(manager.apply_payload({"mode": "force_discharge", "watts": 900, "override_soc_limits": True}))

    adjusted, reason = asyncio.run(manager.apply_with_reason(0, ExecutorState(0, battery_soc=15, battery_power_w=700), FLOOR, CEIL))
    assert adjusted == -900
    assert reason == "override: force_discharge (SoC limit override active)"

    adjusted, reason = asyncio.run(manager.apply_with_reason(0, ExecutorState(0, battery_soc=15, battery_power_w=-100), FLOOR, CEIL))
    assert adjusted == 0
    assert reason == "override: expired after one charge/discharge cycle"


def test_legacy_force_on_alias_charges_under_v3():
    manager = OverrideManager(Settings(initial={"battery.max_charge_w": "1440"}))
    asyncio.run(manager.apply_payload({"mode": "force_on", "watts": 700}))
    result = asyncio.run(manager.apply(-500, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert result == 700


def test_legacy_force_off_alias_idles_under_v3():
    manager = OverrideManager(Settings())
    asyncio.run(manager.apply_payload({"mode": "force_off"}))
    result = asyncio.run(manager.apply(700, ExecutorState(0, battery_soc=50), FLOOR, CEIL))
    assert result == 0
