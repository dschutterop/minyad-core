"""Modbus TCP backend for a GoodWe inverter behind a TCP-to-RS485 gateway.

This adapter is only the actuator for battery limit ceilings. GoodWe API is the
primary telemetry source; P1 data is the primary import/export decision source.

Live tests proved registers 45565/45566 are writable. The 475xx EMS force
registers were tested and are not available on this inverter, so these limits
are not active force-charge/force-discharge setpoints.
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

POLL_INTERVAL_SEC = 2
MIN_WRITE_INTERVAL_SEC = 10
MIN_TARGET_CHANGE_W = 150
WRITE_REFRESH_INTERVAL_SEC = 600
POST_WRITE_FEEDBACK_SETTLE_SEC = 1.0


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
        if not self.client.connected and not await self.client.connect():
            logger.warning("[modbus] Modbus connection failed to %s:%s", self.host, self.port)
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
            logger.info("[modbus] DRY-RUN Modbus write skipped register=%s value=%s", address, value)
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

    async def read_status(self) -> dict[str, int]:
        return await self.read_current_limits()

    async def read_current_limits(self) -> dict[str, int]:
        """Read proven battery limit registers for verification/debug only."""
        regs = await self._read_holding_registers(REG_BATTERY_CHARGE_LIMIT_W, 2)
        return {"charge_limit_w": _u16(regs[0]), "discharge_limit_w": _u16(regs[1])}

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
                "[modbus] Modbus battery limits applied charge_limit_w=%s discharge_limit_w=%s registers={%s:%s,%s:%s} dry_run=%s",
                charge, discharge, REG_BATTERY_CHARGE_LIMIT_W, charge, REG_BATTERY_DISCHARGE_LIMIT_W, discharge, self.dry_run,
            )
            if self.post_write_feedback_settle_s:
                await asyncio.sleep(self.post_write_feedback_settle_s)
            return True

    def _skip_write(self, reason: str, charge: int, discharge: int) -> None:
        self.metrics.skip(reason)
        logger.info(
            "[modbus] Modbus write skipped reason=%s target_charge_limit_w=%s target_discharge_limit_w=%s current_charge_limit_w=%s current_discharge_limit_w=%s",
            reason, charge, discharge, self.metrics.current_charge_limit_w, self.metrics.current_discharge_limit_w,
        )

    async def set_charge(self, watts: int) -> None:
        await self.set_battery_limits(watts, 0)

    async def set_discharge(self, watts: int) -> None:
        await self.set_battery_limits(0, watts)

    async def stop_forced_mode(self) -> None:
        """No-op: Modbus limits are ceilings, never an active force-charge/discharge setpoint."""

    async def read_state(self) -> InverterState:
        raise RuntimeError("Modbus telemetry disabled: use GoodWe API for inverter telemetry")
