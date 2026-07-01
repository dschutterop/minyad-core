from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from minyad.strategy.v3.constants import Settings
from minyad.strategy.v3.models import Slot, SlotPlan
from minyad.strategy.v3.tracker import TrajectoryTracker

TZ = ZoneInfo("Europe/Amsterdam")


def _plan(now, soc_start_pct, soc_target_pct, *, friday=False, solver_status="Optimal"):
    slots = [
        Slot(
            start=now + timedelta(minutes=15 * i),
            soc_target_pct=soc_target_pct,
            planned_grid_charge_w=0,
            planned_export_w=0,
            pv_forecast_w=0,
            load_forecast_w=300,
            price_import=0.25,
            price_export=0.0,
        )
        for i in range(96)
    ]
    return SlotPlan(
        generated_at=now,
        valid_from=now,
        slot_seconds=900,
        soc_start_pct=soc_start_pct,
        slots=slots,
        friday_full_cycle=friday,
        solver_status=solver_status,
        pv_calibration_factor=7.0,
    )


def test_invariant_8_bias_clamped_to_max():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    settings = Settings(initial={"battery.capacity_wh": "10240", "strategy3.traj_tau_hours": "2.0", "strategy3.traj_bias_max_w": "400"})
    plan = _plan(now, 50.0, 50.0)  # flat plan at 50% so soc_plan_pct(now) == 50
    tracker = TrajectoryTracker(settings)
    result = tracker.evaluate(now, soc_actual_pct=60.0, plan=plan)
    assert result.bias_w == -400


def test_invariant_9_deadband_zeroes_small_error():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    settings = Settings(initial={"strategy3.traj_deadband_pct": "3"})
    plan = _plan(now, 50.0, 50.0)
    tracker = TrajectoryTracker(settings)
    result = tracker.evaluate(now, soc_actual_pct=52.5, plan=plan)
    assert result.bias_w == 0


def test_invariant_10_fallback_plan_uses_static_limits():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    settings = Settings(initial={"battery.soc_floor": "20", "battery.soc_ceiling": "90"})
    plan = _plan(now, 50.0, 50.0, solver_status="FALLBACK")
    tracker = TrajectoryTracker(settings)
    result = tracker.evaluate(now, soc_actual_pct=50.0, plan=plan)
    assert result.bias_w == 0
    assert result.floor_dyn_pct == 20.0
    assert result.ceil_dyn_pct == 90.0


def test_invariant_10_fallback_plan_is_friday_aware_ceiling():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=TZ)
    settings = Settings(initial={"battery.soc_ceiling": "90"})
    plan = _plan(now, 50.0, 50.0, friday=True, solver_status="FALLBACK")
    tracker = TrajectoryTracker(settings)
    result = tracker.evaluate(now, soc_actual_pct=50.0, plan=plan)
    assert result.ceil_dyn_pct == 100.0


def test_invariant_15_replan_reanchor_no_upward_ratchet():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    settings = Settings()
    tracker = TrajectoryTracker(settings)

    high_plan = _plan(now, 70.0, 70.0)
    result_before = tracker.evaluate(now, soc_actual_pct=70.0, plan=high_plan)

    # Replan re-anchors soc_now far below the previous trajectory.
    low_plan = _plan(now, 30.0, 30.0)
    result_after = tracker.evaluate(now, soc_actual_pct=30.0, plan=low_plan)

    assert result_after.floor_dyn_pct < result_before.floor_dyn_pct
    assert result_after.ceil_dyn_pct < result_before.ceil_dyn_pct


def test_dynamic_band_respects_static_floor_and_ceiling_bounds():
    now = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    settings = Settings(initial={"battery.soc_floor": "20", "battery.soc_ceiling": "90", "strategy3.traj_band_pct": "8"})
    tracker = TrajectoryTracker(settings)
    plan = _plan(now, 22.0, 22.0)
    result = tracker.evaluate(now, soc_actual_pct=22.0, plan=plan)
    assert result.floor_dyn_pct == 20.0  # max(static floor, 22-8=14) -> 20
    assert result.ceil_dyn_pct == 30.0  # min(90, 22+8)
