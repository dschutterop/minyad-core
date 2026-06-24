"""Modbus TCP backend for a GoodWe inverter behind a TCP-to-RS485 gateway.

This adapter intentionally stays dumb: it knows GoodWe register addresses and
how to read/write them, but it does not decide when the battery should charge or
discharge. Minyad's control service supplies both actuator values.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic, time

from pymodbus.client import AsyncModbusTcpClient

from .base import InverterState

logger = logging.getLogger("goodwe_bridge")

REG_BATTERY_CHARGE_LIMIT_W = 45565
REG_BATTERY_DISCHARGE_LIMIT_W = 45566
REG_BATTERY_VOLTAGE = 35180
REG_BATTERY_POWER = 35182
REG_WORK_MODE = 35187
REG_FIRMWARE_1 = 35016
REG_FIRMWARE_2 = 35017
REG_FIRMWARE_3 = 35020

POLL_INTERVAL_SEC = 2
MIN_WRITE_INTERVAL_SEC = 10
MIN_TARGET_CHANGE_W = 150
WRITE_REFRESH_INTERVAL_SEC = 600
POST_WRITE_FEEDBACK_SETTLE_SEC = 1.0


@dataclass(frozen=True)
class ModbusStatus:
    battery_power_w: int
    battery_voltage_v: float
    work_mode: int
    firmware: tuple[int, int, int]



@dataclass
class ModbusMetrics:
    modbus_reads_total: int = 0
    modbus_writes_total: int = 0
    modbus_write_skipped_total: int = 0
    modbus_errors_total: int = 0
    last_successful_read_timestamp: float | None = None
    last_successful_write_timestamp: float | None = None
    current_charge_limit_w: int = 0
    current_discharge_limit_w: int = 0
    target_charge_limit_w: int = 0
    target_discharge_limit_w: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.modbus_write_skipped_total += 1
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + 1

def _u16(value: int) -> int:
    return value & 0xFFFF


def _s32(high: int, low: int) -> int:
    value = ((_u16(high) << 16) | _u16(low)) & 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


class ModbusBackend:
    def __init__(self, host: str, port: int, slave_id: int, timeout: float, max_w: int, *, dry_run: bool = False, min_write_interval_s: float = MIN_WRITE_INTERVAL_SEC, min_target_change_w: int = MIN_TARGET_CHANGE_W, write_refresh_interval_s: float = WRITE_REFRESH_INTERVAL_SEC, post_write_feedback_settle_s: float = POST_WRITE_FEEDBACK_SETTLE_SEC) -> None:
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.timeout = timeout
        self.max_w = max_w
        self.dry_run = dry_run
        self.client: AsyncModbusTcpClient | None = None
        self.min_write_interval_s = max(0.0, float(min_write_interval_s))
        self.min_target_change_w = max(0, int(min_target_change_w))
        self.write_refresh_interval_s = max(0.0, float(write_refresh_interval_s))
        self.post_write_feedback_settle_s = max(0.0, float(post_write_feedback_settle_s))
        self.metrics = ModbusMetrics()
        self._write_lock = asyncio.Lock()
        self._last_write_monotonic: float | None = None

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
            self.metrics.modbus_errors_total += 1
            raise RuntimeError(f"Modbus read failed at {address}: {result}")
        self.metrics.modbus_reads_total += 1
        self.metrics.last_successful_read_timestamp = time()
        return list(result.registers)

    async def _write_register(self, address: int, value: int) -> None:
        if self.dry_run:
            logger.info("DRY-RUN Modbus write skipped register=%s value=%s", address, value)
            return
        client = await self._connect()
        try:
            result = await client.write_register(address=address, value=value, slave=self.slave_id)
        except AttributeError:
            result = await client.write_registers(address=address, values=[value], slave=self.slave_id)
        except TypeError:
            try:
                result = await client.write_register(address=address, value=value, unit=self.slave_id)
            except AttributeError:
                result = await client.write_registers(address=address, values=[value], unit=self.slave_id)
        if result.isError():
            self.metrics.modbus_errors_total += 1
            raise RuntimeError(f"Modbus write failed at {address}: {result}")
        self.metrics.modbus_writes_total += 1

    def _clamp_watts(self, watts: int) -> int:
        return max(0, min(self.max_w, int(watts)))

    async def read_status(self) -> ModbusStatus:
        battery = await self._read_holding_registers(REG_BATTERY_VOLTAGE, REG_WORK_MODE - REG_BATTERY_VOLTAGE + 1)
        firmware_1 = (await self._read_holding_registers(REG_FIRMWARE_1, 2))[:2]
        firmware_3 = (await self._read_holding_registers(REG_FIRMWARE_3, 1))[0]

        def b(address: int) -> int:
            return battery[address - REG_BATTERY_VOLTAGE]

        return ModbusStatus(
            battery_power_w=_s32(b(REG_BATTERY_POWER), b(REG_BATTERY_POWER + 1)),
            battery_voltage_v=_u16(b(REG_BATTERY_VOLTAGE)) / 10.0,
            work_mode=_u16(b(REG_WORK_MODE)),
            firmware=(_u16(firmware_1[0]), _u16(firmware_1[1]), _u16(firmware_3)),
        )

    async def set_battery_limits(self, charge_limit_w: int, discharge_limit_w: int, *, state_changed: bool = False) -> bool:
        charge = self._clamp_watts(charge_limit_w)
        discharge = self._clamp_watts(discharge_limit_w)
        self.metrics.target_charge_limit_w = charge
        self.metrics.target_discharge_limit_w = discharge
        async with self._write_lock:
            now = monotonic()
            unchanged = charge == self.metrics.current_charge_limit_w and discharge == self.metrics.current_discharge_limit_w
            last_write_age = None if self._last_write_monotonic is None else now - self._last_write_monotonic
            if unchanged and not (last_write_age is not None and last_write_age >= self.write_refresh_interval_s):
                self._skip_write("unchanged target", charge, discharge)
                return False
            delta = max(abs(charge - self.metrics.current_charge_limit_w), abs(discharge - self.metrics.current_discharge_limit_w))
            if not state_changed and delta < self.min_target_change_w and not unchanged:
                self._skip_write("below min delta", charge, discharge)
                return False
            if last_write_age is not None and last_write_age < self.min_write_interval_s:
                self._skip_write("write interval not elapsed", charge, discharge)
                return False
            await self._write_register(REG_BATTERY_CHARGE_LIMIT_W, charge)
            await self._write_register(REG_BATTERY_DISCHARGE_LIMIT_W, discharge)
            self._last_write_monotonic = monotonic()
            self.metrics.last_successful_write_timestamp = time()
            self.metrics.current_charge_limit_w = charge
            self.metrics.current_discharge_limit_w = discharge
            logger.info(
                "Modbus battery limits applied charge_limit_w=%s discharge_limit_w=%s registers={%s:%s,%s:%s} dry_run=%s",
                charge, discharge, REG_BATTERY_CHARGE_LIMIT_W, charge, REG_BATTERY_DISCHARGE_LIMIT_W, discharge, self.dry_run,
            )
            if self.post_write_feedback_settle_s:
                await asyncio.sleep(self.post_write_feedback_settle_s)
            return True

    def _skip_write(self, reason: str, charge: int, discharge: int) -> None:
        self.metrics.skip(reason)
        logger.info(
            "Modbus write skipped reason=%s target_charge_limit_w=%s target_discharge_limit_w=%s current_charge_limit_w=%s current_discharge_limit_w=%s",
            reason, charge, discharge, self.metrics.current_charge_limit_w, self.metrics.current_discharge_limit_w,
        )

    async def set_charge(self, watts: int) -> None:
        await self.set_battery_limits(watts, 0)

    async def set_discharge(self, watts: int) -> None:
        await self.set_battery_limits(0, watts)

    async def read_state(self) -> InverterState:
        status = await self.read_status()
        mode = {0: "idle", 1: "charge", 2: "discharge"}.get(status.work_mode, "idle")
        return InverterState(
            battery_soc=None,
            battery_soh=None,
            battery_power_w=status.battery_power_w,
            battery_voltage_v=status.battery_voltage_v,
            battery_temperature_c=None,
            battery_mode=mode,
            inverter_temperature_c=None,
            grid_power_w=None,
        )
