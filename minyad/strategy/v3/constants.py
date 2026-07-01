"""Typed settings for strategy v3."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text


DEFAULTS: dict[str, str] = {
    # Retained v2 keys (same semantics, same defaults).
    "battery.soc_floor": "20",
    "battery.soc_ceiling": "90",
    "battery.max_charge_w": "1440",
    "battery.max_discharge_w": "5000",
    "battery.max_charge_a": "30",
    "battery.nominal_v": "48",
    "battery.inverter_poll_interval_s": "120",
    "battery.goodwe_poll_interval_grace_s": "60",
    "strategy.grid_charge_enabled": "false",
    "strategy.grid_target_w": "0",
    "strategy.ramp_floor_w": "200",
    "strategy.ramp_hold_seconds": "90",
    "strategy.ramp_ceiling_w": "800",
    "strategy.balance_gain": "0.6",
    "strategy.jitter_w": "50",
    "strategy.export_block_threshold_w": "100",
    "strategy.export_block_hysteresis_w": "50",
    "strategy.soc_hysteresis_pct": "2",
    "strategy.bridge_stale_seconds": "180",
    "strategy.voltage_floor_v": "46.0",
    "strategy.adjustment_log_interval_sec": "300",
    # New v3 keys.
    "battery.capacity_wh": "10240",
    "strategy3.plan_interval_min": "15",
    "strategy3.horizon_slots": "96",
    "strategy3.one_way_efficiency": "0.95",
    "strategy3.cycle_cost_eur_kwh": "0.03",
    "strategy3.fixed_price_import": "0.25",
    "strategy3.fixed_price_export": "0.00",
    "strategy3.export_cap_w": "0",
    "strategy3.grid_charge_relax_w": "0",
    "strategy3.terminal_soc_pct": "30",
    "strategy3.traj_tau_hours": "2.0",
    "strategy3.traj_bias_max_w": "400",
    "strategy3.traj_deadband_pct": "3",
    "strategy3.traj_band_pct": "8",
    "strategy3.pv_calibration_factor": "7.0",
    "strategy3.consumption_lookback_days": "14",
    "strategy3.consumption_fallback_w": "300",
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

    async def set(self, key: str, value: Any) -> None:
        """Persist a single setting (used by the daily PV calibration job)."""
        self.values[key] = str(value)
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            await session.execute(
                text(
                    """
                    insert into settings (key, value, encrypted) values (:key, :value, false)
                    on conflict (key) do update set value = excluded.value
                    """
                ),
                {"key": key, "value": str(value)},
            )
            await session.commit()

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
    def capacity_wh(self) -> float:
        return self.float("battery.capacity_wh")

    @property
    def grid_charge_enabled(self) -> bool:
        return self.bool("strategy.grid_charge_enabled")

    @property
    def grid_target_w(self) -> int:
        return self.int("strategy.grid_target_w")

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
    def export_block_hysteresis_w(self) -> int:
        return self.int("strategy.export_block_hysteresis_w")

    @property
    def soc_hysteresis_pct(self) -> float:
        return self.float("strategy.soc_hysteresis_pct")

    @property
    def adjustment_log_interval_sec(self) -> int:
        return self.int("strategy.adjustment_log_interval_sec")

    @property
    def bridge_stale_seconds(self) -> int:
        poll_interval = self.values.get("battery.inverter_poll_interval_s")
        grace = self.values.get("battery.goodwe_poll_interval_grace_s")
        if poll_interval is not None and grace is not None:
            return int(float(poll_interval)) + int(float(grace))
        return self.int("strategy.bridge_stale_seconds")

    @property
    def voltage_floor_v(self) -> float:
        return self.float("strategy.voltage_floor_v")

    @property
    def plan_interval_min(self) -> int:
        return self.int("strategy3.plan_interval_min")

    @property
    def horizon_slots(self) -> int:
        return self.int("strategy3.horizon_slots")

    @property
    def one_way_efficiency(self) -> float:
        return self.float("strategy3.one_way_efficiency")

    @property
    def cycle_cost_eur_kwh(self) -> float:
        return self.float("strategy3.cycle_cost_eur_kwh")

    @property
    def fixed_price_import(self) -> float:
        return self.float("strategy3.fixed_price_import")

    @property
    def fixed_price_export(self) -> float:
        return self.float("strategy3.fixed_price_export")

    @property
    def export_cap_w(self) -> int:
        return self.int("strategy3.export_cap_w")

    @property
    def grid_charge_relax_w(self) -> int:
        return self.int("strategy3.grid_charge_relax_w")

    @property
    def terminal_soc_pct(self) -> int:
        return self.int("strategy3.terminal_soc_pct")

    @property
    def traj_tau_hours(self) -> float:
        return self.float("strategy3.traj_tau_hours")

    @property
    def traj_bias_max_w(self) -> int:
        return self.int("strategy3.traj_bias_max_w")

    @property
    def traj_deadband_pct(self) -> float:
        return self.float("strategy3.traj_deadband_pct")

    @property
    def traj_band_pct(self) -> float:
        return self.float("strategy3.traj_band_pct")

    @property
    def pv_calibration_factor(self) -> float:
        return self.float("strategy3.pv_calibration_factor")

    @property
    def consumption_lookback_days(self) -> int:
        return self.int("strategy3.consumption_lookback_days")

    @property
    def consumption_fallback_w(self) -> float:
        return self.float("strategy3.consumption_fallback_w")
