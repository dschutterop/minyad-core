import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from minyad.strategy.v2 import Settings, StrategyPlanner
from minyad.strategy.v2.planner import default_day_plan

TZ = ZoneInfo("Europe/Amsterdam")


def prices(day: date):
    rows = []
    start = datetime.combine(day, datetime.min.time(), TZ)
    for hour in range(24):
        price = 0.15
        if hour in {2, 3, 4}:
            price = 0.05
        if hour in {18, 19}:
            price = 0.30
        rows.append({"start": (start + timedelta(hours=hour)).isoformat(), "end": (start + timedelta(hours=hour + 1)).isoformat(), "price_eur_kwh": price})
    return rows


def test_solar_rich_lowers_effective_floor():
    planner = StrategyPlanner(Settings())
    plan = planner.build_plan(date(2026, 6, 28), 5.0, [])
    assert plan.solar_mode == "SOLAR_RICH"
    assert plan.effective_soc_floor == 10


def test_solar_poor_raises_effective_ceiling():
    planner = StrategyPlanner(Settings())
    plan = planner.build_plan(date(2026, 6, 28), 1.0, [])
    assert plan.solar_mode == "SOLAR_POOR"
    assert plan.effective_soc_ceiling == 95


def test_price_windows_are_identified_and_cheap_is_overnight():
    day = date(2026, 6, 28)
    planner = StrategyPlanner(Settings(initial={"strategy.grid_charge_enabled": "true"}))
    plan = planner.build_plan(day, 2.0, prices(day))
    assert len(plan.grid_charge_windows) == 1
    assert plan.grid_charge_windows[0][0].hour == 2
    assert plan.grid_charge_windows[0][1].hour == 5
    assert len(plan.price_discharge_windows) == 1
    assert plan.price_discharge_windows[0][0].hour == 18


def test_friday_lifepo4_cycle_raises_ceiling_without_grid_charge():
    friday = date(2026, 7, 3)
    planner = StrategyPlanner(Settings(initial={"strategy.grid_charge_enabled": "true"}))
    plan = planner.build_plan(friday, 2.0, prices(friday))

    assert plan.effective_soc_ceiling == 100
    assert plan.planned_soc_at_sunset == 100
    assert plan.grid_charge_windows == []
    assert "solar surplus only" in plan.reason


def test_default_friday_plan_allows_lifepo4_full_cycle():
    now = datetime(2026, 7, 3, 9, tzinfo=TZ)
    plan = default_day_plan(Settings(), now)

    assert plan.effective_soc_ceiling == 100
    assert plan.grid_charge_windows == []


def test_plan_is_idempotent():
    day = date(2026, 6, 28)
    planner = StrategyPlanner(Settings(initial={"strategy.grid_charge_enabled": "true"}))
    first = planner.build_plan(day, 2.0, prices(day))
    second = planner.build_plan(day, 2.0, prices(day))
    assert first == second


def test_async_recalculate_uses_fetcher():
    day = date(2026, 6, 28)
    planner = StrategyPlanner(Settings(), ghi_fetcher=lambda _: 5.2)
    plan = asyncio.run(planner.recalculate(day, []))
    assert plan.solar_mode == "SOLAR_RICH"
