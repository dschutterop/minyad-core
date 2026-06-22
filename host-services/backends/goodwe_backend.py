"""GoodWe UDP/AA55 backend for the host-side bridge."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any

import goodwe
from goodwe.protocol import Aa55ProtocolCommand

from .base import InverterState

logger = logging.getLogger("goodwe_bridge")


class GoodWeBackend:
    def __init__(
        self,
        inverter_ip: str,
        max_w: int,
        *,
        retries: int = 5,
        delay: int = 3,
        min_request_interval_s: float = 2.0,
    ) -> None:
        self.inverter_ip = inverter_ip
        self.max_w = max_w
        self.retries = retries
        self.delay = delay
        self.min_request_interval_s = max(0.0, min_request_interval_s)
        self._inverter: Any | None = None
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _wait_for_request_slot(self) -> None:
        elapsed = monotonic() - self._last_request_at
        wait_for = self.min_request_interval_s - elapsed
        if wait_for > 0:
            logger.debug("Throttling GoodWe inverter request for %.2fs", wait_for)
            await asyncio.sleep(wait_for)
        self._last_request_at = monotonic()

    async def _get_inverter(self) -> Any:
        if self._inverter is not None:
            return self._inverter
        for attempt in range(self.retries):
            try:
                self._inverter = await goodwe.connect(self.inverter_ip, family="ES")
                return self._inverter
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

    async def _send_command(self, inv: Any, command: str, response_type: str) -> None:
        await self._wait_for_request_slot()
        await inv._read_from_socket(Aa55ProtocolCommand(command, response_type))

    async def set_charge(self, watts: int) -> None:
        pct = self._watts_to_pct(watts)
        async with self._request_lock:
            inv = await self._get_inverter()
            await self._send_command(inv, "032d050000173b00", "03AD")
            await self._send_command(inv, f"032c050000173b{pct:02x}", "03AC")
        logger.info("GoodWe write: charge=%sW (%s%%)", max(0, min(self.max_w, int(watts))), pct)

    async def set_discharge(self, watts: int) -> None:
        pct = self._watts_to_pct(watts)
        async with self._request_lock:
            inv = await self._get_inverter()
            await self._send_command(inv, "032c050000173b00", "03AC")
            await self._send_command(inv, f"032d050000173b{pct:02x}", "03AD")
        logger.info("GoodWe write: discharge=%sW (%s%%)", max(0, min(self.max_w, int(watts))), pct)

    async def read_state(self) -> InverterState:
        async with self._request_lock:
            inv = await self._get_inverter()
            await self._wait_for_request_slot()
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
