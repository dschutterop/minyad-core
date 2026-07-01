from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.constants import Settings
from minyad.strategy.v3.executor import StrategyExecutor
from minyad.strategy.v3.models import ExecutorState, Slot, SlotPlan, TrackerResult


class Clock:
    def __init__(self):
        self.t = 0.0
        self.now = datetime(2026, 6, 27, 12, tzinfo=timezone.utc)

    def monotonic(self):
        return self.t

    def datetime(self):
        return self.now


def make_executor(settings=None):
    clock = Clock()
    s = Settings(initial={"strategy.ramp_hold_seconds": "90", **(settings or {})})
    return StrategyExecutor(s, clock=clock.monotonic, now=clock.datetime), clock


def make_plan(now, *, planned_grid_charge_w=0, planned_export_w=0, friday=False, solver_status="Optimal"):
    slot = Slot(
        start=now - timedelta(hours=1),
        soc_target_pct=50.0,
        planned_grid_charge_w=planned_grid_charge_w,
        planned_export_w=planned_export_w,
        pv_forecast_w=0,
        load_forecast_w=300,
        price_import=0.25,
        price_export=0.0,
    )
    return SlotPlan(
        generated_at=now - timedelta(hours=1),
        valid_from=now - timedelta(hours=1),
        slot_seconds=7200,
        soc_start_pct=50.0,
        slots=[slot],
        friday_full_cycle=friday,
        solver_status=solver_status,
        pv_calibration_factor=7.0,
    )


def tracker(bias_w=0, floor_dyn_pct=20.0, ceil_dyn_pct=90.0):
    return TrackerResult(bias_w=bias_w, floor_dyn_pct=floor_dyn_pct, ceil_dyn_pct=ceil_dyn_pct)


def test_steady_export_charges_after_hold():
    executor, clock = make_executor()
    plan = make_plan(clock.now)
    assert executor.tick(ExecutorState(-600, battery_soc=50), plan, tracker()).setpoint_w == 0
    clock.t = 91
    decision = executor.tick(ExecutorState(-600, battery_soc=50), plan, tracker())
    assert decision.setpoint_w > 0


def test_steady_import_discharges_after_hold():
    executor, clock = make_executor()
    plan = make_plan(clock.now)
    assert executor.tick(ExecutorState(600, battery_soc=50), plan, tracker()).setpoint_w == 0
    clock.t = 91
    decision = executor.tick(ExecutorState(600, battery_soc=50), plan, tracker())
    assert decision.setpoint_w < 0


def test_invariant_7_active_discharge_trims_during_export():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    plan = make_plan(clock.now)
    executor.current_setpoint_w = -500
    decision = executor.tick(ExecutorState(-200, battery_soc=50, current_setpoint_w=-500), plan, tracker())
    assert decision.setpoint_w == -380
    assert "trimming discharge during export" in decision.reason


def test_invariant_7_export_trim_waits_for_fresh_telemetry_dedup_guard():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    plan = make_plan(clock.now)
    first = executor.tick(ExecutorState(-381, battery_soc=50, battery_power_w=1524, current_setpoint_w=-1438), plan, tracker())
    assert first.setpoint_w == -1210

    duplicate = executor.tick(ExecutorState(-381, battery_soc=50, battery_power_w=1524, current_setpoint_w=-1210), plan, tracker())
    assert duplicate.setpoint_w == -1210
    assert "waiting for fresh export telemetry" in duplicate.reason


def test_export_trim_does_not_cross_into_charge():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    plan = make_plan(clock.now)
    decision = executor.tick(ExecutorState(-381, battery_soc=50, battery_power_w=1524, current_setpoint_w=-70), plan, tracker())
    assert decision.setpoint_w == 0
    assert "trimming discharge during export" in decision.reason


def test_jitter_suppression_keeps_current_setpoint():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.jitter_w": "50"})
    plan = make_plan(clock.now)
    decision = executor.tick(ExecutorState(-30, battery_soc=50, current_setpoint_w=300), plan, tracker())
    assert decision.setpoint_w == 300
    assert "jitter suppressed" in decision.reason


def test_trajectory_bias_is_applied():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    plan = make_plan(clock.now)
    decision = executor.tick(ExecutorState(600, battery_soc=50), plan, tracker(bias_w=-200))
    # error=600, delta=clamp(600*0.6,...)=360, candidate=0-360-200=-560
    assert decision.setpoint_w == -560
    assert decision.bias_w == -200


