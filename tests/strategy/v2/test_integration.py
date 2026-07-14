from datetime import UTC, datetime

from minyad.strategy.v2 import (
    DayPlan,
    ExecutorState,
    Settings,
    SoCGuard,
    StrategyExecutor,
)


def test_morning_solar_ramp_charges_then_stops_at_ceiling():
    now = datetime(2026, 6, 27, 9, tzinfo=UTC)
    settings = Settings(initial={"strategy.ramp_hold_seconds": "0", "strategy.ramp_floor_w": "100"})
    plan = DayPlan(now.date(), "SOLAR_RICH", 5.0, 10, 90)
    executor = StrategyExecutor(settings, plan, now=lambda: now)
    guard = SoCGuard(settings)
    trajectory = []
    soc = 50
    for tick in range(60):
        export = -min(1200, tick * 30)
        if tick == 55:
            soc = 90
        decision = executor.tick(ExecutorState(export, battery_soc=soc, current_setpoint_w=executor.current_setpoint_w))
        guarded = guard.apply(decision.setpoint_w, ExecutorState(export, battery_soc=soc), plan, now)
        trajectory.append(guarded)
        executor.current_setpoint_w = guarded
    assert max(trajectory[:55]) > 0
    assert trajectory[-1] == 0
