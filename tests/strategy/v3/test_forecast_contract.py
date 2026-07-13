import math
from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.forecast_contract import build_minyad_forecast, validate_forecast_arrays

UTC = timezone.utc
ALIGNED_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=UTC)


def _valid_candidate(**overrides):
    base = dict(
        starts_at=ALIGNED_NOW,
        slot_duration_s=900,
        surplus_p50_w=[100.0] * 96,
        surplus_p25_w=[80.0] * 96,
        pv_p25_w=[900.0] * 96,
        soc_pct=[68.0] * 96,
    )
    base.update(overrides)
    return base


def test_validate_forecast_arrays_accepts_a_valid_candidate():
    assert validate_forecast_arrays(**_valid_candidate()) is None


def test_validate_forecast_arrays_rejects_naive_start():
    assert validate_forecast_arrays(**_valid_candidate(starts_at=datetime(2026, 7, 14, 10, 0, 0))) == "start_not_utc"


def test_validate_forecast_arrays_rejects_unaligned_start():
    unaligned = ALIGNED_NOW + timedelta(minutes=7)
    assert validate_forecast_arrays(**_valid_candidate(starts_at=unaligned)) == "unaligned_start"


def test_validate_forecast_arrays_rejects_length_mismatch():
    short = _valid_candidate(surplus_p50_w=[100.0] * 50)
    assert validate_forecast_arrays(**short) == "array_length_mismatch"


def test_validate_forecast_arrays_rejects_non_finite_values():
    bad = _valid_candidate(surplus_p50_w=[100.0] * 95 + [math.inf])
    assert validate_forecast_arrays(**bad) == "non_finite_values"

    bad_nan = _valid_candidate(pv_p25_w=[math.nan] + [900.0] * 95)
    assert validate_forecast_arrays(**bad_nan) == "non_finite_values"


def test_validate_forecast_arrays_rejects_soc_out_of_bounds():
    bad = _valid_candidate(soc_pct=[68.0] * 95 + [105.0])
    assert validate_forecast_arrays(**bad) == "soc_out_of_bounds"

    bad_negative = _valid_candidate(soc_pct=[-1.0] + [68.0] * 95)
    assert validate_forecast_arrays(**bad_negative) == "soc_out_of_bounds"


def test_validate_forecast_arrays_rejects_p25_exceeding_p50():
    bad = _valid_candidate(surplus_p25_w=[150.0] * 96, surplus_p50_w=[100.0] * 96)
    assert validate_forecast_arrays(**bad) == "p25_exceeds_p50"


def _plan_payload(now, *, slot_count=96, solar_w=1500.0, load_w=400.0, charge_w=300.0, soc_start=68.0):
    slots = []
    for i in range(slot_count):
        slots.append({
            "start": (now + timedelta(seconds=900 * i)).isoformat(),
            "soc_target_pct": min(90.0, soc_start + i * 0.02),
            "planned_grid_charge_w": 0,
            "planned_export_w": 0,
            "pv_forecast_w": solar_w,
            "load_forecast_w": load_w,
            "charge_w": charge_w,
            "discharge_w": 0,
            "curtailment_w": 0,
            "price_source": "fallback",
            "cloud_cover_pct": 10.0,
            "surplus_w": max(0.0, solar_w - load_w - charge_w),
            "price_import": 0.25,
            "price_export": 0.0,
        })
    return {
        "generated_at": now.isoformat(),
        "valid_from": now.isoformat(),
        "slot_seconds": 900,
        "soc_start_pct": soc_start,
        "slots": slots,
        "friday_full_cycle": False,
        "solver_status": "Optimal",
        "pv_calibration_factor": 7.0,
        "plan_schema": 2,
    }


def _bands():
    grid = [[1, 0.5], [5, 0.6], [10, 0.7], [25, 0.85], [50, 1.0], [75, 1.1], [90, 1.2], [95, 1.25], [99, 1.3]]
    return {"clear": {"quantile_grid": grid}}


