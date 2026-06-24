"""Shared inverter backend abstractions for the GoodWe bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InverterState:
    battery_soc: int | None
    battery_soh: int | None
    battery_power_w: int | None
    battery_voltage_v: float | None
    battery_temperature_c: float | None
    battery_mode: str | None
    inverter_temperature_c: float | None
    grid_power_w: int | None


class InverterBackend(Protocol):
    async def read_status(self) -> object:
        """Poll raw backend status, when supported."""
        ...

    async def set_battery_limits(self, charge_limit_w: int, discharge_limit_w: int) -> None:
        """Apply charge/discharge actuator limits in watts."""
        ...

    async def read_state(self) -> InverterState:
        """Poll inverter and return structured state."""
        ...

    async def set_charge(self, watts: int) -> None:
        """Set grid-charge power in watts. 0 = stop charging."""
        ...

    async def set_discharge(self, watts: int) -> None:
        """Set discharge-to-load power in watts. 0 = stop discharging."""
        ...
