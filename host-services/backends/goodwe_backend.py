"""GoodWe UDP/AA55 backend for the host-side bridge."""

from __future__ import annotations

import logging
from typing import Any

import goodwe
from goodwe.protocol import Aa55ProtocolCommand

from .base import InverterState

logger = logging.getLogger("goodwe_bridge")


class GoodWeBackend:
    def __init__(self, inverter_ip: str, max_w: int, *, retries: int = 5, delay: int = 3) -> None:
        self.inverter_ip = inverter_ip
        self.max_w = max_w
        self.retries = retries
        self.delay = delay

    async def _get_inverter(self) -> Any:
        import asyncio

        for attempt in range(self.retries):
            try:
                return await goodwe.connect(self.inverter_ip, family="ES")
            except goodwe.exceptions.InverterError as exc:
                logger.warning("Connect attempt %s/%s failed: %s", attempt + 1, self.retries, exc)
                if attempt < self.retries - 1:
                    await asyncio.sleep(self.delay)
        raise RuntimeError(f"Inverter unreachable after {self.retries} attempts")

    def _watts_to_pct(self, watts: int) -> int:
        if self.max_w <= 0:
            return 0
        pct = round((max(0, min(self.max_w, int(watts))) / self.max_w) * 100)
        return max(0, min(100, pct))

    async def _write_percent(self, register: str, pct: int) -> None:
        inv = await self._get_inverter()
        await inv._read_from_socket(Aa55ProtocolCommand(f"{register}050000173b{pct:02x}", register.upper()))

    async def set_charge(self, watts: int) -> None:
        pct = self._watts_to_pct(watts)
        inv = await self._get_inverter()
        await inv._read_from_socket(Aa55ProtocolCommand("032d050000173b00", "03AD"))
        await inv._read_from_socket(Aa55ProtocolCommand(f"032c050000173b{pct:02x}", "03AC"))
        logger.info("GoodWe write: charge=%sW (%s%%)", max(0, min(self.max_w, int(watts))), pct)

    async def set_discharge(self, watts: int) -> None:
        pct = self._watts_to_pct(watts)
        inv = await self._get_inverter()
        await inv._read_from_socket(Aa55ProtocolCommand("032c050000173b00", "03AC"))
        await inv._read_from_socket(Aa55ProtocolCommand(f"032d050000173b{pct:02x}", "03AD"))
        logger.info("GoodWe write: discharge=%sW (%s%%)", max(0, min(self.max_w, int(watts))), pct)

    async def read_state(self) -> InverterState:
        inv = await self._get_inverter()
        data = await inv.read_runtime_data()
        mode = _battery_mode_label(data.get("battery_mode"), data.get("battery_mode_label"))
        return InverterState(
            battery_soc=int(data["battery_soc"]),
            battery_soh=int(data["battery_soh"]),
            battery_power_w=int(data["pbattery1"]),
            battery_voltage_v=float(data["vbattery1"]),
            battery_temperature_c=float(data.get("battery_temperature", data.get("battery_temperature1", 0.0))),
            battery_mode=mode,
            inverter_temperature_c=float(data.get("temperature", data.get("temperature_air", 0.0))),
            grid_power_w=int(data.get("pgrid", 0)),
        )


def _battery_mode_label(value: object, fallback: object = None) -> str:
    if isinstance(fallback, str):
        text = fallback.lower()
        if "discharge" in text:
            return "discharge"
        if "charge" in text:
            return "charge"
        if "idle" in text or "standby" in text:
            return "idle"
    try:
        return {0: "idle", 1: "charge", 2: "discharge"}[int(value)]
    except Exception:
        return "idle"