def test_planned_grid_charge_sizes_to_plan_not_hardware_max():
    now = datetime(2026, 6, 27, 2, tzinfo=timezone.utc)
    executor, clock = make_executor({"battery.max_charge_w": "1440"})
    clock.now = now
    plan = make_plan(now, planned_grid_charge_w=500)
    # pv_now_w=0, net_grid_w=700 (importing), battery_power_w=0 -> load_now_w_estimate=700
    decision = executor.tick(ExecutorState(700, battery_soc=50, pv_now_w=0), plan, tracker())
    assert decision.setpoint_w == 500  # planned_grid_charge_w + max(0, pv-load) = 500 + 0


def test_planned_grid_charge_adds_pv_surplus_over_estimated_load():
    now = datetime(2026, 6, 27, 10, tzinfo=timezone.utc)
    executor, clock = make_executor({"battery.max_charge_w": "1440"})
    clock.now = now
    plan = make_plan(now, planned_grid_charge_w=300)
    # net_grid_w=0, battery_power_w=0, pv_now_w=1000 -> load_now_w_estimate=max(0,0+0+1000)=1000
    # surplus over estimate = max(0, 1000-1000)=0 -> candidate=300
    decision = executor.tick(ExecutorState(0, battery_soc=50, pv_now_w=1000), plan, tracker())
    assert decision.setpoint_w == 300


def test_no_soc_clamp_inside_executor():
    # The executor itself must never block on SoC -- that's the guard's job now.
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0"})
    plan = make_plan(clock.now)
    decision = executor.tick(ExecutorState(600, battery_soc=1.0), plan, tracker())
    assert decision.setpoint_w < 0  # would discharge despite soc=1% -- guard's job to block this


def test_ramp_hold_resets_after_each_fire():
    executor, clock = make_executor()
    plan = make_plan(clock.now)
    executor.tick(ExecutorState(600, battery_soc=50), plan, tracker())
    clock.t = 91
    executor.tick(ExecutorState(600, battery_soc=50), plan, tracker())
    clock.t = 92
    decision = executor.tick(ExecutorState(600, battery_soc=50), plan, tracker())
    assert decision.setpoint_w == executor.current_setpoint_w


def test_export_block_hysteresis_stays_blocked_within_band():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.export_block_threshold_w": "100", "strategy.export_block_hysteresis_w": "50"})
    plan = make_plan(clock.now)
    executor.current_setpoint_w = -400
    executor.tick(ExecutorState(-150, battery_soc=50, current_setpoint_w=-400), plan, tracker())
    decision = executor.tick(ExecutorState(-80, battery_soc=50, current_setpoint_w=-310), plan, tracker())
    assert decision.setpoint_w <= 0
    assert "trimming discharge during export" in decision.reason


def test_export_block_hysteresis_releases_past_clearance():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.export_block_threshold_w": "100", "strategy.export_block_hysteresis_w": "50"})
    plan = make_plan(clock.now)
    executor.current_setpoint_w = -400
    executor.tick(ExecutorState(-150, battery_soc=50, current_setpoint_w=-400), plan, tracker())
    decision = executor.tick(ExecutorState(200, battery_soc=50, current_setpoint_w=0), plan, tracker())
    assert decision.setpoint_w < 0


def test_export_block_threshold_widens_with_planned_export():
    executor, clock = make_executor({"strategy.ramp_hold_seconds": "0", "strategy.export_block_threshold_w": "100"})
    plan = make_plan(clock.now, planned_export_w=200)
    executor.current_setpoint_w = -400
    # export of -250W would normally trip the 100W threshold, but plan allows 200W more room (300W)
    decision = executor.tick(ExecutorState(-250, battery_soc=50, current_setpoint_w=-400), plan, tracker())
    assert not executor._export_blocked


def test_grid_charge_ceiling_hysteresis_stops_at_dynamic_ceiling():
    now = datetime(2026, 6, 27, 2, tzinfo=timezone.utc)
    executor, clock = make_executor({"battery.max_charge_w": "1440", "strategy.soc_hysteresis_pct": "2"})
    clock.now = now
    plan = make_plan(now, planned_grid_charge_w=500)
    executor.tick(ExecutorState(0, battery_soc=90, pv_now_w=0), plan, tracker(ceil_dyn_pct=90))  # ceiling reached
    decision = executor.tick(ExecutorState(0, battery_soc=89.5, pv_now_w=0), plan, tracker(ceil_dyn_pct=90))
    assert decision.setpoint_w != 500
