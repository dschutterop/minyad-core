"""Typed settings for strategy v2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text


DEFAULTS: dict[str, str] = {
    "battery.soc_floor": "20",
    "battery.soc_ceiling": "90",
    "battery.max_charge_w": "1440",
    "battery.max_discharge_w": "5000",
    "battery.max_charge_a": "30",
    "battery.nominal_v": "48",
    "strategy.ghi_solar_rich_threshold": "4.5",
    "strategy.ghi_solar_poor_threshold": "1.5",
    "strategy.grid_target_w": "0",
    "strategy.price_cheap_threshold_eur_kwh": "0.08",
    "strategy.price_expensive_threshold_eur_kwh": "0.25",
    "strategy.grid_charge_enabled": "false",
    "strategy.daily_recalculate_local_time": "22:00",
    "strategy.ramp_floor_w": "200",
    "strategy.ramp_hold_seconds": "90",
    "strategy.ramp_ceiling_w": "800",
    "strategy.balance_gain": "0.6",
    "strategy.jitter_w": "50",
    "strategy.export_block_threshold_w": "100",
    "strategy.price_discharge_bias_w": "200",
    "strategy.control_refresh_interval_sec": "300",
    "strategy.active_command_retry_interval_sec": "60",
    "strategy.bridge_stale_seconds": "60",
    "strategy.voltage_floor_v": "46.0",
}


class Settings:
    """Settings backed by the PostgreSQL settings table, with in-memory fallback."""

    def __init__(self, db_session_factory: Any | None = None, initial: Mapping[str, Any] | None = None) -> None:
        self.db_session_factory = db_session_factory
        self.values: dict[str, str] = dict(DEFAULTS)
        if initial:
            self.values.update({key: str(value) for key, value in initial.items()})

    async def load(self) -> None:
        await self.reload()

    async def reload(self) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            result = await session.execute(text("select key, value from settings"))
            self.values.update({row.key: str(row.value) for row in result})

    def get(self, key: str, default: Any | None = None) -> str:
        return self.values.get(key, str(default) if default is not None else "")

    def int(self, key: str) -> int:
        return int(float(self.values[key]))

    def float(self, key: str) -> float:
        return float(self.values[key])

    def bool(self, key: str) -> bool:
        return self.values[key].strip().lower() in {"1", "true", "yes", "on"}

    @property
    def soc_floor(self) -> int:
        return self.int("battery.soc_floor")

    @property
    def soc_ceiling(self) -> int:
        return self.int("battery.soc_ceiling")

    @property
    def max_charge_w(self) -> int:
        return self.int("battery.max_charge_w")

    @property
    def max_discharge_w(self) -> int:
        return self.int("battery.max_discharge_w")

    @property
    def max_charge_a(self) -> int:
        return self.int("battery.max_charge_a")

    @property
    def nominal_v(self) -> int:
        return self.int("battery.nominal_v")

    @property
    def effective_max_charge_w(self) -> int:
        return min(self.max_charge_w, int(self.max_charge_a * self.nominal_v))

    @property
    def ramp_floor_w(self) -> int:
        return self.int("strategy.ramp_floor_w")

    @property
    def ramp_hold_seconds(self) -> int:
        return self.int("strategy.ramp_hold_seconds")

    @property
    def ramp_ceiling_w(self) -> int:
        return self.int("strategy.ramp_ceiling_w")

    @property
    def balance_gain(self) -> float:
        return self.float("strategy.balance_gain")

    @property
    def jitter_w(self) -> int:
        return self.int("strategy.jitter_w")

    @property
    def export_block_threshold_w(self) -> int:
        return self.int("strategy.export_block_threshold_w")

    @property
    def price_discharge_bias_w(self) -> int:
        return self.int("strategy.price_discharge_bias_w")

    @property
    def bridge_stale_seconds(self) -> int:
        return self.int("strategy.bridge_stale_seconds")

    @property
    def voltage_floor_v(self) -> float:
        return self.float("strategy.voltage_floor_v")
