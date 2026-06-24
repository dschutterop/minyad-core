import asyncio
import sys
from pathlib import Path

HOST_SERVICES = Path(__file__).resolve().parents[1] / "host-services"
if str(HOST_SERVICES) not in sys.path:
    sys.path.insert(0, str(HOST_SERVICES))

from backends import InverterState
from backends.composite_goodwe_backend import GoodWeCompositeBackend


def state(**overrides):
    values = dict(
        battery_soc=None,
        battery_soh=None,
        battery_power_w=None,
        battery_voltage_v=None,
        battery_temperature_c=None,
        battery_mode=None,
        inverter_temperature_c=None,
        grid_power_w=None,
    )
    values.update(overrides)
    return InverterState(**values)


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.limits = []

    async def read_state(self):
        if self.error:
            raise self.error
        return self.result

    async def set_battery_limits(self, charge_limit_w, discharge_limit_w):
        self.limits.append((charge_limit_w, discharge_limit_w))


def read(backend):
    return asyncio.run(backend.read_state())


def test_modbus_and_api_both_available_prefers_field_specific_sources():
    backend = GoodWeCompositeBackend(
        FakeClient(state(battery_power_w=100, battery_voltage_v=52.1, battery_mode="charge", battery_soc=1)),
        FakeClient(state(battery_soc=80, battery_soh=97, battery_temperature_c=24.5, battery_power_w=999)),
    )

    telemetry = read(backend)

    assert telemetry.battery_voltage_v == 52.1
    assert telemetry.battery_power_w == 100
    assert telemetry.battery_mode == "charge"
    assert telemetry.battery_soc == 80
    assert telemetry.battery_soh == 97
    assert telemetry.battery_temperature_c == 24.5
    assert telemetry.field_sources["battery_voltage_v"] == "modbus"
    assert telemetry.field_sources["battery_soc"] == "api"


def test_only_modbus_available_supports_partial_control_telemetry():
    telemetry = read(GoodWeCompositeBackend(FakeClient(state(battery_power_w=-120, battery_voltage_v=51.9, battery_mode="discharge")), None))

    assert telemetry.battery_power_w == -120
    assert telemetry.battery_voltage_v == 51.9
    assert telemetry.battery_soc is None
    assert telemetry.api_error == "disabled"


def test_only_api_available_keeps_api_telemetry_but_marks_modbus_disabled():
    telemetry = read(GoodWeCompositeBackend(None, FakeClient(state(battery_soc=72, battery_soh=99, battery_temperature_c=22.0))))

    assert telemetry.battery_soc == 72
    assert telemetry.battery_voltage_v is None
    assert telemetry.modbus_error == "disabled"


def test_api_fails_modbus_works():
    telemetry = read(GoodWeCompositeBackend(FakeClient(state(battery_voltage_v=50.0, battery_power_w=40)), FakeClient(error=RuntimeError("api down"))))

    assert telemetry.battery_voltage_v == 50.0
    assert telemetry.api_error == "api down"
    assert telemetry.modbus_available is True


def test_modbus_fails_api_works_degraded():
    telemetry = read(GoodWeCompositeBackend(FakeClient(error=ConnectionError("modbus down")), FakeClient(state(battery_soc=55, battery_temperature_c=21.0))))

    assert telemetry.battery_soc == 55
    assert telemetry.battery_voltage_v is None
    assert telemetry.modbus_error == "modbus down"
    assert telemetry.api_available is True


def test_both_fail_raises():
    try:
        read(GoodWeCompositeBackend(FakeClient(error=ConnectionError("modbus down")), FakeClient(error=RuntimeError("api down"))))
    except RuntimeError as exc:
        assert "GoodWe telemetry unavailable" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_partial_telemetry_merge_uses_fallback_only_when_preferred_missing():
    telemetry = GoodWeCompositeBackend.merge_telemetry(
        state(battery_voltage_v=None, battery_power_w=12),
        state(battery_voltage_v=49.5, battery_soc=66),
    )

    assert telemetry.battery_power_w == 12
    assert telemetry.field_sources["battery_power_w"] == "modbus"
    assert telemetry.battery_voltage_v is None
    assert telemetry.field_sources["battery_voltage_v"] == "unavailable"
    assert telemetry.battery_soc == 66


def test_set_limits_works_only_via_modbus():
    modbus = FakeClient(state())
    backend = GoodWeCompositeBackend(modbus, FakeClient(state()))
    asyncio.run(backend.set_battery_limits(1000, 2000))
    assert modbus.limits == [(1000, 2000)]

    try:
        asyncio.run(GoodWeCompositeBackend(None, FakeClient(state())).set_battery_limits(1, 2))
    except RuntimeError as exc:
        assert "Modbus actuator disabled" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
