"""Modbus TCP backend for a GoodWe ES inverter behind a TCP-to-RS485 gateway."""

from __future__ import annotations

import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from .base import InverterState

logger = logging.getLogger("goodwe_bridge")

REG_VGRID = 0x001E
REG_PGRID = 0x0020
REG_TEMPERATURE = 0x007A
REG_BATTERY_SOC = 0x0168
REG_CHARGE_LIMIT = 0x032C
REG_DISCHARGE_LIMIT = 0x032D


def _u16(value: int) -> int:
    return value & 0xFFFF


def _s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class ModbusBackend:
    def __init__(self, host: str, port: int, slave_id: int, timeout: float, max_w: int) -> None:
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.timeout = timeout
        self.max_w = max_w
        self.client: AsyncModbusTcpClient | None = None

    async def _connect(self) -> AsyncModbusTcpClient:
        if self.client is None:
            self.client = AsyncModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        if not self.client.connected:
            if not await self.client.connect():
                logger.warning("Modbus connection failed to %s:%s", self.host, self.port)
                raise ConnectionError(f"Modbus gateway unreachable at {self.host}:{self.port}")
        return self.client

    async def _read_holding_registers(self, address: int, count: int) -> list[int]:
        client = await self._connect()
        try:
            result = await client.read_holding_registers(address=address, count=count, slave=self.slave_id)
        except TypeError:
            result = await client.read_holding_registers(address=address, count=count, unit=self.slave_id)
        if result.isError():
            raise RuntimeError(f"Modbus read failed at 0x{address:04x}: {result}")
        return list(result.registers)

    async def _write_limit(self, address: int, pct: int) -> None:
        client = await self._connect()
        registers = [0x0500, 0x0017, 0x3B00 | pct]
        try:
            result = await client.write_registers(address=address, values=registers, slave=self.slave_id)
        except TypeError:
            result = await client.write_registers(address=address, values=registers, unit=self.slave_id)
        if result.isError():
            raise RuntimeError(f"Modbus write failed at 0x{address:04x}: {result}")

    def _watts_to_pct(self, watts: int) -> tuple[int, int]:
        safe_watts = max(0, min(self.max_w, int(watts)))
        if self.max_w <= 0:
            return safe_watts, 0
        return safe_watts, max(0, min(100, round((safe_watts / self.max_w) * 100)))

    async def set_charge(self, watts: int) -> None:
        safe_watts, pct = self._watts_to_pct(watts)
        await self._write_limit(REG_DISCHARGE_LIMIT, 0)
        await self._write_limit(REG_CHARGE_LIMIT, pct)
        logger.info("Modbus write: charge=%sW (%s%%)", safe_watts, pct)

    async def set_discharge(self, watts: int) -> None:
        safe_watts, pct = self._watts_to_pct(watts)
        await self._write_limit(REG_CHARGE_LIMIT, 0)
        await self._write_limit(REG_DISCHARGE_LIMIT, pct)
        logger.info("Modbus write: discharge=%sW (%s%%)", safe_watts, pct)

    async def read_state(self) -> InverterState:
        grid = await self._read_holding_registers(REG_VGRID, 0x0044 - REG_VGRID + 1)
        temp = await self._read_holding_registers(REG_TEMPERATURE, 1)
        battery = await self._read_holding_registers(REG_BATTERY_SOC, 0x0178 - REG_BATTERY_SOC + 1)

        def g(address: int) -> int:
            return grid[address - REG_VGRID]

        def b(address: int) -> int:
            return battery[address - REG_BATTERY_SOC]

        mode = {0: "idle", 1: "charge", 2: "discharge"}.get(_u16(b(0x0170)), "idle")
        return InverterState(
            battery_soc=_u16(b(0x0168)),
            battery_soh=_u16(b(0x0169)),
            battery_power_w=_s16(b(0x016C)),
            battery_voltage_v=_u16(b(0x016A)) / 10.0,
            battery_temperature_c=_s16(b(0x0178)) / 10.0,
            battery_mode=mode,
            inverter_temperature_c=_s16(temp[0]) / 10.0,
            grid_power_w=_s16(g(REG_PGRID)),
        )
