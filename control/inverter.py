"""Async GoodWe ES inverter wrapper for Minyad battery control."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import goodwe

LOGGER = logging.getLogger(__name__)
WORK_MODE_ECO = 3


@dataclass(frozen=True, slots=True)
class InverterSettings:
    inverter_ip: str
    inverter_retries: int
    inverter_delay: int
    max_charge_a: int


class InverterUnavailable(RuntimeError):
    """Raised when the inverter cannot be reached after configured retries."""


class GoodWeInverter:
    """Thin async wrapper around the goodwe library with safe W→A conversion."""

    def __init__(self, settings: InverterSettings) -> None:
        self.settings = settings

    async def connect(self) -> Any:
        last_error: BaseException | None = None
        retries = max(1, self.settings.inverter_retries)
        for attempt in range(retries):
            try:
                return await goodwe.connect(self.settings.inverter_ip)
            except (goodwe.exceptions.InverterError, OSError, asyncio.TimeoutError) as exc:
                last_error = exc
                LOGGER.warning(
                    "Inverter %s connect attempt %s/%s failed: %s",
                    self.settings.inverter_ip,
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt < retries - 1:
                    await asyncio.sleep(self.settings.inverter_delay)
        raise InverterUnavailable(f"Inverter {self.settings.inverter_ip} unreachable after {retries} attempt(s)") from last_error

    async def read_status(self) -> dict[str, Any]:
        inv = await self.connect()
        data = await inv.read_runtime_data()
        return {
            "soc": data.get("battery_soc"),
            "soh": data.get("battery_soh"),
            "power_w": data.get("pbattery1"),
            "voltage": data.get("vbattery1"),
            "charge_i": await inv.read_setting("charge_i"),
        }

    async def set_charge_power(self, watts: int) -> int:
        inv = await self.connect()
        data = await inv.read_runtime_data()
        voltage = float(data["vbattery1"])
        amps = max(0, min(self.settings.max_charge_a, round(watts / voltage)))
        await inv.write_setting("work_mode", WORK_MODE_ECO)
        await inv.write_setting("charge_i", amps)
        return amps

    async def stop_charging(self) -> None:
        inv = await self.connect()
        await inv.write_setting("charge_i", 0)

    async def set_discharge_power(self, watts: int) -> int:
        inv = await self.connect()
        data = await inv.read_runtime_data()
        voltage = float(data["vbattery1"])
        amps = max(0, min(self.settings.max_charge_a, round(watts / voltage)))
        await inv.write_setting("discharge_i", amps)
        return amps