def test_build_minyad_forecast_returns_96_slots_with_utc_aligned_timestamps():
    plan_payload = _plan_payload(ALIGNED_NOW)
    outcome = build_minyad_forecast(
        plan_payload=plan_payload,
        plan_generated_at=ALIGNED_NOW,
        plan_solver_status="Optimal",
        uncertainty_bands=_bands(),
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
        seed=11,
    )
    assert outcome.validation_status == "valid"
    forecast = outcome.forecast
    assert forecast["quality"] == "authoritative_lp"
    assert forecast["slot_count"] == 96
    assert len(forecast["surplus_p50_w"]) == 96
    assert len(forecast["surplus_p25_w"]) == 96
    assert len(forecast["pv_p25_w"]) == 96
    assert forecast["starts_at"] == ALIGNED_NOW.isoformat()
    assert forecast["starts_at"].endswith("+00:00")
    assert forecast["generated_at"].endswith("+00:00")
    assert all(p25 <= p50 for p25, p50 in zip(forecast["surplus_p25_w"], forecast["surplus_p50_w"]))

    assert len(outcome.soc_trajectory_pct) == 96
    assert all(0.0 <= v <= 100.0 for v in outcome.soc_trajectory_pct)


def test_build_minyad_forecast_missing_plan_is_unavailable_not_fabricated():
    outcome = build_minyad_forecast(
        plan_payload=None,
        plan_generated_at=None,
        plan_solver_status=None,
        uncertainty_bands=None,
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
    )
    assert outcome.validation_status == "invalid"
    assert outcome.validation_reason == "missing_plan"
    assert outcome.soc_trajectory_pct is None
    assert outcome.forecast["quality"] == "unavailable"
    assert "surplus_p50_w" not in outcome.forecast


def test_build_minyad_forecast_stale_plan_is_rejected():
    old = ALIGNED_NOW - timedelta(hours=2)
    plan_payload = _plan_payload(old)
    outcome = build_minyad_forecast(
        plan_payload=plan_payload,
        plan_generated_at=old,
        plan_solver_status="Optimal",
        uncertainty_bands=_bands(),
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
    )
    assert outcome.validation_status == "invalid"
    assert outcome.validation_reason == "stale_plan"
    assert outcome.soc_trajectory_pct is None


def test_build_minyad_forecast_solver_fallback_is_rejected_not_fabricated():
    """A FALLBACK/timed-out solver run must never be presented as a real forecast."""
    plan_payload = _plan_payload(ALIGNED_NOW)
    outcome = build_minyad_forecast(
        plan_payload=plan_payload,
        plan_generated_at=ALIGNED_NOW,
        plan_solver_status="FALLBACK",
        uncertainty_bands=_bands(),
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
    )
    assert outcome.validation_status == "invalid"
    assert outcome.validation_reason == "solver_fallback"
    assert outcome.soc_trajectory_pct is None


def test_build_minyad_forecast_rejects_wrong_slot_count():
    plan_payload = _plan_payload(ALIGNED_NOW, slot_count=50)
    outcome = build_minyad_forecast(
        plan_payload=plan_payload,
        plan_generated_at=ALIGNED_NOW,
        plan_solver_status="Optimal",
        uncertainty_bands=_bands(),
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
    )
    assert outcome.validation_status == "invalid"
    assert outcome.validation_reason == "unexpected_slot_count"
    assert outcome.soc_trajectory_pct is None


def test_build_minyad_forecast_never_contains_reservation_or_device_keys():
    """Minyad does not do appliance switching; nothing device/reservation-shaped may leak in."""
    plan_payload = _plan_payload(ALIGNED_NOW)
    outcome = build_minyad_forecast(
        plan_payload=plan_payload,
        plan_generated_at=ALIGNED_NOW,
        plan_solver_status="Optimal",
        uncertainty_bands=_bands(),
        now=ALIGNED_NOW,
        stale_minutes=30,
        scenario_count=64,
        seed=5,
    )
    forbidden = {"reservation", "reservation_id", "device_id", "job_id", "appliance", "vesper", "acknowledgement_status"}
    assert forbidden.isdisjoint(outcome.forecast.keys())
