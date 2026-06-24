import asyncio
import importlib
import sys
import types
from pathlib import Path


class FakeInverterError(Exception):
    pass


class FakeCommand:
    def __init__(self, command, response_type):
        self.command = command
        self.response_type = response_type


def install_goodwe_stub():
    fake_goodwe = types.ModuleType("goodwe")
    fake_goodwe.connect_calls = 0
    fake_goodwe.instances = []

    class FakeInverter:
        def __init__(self):
            self.commands = []
            self.runtime_reads = 0

        async def _read_from_socket(self, command):
            self.commands.append((command.command, command.response_type))

        async def read_runtime_data(self):
            self.runtime_reads += 1
            return {
                "battery_soc": 80,
                "battery_soh": 99,
                "pbattery1": 250,
                "vbattery1": 52.0,
                "battery_temperature": 24.0,
                "battery_mode": 1,
                "temperature": 31.0,
                "pgrid": 120,
            }

    async def connect(_host, family=None):
        fake_goodwe.connect_calls += 1
        inverter = FakeInverter()
        fake_goodwe.instances.append(inverter)
        return inverter

    fake_goodwe.connect = connect
    fake_goodwe.exceptions = types.SimpleNamespace(InverterError=FakeInverterError)

    protocol = types.ModuleType("goodwe.protocol")
    protocol.Aa55ProtocolCommand = FakeCommand

    sys.modules["goodwe"] = fake_goodwe
    sys.modules["goodwe.protocol"] = protocol
    return fake_goodwe


def import_backend_module():
    host_services = Path(__file__).resolve().parents[1] / "host-services"
    if str(host_services) not in sys.path:
        sys.path.insert(0, str(host_services))
    sys.modules.pop("backends.goodwe_backend", None)
    return importlib.import_module("backends.goodwe_backend")


def test_goodwe_backend_reuses_connection_for_sequential_requests():
    fake_goodwe = install_goodwe_stub()
    goodwe_backend = import_backend_module()

    async def run():
        backend = goodwe_backend.GoodWeBackend("192.0.2.10", 5000, min_request_interval_s=0)
        await backend.read_state()
        await backend.set_discharge(1000)
        await backend.set_charge(500)

    asyncio.run(run())

    assert fake_goodwe.connect_calls == 1
    assert len(fake_goodwe.instances) == 1
    assert fake_goodwe.instances[0].runtime_reads == 1
    assert fake_goodwe.instances[0].commands == [
        ("032c050000173b00", "03AC"),
        ("032d050000173b14", "03AD"),
        ("032c050000173b0a", "03AC"),
        ("032d050000173b00", "03AD"),
    ]
