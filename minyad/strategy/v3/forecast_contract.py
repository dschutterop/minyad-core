"""Builds the Vesper-facing ``minyad_forecast`` block from Minyad's own LP plan, or explains
precisely why it can't — never a partial, stale, or fabricated one.

Minyad owns the authoritative household energy forecast, battery dispatch/SoC trajectory, and
the P50/P25 uncertainty model. This module is the single place that decides whether a given
``SlotPlan`` (persisted by ``planner.RollingPlanner``) is fit to publish as that contract; the
structural rules mirror the ``minyad_forecast`` shape documented in
``docs/minyad_forecast_contract.md``.

Vesper is expected to subtract its own current-tick reservations from ``surplus_p50_w`` /
``surplus_p25_w`` separately — this module has no knowledge of Vesper reservations or devices
and must never gain any (Minyad does not do appliance switching).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .scenario_forecast import ScenarioForecastFailure, ScenarioSlotInput, generate_scenario_forecast

FORECAST_SLOT_COUNT = 96
FORECAST_SLOT_SECONDS = 900
FORECAST_SOURCE = "minyad_lp"
DEFAULT_MODEL_VERSION = "strategy-v3-lp"


@dataclass(frozen=True)
class ForecastBuildOutcome:
    forecast: dict[str, Any] | None
    soc_trajectory_pct: list[float] | None
    validation_status: str
    validation_reason: str | None


def _round_list(values: list[float], ndigits: int) -> list[float]:
    return [round(v, ndigits) for v in values]


def validate_forecast_arrays(
    *,
    starts_at: datetime,
    slot_duration_s: int,
    surplus_p50_w: list[float],
    surplus_p25_w: list[float],
    pv_p25_w: list[float],
    soc_pct: list[float],
    expected_slot_count: int = FORECAST_SLOT_COUNT,
    expected_slot_seconds: int = FORECAST_SLOT_SECONDS,
) -> str | None:
    """Structural/numeric validation shared by real plans and hand-built test candidates.

    Returns a failure-reason string, or ``None`` if the candidate is valid.
    """
    if starts_at.tzinfo is None or starts_at.utcoffset() != timedelta(0):
        return "start_not_utc"
    if starts_at.minute % 15 != 0 or starts_at.second != 0 or starts_at.microsecond != 0:
        return "unaligned_start"
    if slot_duration_s != expected_slot_seconds:
        return "unexpected_slot_duration"

    arrays = {
        "surplus_p50_w": surplus_p50_w,
        "surplus_p25_w": surplus_p25_w,
        "pv_p25_w": pv_p25_w,
        "soc_pct": soc_pct,
    }
    if any(len(values) != expected_slot_count for values in arrays.values()):
        return "array_length_mismatch"
    for values in arrays.values():
        if any(not math.isfinite(v) for v in values):
            return "non_finite_values"
    if any(v < 0.0 or v > 100.0 for v in soc_pct):
        return "soc_out_of_bounds"
    if any(v < 0.0 for v in surplus_p50_w) or any(v < 0.0 for v in surplus_p25_w) or any(v < 0.0 for v in pv_p25_w):
        return "negative_power"
    if any(p25 > p50 + 1e-6 for p25, p50 in zip(surplus_p25_w, surplus_p50_w)):
        return "p25_exceeds_p50"
    return None


def build_minyad_forecast(
    *,
    plan_payload: dict[str, Any] | None,
    plan_generated_at: datetime | None,
    plan_solver_status: str | None,
    uncertainty_bands: dict[str, dict[str, Any]] | None,
    now: datetime,
    stale_minutes: int,
    scenario_count: int,
    model_version: str = DEFAULT_MODEL_VERSION,
    seed: int | None = None,
) -> ForecastBuildOutcome:
    """Validate the current LP plan and, if it's fit for purpose, build the scenario-derived
    ``minyad_forecast`` block plus the aligned SoC trajectory.

    On any failure, ``forecast`` carries a ``"quality": "unavailable"`` marker with an explicit
    ``validation.reason`` and ``soc_trajectory_pct`` is ``None`` — callers must not substitute a
    copied current SoC or a synthetic trajectory for it.
    """
    age_s: float | None = None
    reason: str | None = None

    if plan_payload is None or plan_generated_at is None:
        reason = "missing_plan"
    else:
        generated_at = plan_generated_at if plan_generated_at.tzinfo else plan_generated_at.replace(tzinfo=timezone.utc)
        age_s = (now - generated_at).total_seconds()
        if age_s > stale_minutes * 60:
            reason = "stale_plan"
        elif plan_solver_status != "Optimal":
            reason = "solver_fallback"

    slots: list[dict[str, Any]] = []
    if reason is None:
        slots = plan_payload.get("slots") or []
        if len(slots) != FORECAST_SLOT_COUNT:
            reason = "unexpected_slot_count"
        elif int(plan_payload.get("slot_seconds", 0)) != FORECAST_SLOT_SECONDS:
            reason = "unexpected_slot_duration"

    starts_at: datetime | None = None
    if reason is None:
        try:
            starts_at = datetime.fromisoformat(str(slots[0]["start"]))
        except (KeyError, ValueError, IndexError):
            reason = "invalid_slot_data"
        else:
            starts_at = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
            starts_at = starts_at.astimezone(timezone.utc)

    soc_trajectory_pct: list[float] | None = None
    if reason is None:
        try:
            soc_start_pct = float(plan_payload.get("soc_start_pct"))
            soc_trajectory_pct = [soc_start_pct] + [float(slot["soc_target_pct"]) for slot in slots[:-1]]
        except (TypeError, ValueError, KeyError):
            reason = "invalid_slot_data"

    outcome_forecast: dict[str, Any] | None = None
    if reason is None:
        scenario_slots = [
            ScenarioSlotInput(
                start=datetime.fromisoformat(str(slot["start"])),
                pv_forecast_w=float(slot.get("pv_forecast_w") or 0.0),
                load_forecast_w=float(slot.get("load_forecast_w") or 0.0),
                charge_w=float(slot.get("charge_w") or 0.0),
                cloud_cover_pct=slot.get("cloud_cover_pct"),
            )
            for slot in slots
        ]
        result = generate_scenario_forecast(scenario_slots, uncertainty_bands or {}, scenario_count=scenario_count, seed=seed)
        if isinstance(result, ScenarioForecastFailure):
            reason = result.reason
        else:
            structural_reason = validate_forecast_arrays(
                starts_at=starts_at,
                slot_duration_s=FORECAST_SLOT_SECONDS,
                surplus_p50_w=result.surplus_p50_w,
                surplus_p25_w=result.surplus_p25_w,
                pv_p25_w=result.pv_p25_w,
                soc_pct=soc_trajectory_pct,
            )
            if structural_reason is not None:
                reason = structural_reason
            else:
                outcome_forecast = {
                    "source": FORECAST_SOURCE,
                    "quality": "authoritative_lp",
                    "generated_at": plan_generated_at.astimezone(timezone.utc).isoformat(),
                    "starts_at": starts_at.isoformat(),
                    "slot_duration_s": FORECAST_SLOT_SECONDS,
                    "slot_count": FORECAST_SLOT_COUNT,
                    "surplus_p50_w": [round(v) for v in result.surplus_p50_w],
                    "surplus_p25_w": [round(v) for v in result.surplus_p25_w],
                    "pv_p25_w": [round(v) for v in result.pv_p25_w],
                    "soc_pct": _round_list(soc_trajectory_pct, 2),
                    "scenario_count": scenario_count,
                    "model_version": model_version,
                    "validation": {
                        "status": "valid",
                        "reason": None,
                        "age_s": round(age_s, 1) if age_s is not None else None,
                        "scenario_count": scenario_count,
                    },
                }

    if reason is not None:
        return ForecastBuildOutcome(
            forecast={
                "source": FORECAST_SOURCE,
                "quality": "unavailable",
                "validation": {
                    "status": "invalid",
                    "reason": reason,
                    "age_s": round(age_s, 1) if age_s is not None else None,
                    "scenario_count": None,
                },
            },
            soc_trajectory_pct=None,
            validation_status="invalid",
            validation_reason=reason,
        )

    return ForecastBuildOutcome(
        forecast=outcome_forecast,
        soc_trajectory_pct=soc_trajectory_pct,
        validation_status="valid",
        validation_reason=None,
    )
