"""Dataclasses for strategy v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class DayPlan:
    date: date
    solar_mode: str
    forecast_ghi_kwh_m2: float
    effective_soc_floor: int
    effective_soc_ceiling: int
    grid_charge_windows: list[Window] = field(default_factory=list)
    price_discharge_windows: list[Window] = field(default_factory=list)
    planned_soc_at_sunset: int = 50
    valid_until: datetime | None = None
    reason: str = "default plan"

    def in_grid_charge_window(self, now: datetime) -> bool:
        return _in_window(self.grid_charge_windows, now)

    def in_price_discharge_window(self, now: datetime) -> bool:
        return _in_window(self.price_discharge_windows, now)


@dataclass(frozen=True)
class ExecutorState:
    net_grid_w: int
    battery_soc: float | None = None
    battery_power_w: int = 0
    solar_forecast_w: int = 0
    battery_voltage: float | None = None
    bridge_last_seen: datetime | None = None
    current_setpoint_w: int = 0


@dataclass(frozen=True)
class StrategyDecision:
    timestamp: datetime
    setpoint_w: int
    soc: float | None
    net_grid_w: int
    solar_forecast_w: int
    mode: str
    reason: str
    plan_date: date
    in_grid_charge_window: bool
    in_price_discharge_window: bool


def _in_window(windows: list[Window], now: datetime) -> bool:
    return any(start <= now < end for start, end in windows)
