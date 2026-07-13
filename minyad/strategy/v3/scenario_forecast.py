"""PV scenario generation for the Vesper-facing forecast contract (minyad_forecast).

Draws Monte Carlo PV scenarios from the empirical per-cloud-class ratio distribution built by
``pv_uncertainty.py`` (see ``compute_uncertainty_bands``'s ``quantile_grid``), then derives
``surplus_p50_w`` / ``surplus_p25_w`` / ``pv_p25_w`` as *empirical* percentiles across those
scenarios — never a fixed discount applied to the point forecast.

Scope note: each slot's scenarios are drawn independently from that slot's own cloud-class
marginal distribution (inverse-CDF sampling over the stored quantile grid). This is not a
temporally-correlated weather-path model — it does not simulate "a cloudy day" as a single
coherent scenario across slots. That's sufficient for the per-slot marginal P50/P25 the
minyad_forecast contract asks for, but callers should not treat two scenarios drawn for
different slots as describing the same underlying weather realization.

A cloud class with no persisted quantile grid (too little calibration history — see
``pv_uncertainty.MIN_SAMPLES_PER_CLASS``) cannot back a scenario: the whole forecast is
reported unavailable for that horizon rather than silently falling back to a fabricated
distribution for the affected slots.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .pv_uncertainty import classify_cloud_cover, percentile

DEFAULT_SCENARIO_COUNT = 100


@dataclass(frozen=True)
class ScenarioSlotInput:
    start: datetime
    pv_forecast_w: float
    load_forecast_w: float
    charge_w: float
    cloud_cover_pct: float | None


@dataclass(frozen=True)
class ScenarioForecastResult:
    surplus_p50_w: list[float]
    surplus_p25_w: list[float]
    pv_p25_w: list[float]
    scenario_count: int


@dataclass(frozen=True)
class ScenarioForecastFailure:
    reason: str


def sample_multiplier(quantile_grid: Sequence[Sequence[float]], u: float) -> float:
    """Inverse-CDF sample from a ``[[level_pct, value], ...]`` empirical quantile grid.

    ``u`` is a uniform draw in ``[0, 100)``. Linear interpolation between the two bracketing
    grid points, clamped to the grid's own endpoints outside its range (no tail extrapolation).
    """
    if not quantile_grid:
        raise ValueError("quantile_grid must not be empty")
    grid = sorted(quantile_grid, key=lambda point: point[0])
    if u <= grid[0][0]:
        return float(grid[0][1])
    if u >= grid[-1][0]:
        return float(grid[-1][1])
    for (lo_level, lo_value), (hi_level, hi_value) in zip(grid, grid[1:]):
        if lo_level <= u <= hi_level:
            span = hi_level - lo_level
            if span <= 0:
                return float(lo_value)
            fraction = (u - lo_level) / span
            return float(lo_value + (hi_value - lo_value) * fraction)
    return float(grid[-1][1])


def generate_scenario_forecast(
    slots: Sequence[ScenarioSlotInput],
    bands: dict[str, dict[str, object]],
    *,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    seed: int | None = None,
) -> ScenarioForecastResult | ScenarioForecastFailure:
    """Generate PV scenarios per slot and reduce them to empirical surplus/PV quantiles.

    ``surplus_w[t]`` per scenario is ``max(0, pv_scenario_w[t] - load_forecast_w[t] - charge_w[t])``
    — the same formula the deterministic point forecast uses (``Slot.surplus_w``), with the
    LP's own planned ``charge_w[t]`` held fixed across scenarios (Minyad's planned battery
    dispatch is not re-optimized per scenario). ``pv_p25_w[t]`` is the 25th percentile of the
    PV scenario distribution alone, independent of load or battery.
    """
    if scenario_count < 1:
        return ScenarioForecastFailure("invalid_scenario_count")
    if not slots:
        return ScenarioForecastFailure("empty_horizon")

    grids: list[Sequence[Sequence[float]]] = []
    for slot in slots:
        if slot.cloud_cover_pct is None:
            return ScenarioForecastFailure("insufficient_scenario_data")
        cloud_class = classify_cloud_cover(slot.cloud_cover_pct)
        band = bands.get(cloud_class)
        grid = band.get("quantile_grid") if band else None
        if not grid:
            return ScenarioForecastFailure("insufficient_scenario_data")
        grids.append(grid)

    rng = random.Random(seed)
    surplus_p50_w: list[float] = []
    surplus_p25_w: list[float] = []
    pv_p25_w: list[float] = []
    for slot, grid in zip(slots, grids):
        pv_samples = [max(0.0, slot.pv_forecast_w * sample_multiplier(grid, rng.uniform(0.0, 100.0))) for _ in range(scenario_count)]
        surplus_samples = [max(0.0, pv - slot.load_forecast_w - slot.charge_w) for pv in pv_samples]
        surplus_p50_w.append(percentile(surplus_samples, 50.0))
        surplus_p25_w.append(percentile(surplus_samples, 25.0))
        pv_p25_w.append(percentile(pv_samples, 25.0))

    return ScenarioForecastResult(
        surplus_p50_w=surplus_p50_w,
        surplus_p25_w=surplus_p25_w,
        pv_p25_w=pv_p25_w,
        scenario_count=scenario_count,
    )
