"""Daily planner for battery strategy v2."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from .constants import Settings
from .models import DayPlan, Window

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SCHIPLUIDEN_LAT = 51.97
SCHIPLUIDEN_LON = 4.31


class StrategyPlanner:
    def __init__(
        self,
        settings: Settings,
        db_session_factory: Any | None = None,
        *,
        timezone_name: str = "Europe/Amsterdam",
        ghi_fetcher: Any | None = None,
    ) -> None:
        self.settings = settings
        self.db_session_factory = db_session_factory
        self.tz = ZoneInfo(timezone_name)
        self._ghi_fetcher = ghi_fetcher
        self.prices: list[dict[str, Any]] = []

    def set_prices(self, prices: list[dict[str, Any]]) -> None:
        self.prices = prices

    async def recalculate(self, plan_date: date | None = None, prices: list[dict[str, Any]] | None = None) -> DayPlan:
        target_date = plan_date or (datetime.now(self.tz).date() + timedelta(days=1))
        price_rows = prices if prices is not None else self.prices
        if not price_rows:
            price_rows = await self._load_prices_from_db()
        ghi = await self.fetch_daily_ghi(target_date)
        plan = self.build_plan(target_date, ghi, price_rows)
        await self.persist(plan)
        return plan

    def build_plan(self, plan_date: date, ghi: float, prices: list[dict[str, Any]]) -> DayPlan:
        rich = self.settings.float("strategy.ghi_solar_rich_threshold")
        poor = self.settings.float("strategy.ghi_solar_poor_threshold")
        floor = self.settings.soc_floor
        ceiling = self.settings.soc_ceiling
        if ghi > rich:
            mode = "SOLAR_RICH"
            effective_floor = max(10, floor - 10)
            effective_ceiling = ceiling
            sunset_target = effective_floor + 20
        elif ghi < poor:
            mode = "SOLAR_POOR"
            effective_floor = floor
            effective_ceiling = min(ceiling + 10, 95)
            sunset_target = effective_ceiling - 5
        else:
            mode = "NORMAL"
            effective_floor = floor
            effective_ceiling = ceiling
            sunset_target = floor + 30

        grid_charge_windows: list[Window] = []
        if self.settings.bool("strategy.grid_charge_enabled") and mode in {"SOLAR_POOR", "NORMAL"}:
            cheap = self._price_windows(prices, plan_date, below=self.settings.float("strategy.price_cheap_threshold_eur_kwh"))
            overnight = [window for window in cheap if self._is_overnight(window)]
            if overnight:
                grid_charge_windows = [min(overnight, key=self._window_min_price(prices))]

        price_discharge_windows = self._price_windows(prices, plan_date, above=self.settings.float("strategy.price_expensive_threshold_eur_kwh"))
        valid_until = datetime.combine(plan_date, time(23, 59, 59), self.tz)
        reason = f"{mode}: GHI {ghi:.2f} kWh/m2; {len(grid_charge_windows)} charge and {len(price_discharge_windows)} discharge price windows"
        return DayPlan(plan_date, mode, round(ghi, 3), effective_floor, effective_ceiling, grid_charge_windows, price_discharge_windows, sunset_target, valid_until, reason)

    async def fetch_daily_ghi(self, plan_date: date) -> float:
        if self._ghi_fetcher is not None:
            return float(await self._maybe_await(self._ghi_fetcher(plan_date)))
        params = {
            "latitude": SCHIPLUIDEN_LAT,
            "longitude": SCHIPLUIDEN_LON,
            "hourly": "shortwave_radiation",
            "start_date": plan_date.isoformat(),
            "end_date": plan_date.isoformat(),
            "timezone": "Europe/Amsterdam",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            values = response.json().get("hourly", {}).get("shortwave_radiation", [])
        return sum(float(value) for value in values) / 1000.0

    async def persist(self, plan: DayPlan) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            await session.execute(
                text("""
                    insert into day_plans (
                        plan_date, solar_mode, forecast_ghi_kwh_m2, effective_soc_floor,
                        effective_soc_ceiling, grid_charge_windows, price_discharge_windows,
                        planned_soc_at_sunset, valid_until, reason
                    ) values (
                        :plan_date, :solar_mode, :forecast_ghi, :floor, :ceiling,
                        cast(:grid_windows as jsonb), cast(:price_windows as jsonb),
                        :sunset_soc, :valid_until, :reason
                    )
                    on conflict (plan_date) do update set
                        solar_mode=excluded.solar_mode,
                        forecast_ghi_kwh_m2=excluded.forecast_ghi_kwh_m2,
                        effective_soc_floor=excluded.effective_soc_floor,
                        effective_soc_ceiling=excluded.effective_soc_ceiling,
                        grid_charge_windows=excluded.grid_charge_windows,
                        price_discharge_windows=excluded.price_discharge_windows,
                        planned_soc_at_sunset=excluded.planned_soc_at_sunset,
                        valid_until=excluded.valid_until,
                        reason=excluded.reason
                """),
                {
                    "plan_date": plan.date,
                    "solar_mode": plan.solar_mode,
                    "forecast_ghi": plan.forecast_ghi_kwh_m2,
                    "floor": plan.effective_soc_floor,
                    "ceiling": plan.effective_soc_ceiling,
                    "grid_windows": json.dumps(_windows_to_json(plan.grid_charge_windows)),
                    "price_windows": json.dumps(_windows_to_json(plan.price_discharge_windows)),
                    "sunset_soc": plan.planned_soc_at_sunset,
                    "valid_until": plan.valid_until,
                    "reason": plan.reason,
                },
            )
            await session.commit()

    async def load_plan(self, plan_date: date) -> DayPlan | None:
        if self.db_session_factory is None:
            return None
        async with self.db_session_factory() as session:
            result = await session.execute(text("select * from day_plans where plan_date=:d"), {"d": plan_date})
            row = result.first()
        if row is None:
            return None
        row = row._mapping
        return DayPlan(
            row["plan_date"],
            row["solar_mode"],
            float(row["forecast_ghi_kwh_m2"] or 0),
            int(row["effective_soc_floor"]),
            int(row["effective_soc_ceiling"]),
            _windows_from_json(row["grid_charge_windows"] or []),
            _windows_from_json(row["price_discharge_windows"] or []),
            int(row["planned_soc_at_sunset"] or 50),
            row["valid_until"],
            row["reason"] or "",
        )

    async def _load_prices_from_db(self) -> list[dict[str, Any]]:
        return []

    def _price_windows(self, prices: list[dict[str, Any]], plan_date: date, *, below: float | None = None, above: float | None = None) -> list[Window]:
        selected: list[Window] = []
        for row in prices:
            start = _parse_dt(row["start"]).astimezone(self.tz)
            end = _parse_dt(row["end"]).astimezone(self.tz)
            price = float(row["price_eur_kwh"])
            if start.date() != plan_date:
                continue
            if (below is not None and price < below) or (above is not None and price > above):
                selected.append((start, end))
        return _merge_contiguous(selected)

    def _is_overnight(self, window: Window) -> bool:
        start, end = window
        return start.hour >= 22 or end.hour <= 8 or start.hour < 8

    def _window_min_price(self, prices: list[dict[str, Any]]) -> Any:
        def key(window: Window) -> float:
            start, end = window
            values = [float(row["price_eur_kwh"]) for row in prices if start <= _parse_dt(row["start"]).astimezone(self.tz) < end]
            return min(values) if values else 999.0

        return key

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value


def default_day_plan(settings: Settings, now: datetime | None = None) -> DayPlan:
    current = (now or datetime.now(AMSTERDAM)).astimezone(AMSTERDAM)
    return DayPlan(
        current.date(),
        "NORMAL",
        0.0,
        settings.soc_floor,
        settings.soc_ceiling,
        [],
        [],
        settings.soc_floor + 30,
        datetime.combine(current.date(), time(23, 59, 59), AMSTERDAM),
        "default normal plan; no persisted day plan available",
    )


def _merge_contiguous(windows: list[Window]) -> list[Window]:
    if not windows:
        return []
    windows = sorted(windows)
    merged = [windows[0]]
    for start, end in windows[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _windows_to_json(windows: list[Window]) -> list[dict[str, str]]:
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in windows]


def _windows_from_json(rows: list[dict[str, str]]) -> list[Window]:
    return [(_parse_dt(row["start"]), _parse_dt(row["end"])) for row in rows]
