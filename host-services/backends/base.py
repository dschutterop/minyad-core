"""Shared inverter backend abstractions for the GoodWe bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InverterState:
    battery_soc: int
    battery_soh: int
    battery_power_w: int
    battery_voltage_v: float
    battery_temperature_c: float
    battery_mode: str
    inverter_temperature_c: float
    grid_power_w: int


class InverterBackend(Protocol):
    async def read_state(self) -> InverterState:
        """Poll inverter and return structured state."""
        ...

    async def set_charge(self, watts: int) -> None:
        """Set grid-charge power in watts. 0 = stop charging."""
        ...

    async def set_discharge(self, watts: int) -> None:
        """Set discharge-to-load power in watts. 0 = stop discharging."""
        ...
