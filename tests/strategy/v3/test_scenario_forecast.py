from datetime import datetime, timezone

from minyad.strategy.v3.scenario_forecast import (
    ScenarioForecastFailure,
    ScenarioForecastResult,
    ScenarioSlotInput,
    generate_scenario_forecast,
    sample_multiplier,
)

UTC = timezone.utc


def _grid(*pairs):
    return [[level, value] for level, value in pairs]


def test_sample_multiplier_interpolates_between_grid_points():
    grid = _grid((0.0, 0.0), (100.0, 10.0))
    assert sample_multiplier(grid, 50.0) == 5.0
    assert sample_multiplier(grid, 25.0) == 2.5


def test_sample_multiplier_clamps_outside_grid_range():
    grid = _grid((10.0, 1.0), (90.0, 2.0))
    assert sample_multiplier(grid, 0.0) == 1.0
    assert sample_multiplier(grid, 100.0) == 2.0


def _slot(pv_w, load_w=300.0, charge_w=0.0, cloud_cover_pct=10.0):
    return ScenarioSlotInput(
        start=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
        pv_forecast_w=pv_w,
        load_forecast_w=load_w,
        charge_w=charge_w,
        cloud_cover_pct=cloud_cover_pct,
    )


def _skewed_band():
    # A right-skewed ratio distribution: most mass below 1.0, a long tail above. P50 and P25
    # are close together while P90 is far out — deliberately not a symmetric/linear spread, so
    # a "P25 = P50 * constant" implementation would not reproduce it.
    grid = _grid(
        (1.0, 0.2), (5.0, 0.3), (10.0, 0.35), (25.0, 0.45), (50.0, 0.5),
        (75.0, 0.6), (90.0, 1.4), (95.0, 1.8), (99.0, 2.2),
    )
    return {"clear": {"quantile_grid": grid}}


def test_generate_scenario_forecast_p25_never_exceeds_p50():
    slots = [_slot(pv_w=1500.0 + 10 * i) for i in range(20)]
    result = generate_scenario_forecast(slots, _skewed_band(), scenario_count=200, seed=7)
    assert isinstance(result, ScenarioForecastResult)
    assert all(p25 <= p50 for p25, p50 in zip(result.surplus_p25_w, result.surplus_p50_w))
    assert all(v >= 0.0 for v in result.surplus_p25_w)
    assert all(v >= 0.0 for v in result.surplus_p50_w)
    assert all(v >= 0.0 for v in result.pv_p25_w)


def test_generate_scenario_forecast_not_a_fixed_discount_of_p50():
    """P25 must come from the empirical scenario distribution, not P50 * constant.

    A narrow, symmetric distribution and this module's skewed one produce different
    P25/P50 ratios — a fixed-multiplier implementation would produce the same ratio for both.
    """
    narrow_grid = _grid((1.0, 0.95), (25.0, 0.98), (50.0, 1.0), (75.0, 1.02), (90.0, 1.04), (99.0, 1.05))
    narrow_band = {"clear": {"quantile_grid": narrow_grid}}
    skewed_band = _skewed_band()

    slots = [_slot(pv_w=2000.0, load_w=0.0, charge_w=0.0)]
    narrow_result = generate_scenario_forecast(slots, narrow_band, scenario_count=500, seed=1)
    skewed_result = generate_scenario_forecast(slots, skewed_band, scenario_count=500, seed=1)
    assert isinstance(narrow_result, ScenarioForecastResult)
    assert isinstance(skewed_result, ScenarioForecastResult)

    narrow_ratio = narrow_result.surplus_p25_w[0] / narrow_result.surplus_p50_w[0]
    skewed_ratio = skewed_result.surplus_p25_w[0] / skewed_result.surplus_p50_w[0]
    assert abs(narrow_ratio - skewed_ratio) > 0.05


def test_pv_p25_independent_of_load_and_battery_charge():
    """pv_p25_w reflects PV-only uncertainty, not net household surplus."""
    band = _skewed_band()
    # Load + planned charge fully absorb PV, so surplus collapses to (near) zero everywhere...
    zero_surplus_slots = [_slot(pv_w=1000.0, load_w=2000.0, charge_w=2000.0)]
    result = generate_scenario_forecast(zero_surplus_slots, band, scenario_count=300, seed=3)
    assert isinstance(result, ScenarioForecastResult)
    assert result.surplus_p50_w[0] == 0.0
    assert result.surplus_p25_w[0] == 0.0
    # ...but pv_p25_w must still reflect the PV distribution alone, not collapse to zero.
    assert result.pv_p25_w[0] > 0.0


def test_generate_scenario_forecast_fails_without_cloud_cover():
    slots = [_slot(pv_w=1000.0, cloud_cover_pct=None)]
    result = generate_scenario_forecast(slots, _skewed_band(), scenario_count=50, seed=1)
    assert isinstance(result, ScenarioForecastFailure)
    assert result.reason == "insufficient_scenario_data"


def test_generate_scenario_forecast_fails_when_band_missing_for_class():
    slots = [_slot(pv_w=1000.0, cloud_cover_pct=80.0)]  # cloudy, band only has "clear"
    result = generate_scenario_forecast(slots, _skewed_band(), scenario_count=50, seed=1)
    assert isinstance(result, ScenarioForecastFailure)
    assert result.reason == "insufficient_scenario_data"


def test_generate_scenario_forecast_fails_when_band_lacks_quantile_grid():
    slots = [_slot(pv_w=1000.0)]
    bands = {"clear": {"p10_multiplier": 0.7, "p90_multiplier": 1.3}}  # no quantile_grid
    result = generate_scenario_forecast(slots, bands, scenario_count=50, seed=1)
    assert isinstance(result, ScenarioForecastFailure)
    assert result.reason == "insufficient_scenario_data"
