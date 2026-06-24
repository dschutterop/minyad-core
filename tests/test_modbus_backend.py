import asyncio
import importlib
import sys
import types
from pathlib import Path


class Result:
    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._error = error

    def isError(self):
        return self._error


class FakeModbusClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.connected = False
        self.writes = []
        FakeModbusClient.instances.append(self)

    async def connect(self):
        self.connected = True
        return True

    async def write_register(self, address, value, slave=None):
        self.writes.append((address, value, slave))
        return Result()

    async def read_holding_registers(self, address, count, slave=None):
        if address == 35180:
            regs = [520, 0, 0xFFFF, 0xFF9C, 0, 0, 0, 2]
            return Result(regs[:count])
        if address == 35016:
            return Result([1, 2])
        if address == 35020:
            return Result([3])
        return Result([0] * count)


def import_modbus_backend():
    pymodbus = types.ModuleType("pymodbus")
    client = types.ModuleType("pymodbus.client")
    client.AsyncModbusTcpClient = FakeModbusClient
    pymodbus.client = client
    sys.modules["pymodbus"] = pymodbus
    sys.modules["pymodbus.client"] = client
    host_services = Path(__file__).resolve().parents[1] / "host-services"
    if str(host_services) not in sys.path:
        sys.path.insert(0, str(host_services))
    sys.modules.pop("backends.modbus_backend", None)
    return importlib.import_module("backends.modbus_backend")


def test_set_battery_limits_writes_only_proven_goodwe_limit_registers():
    modbus = import_modbus_backend()

    async def run():
        backend = modbus.ModbusBackend("127.0.0.1", 502, 247, 5, 5000)
        await backend.set_battery_limits(6000, 1200)
        return backend.client.writes

    assert asyncio.run(run()) == [(45565, 5000, 247), (45566, 1200, 247)]


def test_dry_run_clamps_but_skips_modbus_writes():
    modbus = import_modbus_backend()

    async def run():
        backend = modbus.ModbusBackend("127.0.0.1", 502, 247, 5, 5000, dry_run=True)
        await backend.set_battery_limits(100, 200)
        return backend.client

    assert asyncio.run(run()) is None


def test_read_status_reads_only_current_limit_registers_for_debug():
    modbus = import_modbus_backend()

    async def run():
        backend = modbus.ModbusBackend("127.0.0.1", 502, 247, 5, 5000)
        return await backend.read_status()

    status = asyncio.run(run())
    assert status == {"charge_limit_w": 0, "discharge_limit_w": 0}


def test_modbus_adapter_skips_unchanged_target_and_counts_reason():
    modbus = import_modbus_backend()

    async def run():
        backend = modbus.ModbusBackend(
            "127.0.0.1",
            502,
            247,
            5,
            5000,
            min_write_interval_s=0,
            post_write_feedback_settle_s=0,
        )
        first = await backend.set_battery_limits(1000, 0, state_changed=True)
        second = await backend.set_battery_limits(1000, 0, state_changed=True)
        return first, second, backend.client.writes, backend.metrics

    first, second, writes, metrics = asyncio.run(run())
    assert first is True
    assert second is False
    assert writes == [(45565, 1000, 247), (45566, 0, 247)]
    assert metrics.modbus_write_skipped_total == 1
    assert metrics.skipped_by_reason["unchanged target"] == 1


def test_modbus_adapter_enforces_min_write_interval():
    modbus = import_modbus_backend()

    async def run():
        backend = modbus.ModbusBackend(
            "127.0.0.1",
            502,
            247,
            5,
            5000,
            min_write_interval_s=10,
            post_write_feedback_settle_s=0,
        )
        await backend.set_battery_limits(1000, 0, state_changed=True)
        second = await backend.set_battery_limits(2500, 0, state_changed=True)
        return second, backend.client.writes, backend.metrics

    second, writes, metrics = asyncio.run(run())
    assert second is False
    assert writes == [(45565, 1000, 247), (45566, 0, 247)]
    assert metrics.skipped_by_reason["write interval not elapsed"] == 1
