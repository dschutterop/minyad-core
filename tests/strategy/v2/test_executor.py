from datetime import datetime, timedelta, timezone

from minyad.strategy.v2 import DayPlan, ExecutorState, Settings, StrategyExecutor


class Clock:
    def __init__(self):
        self.t = 0.0
        self.now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)

    def monotonic(self):
        return self.t

    def datetime(self):
        return self.now


def make_executor(settings=None, plan=None):
    clock = Clock()
    s = Settings(initial={"strategy.ramp_hold_seconds": "90", **(settings or {})})
    p = plan or DayPlan(clock.now.date(), "NORMAL", 2.0, 20, 90)
    return StrategyExecutor(s, p, clock=clock.monotonic, now=clock.datetime), clock


def test_steady_export_charges_after_hold():
    executor, clock = make_executor()
    assert executor.tick(ExecutorState(-600, battery_soc=50)).setpoint_w == 0
    clock.t = 91
    decision = executor.tick(ExecutorState(-600, battery_soc=50))
    assert decision.setpoint_w > 0


def test_steady_import_discharges_after_hold():
    executor, clock = make_executor()
    assert executor.tick(ExecutorState(600, battery_soc=50)).setpoint_w == 0
    clock.t = 91
    decision = executor.tick(ExecutorState(600, battery_soc=50))
    assert decision.setpoint_w < 0


def test_discharge_blocked_during_export():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    executor.current_setpoint_w = -500
    decision = executor.tick(ExecutorState(-200, battery_soc=50, current_setpoint_w=-500))
    assert decision.setpoint_w == 0
    assert "discharge blocked" in decision.reason


def test_jitter_suppression_keeps_current_setpoint():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.jitter_w": "50"})
    decision = executor.tick(ExecutorState(-30, battery_soc=50, current_setpoint_w=300))
    assert decision.setpoint_w == 300
    assert "jitter suppressed" in decision.reason


def test_price_discharge_window_adds_bias():
    now = datetime(2026, 6, 27, 18, tzinfo=timezone.utc)
    plan = DayPlan(now.date(), "NORMAL", 2.0, 20, 90, price_discharge_windows=[(now - timedelta(minutes=1), now + timedelta(hours=1))])
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"}, plan)
    clock.now = now
    decision = executor.tick(ExecutorState(600, battery_soc=50))
    assert decision.setpoint_w == -560
    assert decision.in_price_discharge_window is True


def test_grid_charge_window_forces_max_charge():
    now = datetime(2026, 6, 27, 2, tzinfo=timezone.utc)
    plan = DayPlan(now.date(), "NORMAL", 2.0, 20, 90, grid_charge_windows=[(now - timedelta(minutes=1), now + timedelta(hours=1))])
    executor, clock = make_executor({"battery.max_charge_w": "1440"}, plan)
    clock.now = now
    decision = executor.tick(ExecutorState(700, battery_soc=50))
    assert decision.setpoint_w == 1440
    assert decision.in_grid_charge_window is True


def test_ramp_hold_resets_after_each_fire():
    # After the hold fires, the next ramp should require a new hold period.
    executor, clock = make_executor()
    executor.tick(ExecutorState(600, battery_soc=50))
    clock.t = 91
    executor.tick(ExecutorState(600, battery_soc=50))  # fires, resets timer
    clock.t = 92  # only 1s after reset — should NOT fire again
    decision = executor.tick(ExecutorState(600, battery_soc=50))
    assert decision.setpoint_w == executor.current_setpoint_w  # held, no new ramp


def test_soc_floor_hysteresis_keeps_discharge_blocked_above_floor():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.soc_hysteresis_pct": "2"})
    # Touch the floor to engage the block
    executor.tick(ExecutorState(-600, battery_soc=20))
    # SoC recovers to 21% — still inside the 2% band, discharge must stay blocked
    decision = executor.tick(ExecutorState(-600, battery_soc=21))
    assert decision.setpoint_w >= 0


def test_soc_floor_hysteresis_releases_above_band():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.soc_hysteresis_pct": "2"})
    executor.tick(ExecutorState(-600, battery_soc=20))
    # SoC climbs past floor + band (22%) — discharge may resume
    decision = executor.tick(ExecutorState(600, battery_soc=23))
    assert decision.setpoint_w < 0


def test_soc_ceiling_hysteresis_keeps_charge_blocked_below_ceiling():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.soc_hysteresis_pct": "2"})
    executor.tick(ExecutorState(-600, battery_soc=90))
    # SoC dips to 89% — still inside the 2% band, charge must stay blocked
    decision = executor.tick(ExecutorState(-600, battery_soc=89))
    assert decision.setpoint_w <= 0


def test_export_block_hysteresis_stays_blocked_within_band():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.export_block_threshold_w": "100", "strategy.export_block_hysteresis_w": "50"})
    executor.current_setpoint_w = -400
    # Trigger the export block
    executor.tick(ExecutorState(-150, battery_soc=50, current_setpoint_w=-400))
    # Export drops to -80W — within threshold but not past the 50W hysteresis clearance (-50W)
    decision = executor.tick(ExecutorState(-80, battery_soc=50, current_setpoint_w=0))
    assert decision.setpoint_w == 0


def test_export_block_hysteresis_releases_past_clearance():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.export_block_threshold_w": "100", "strategy.export_block_hysteresis_w": "50"})
    executor.current_setpoint_w = -400
    executor.tick(ExecutorState(-150, battery_soc=50, current_setpoint_w=-400))
    # Grid swings to import — export block should clear
    decision = executor.tick(ExecutorState(200, battery_soc=50, current_setpoint_w=0))
    assert decision.setpoint_w < 0


def test_grid_charge_ceiling_hysteresis_stops_at_ceiling():
    now = datetime(2026, 6, 27, 2, tzinfo=timezone.utc)
    plan = DayPlan(now.date(), "NORMAL", 2.0, 20, 90, grid_charge_windows=[(now - timedelta(minutes=1), now + timedelta(hours=1))])
    executor, clock = make_executor({"battery.max_charge_w": "1440", "strategy.soc_hysteresis_pct": "2"}, plan)
    clock.now = now
    executor.tick(ExecutorState(0, battery_soc=90))  # ceiling reached
    # SoC reads 89.5% — inside the 2% band, should NOT resume charging
    decision = executor.tick(ExecutorState(0, battery_soc=89.5))
    assert decision.setpoint_w != 1440
