import asyncio
import sys
from pathlib import Path

HOST_SERVICES = Path(__file__).resolve().parents[1] / "host-services"
if str(HOST_SERVICES) not in sys.path:
    sys.path.insert(0, str(HOST_SERVICES))

from backends import InverterState  # noqa: E402,I001 - must follow sys.path setup above
from backends.composite_goodwe_backend import GoodWeCompositeBackend  # noqa: E402 - must follow sys.path setup above


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

    async def set_battery_limits(self, charge_limit_w, discharge_limit_w, *, state_changed=False):
        self.limits.append((charge_limit_w, discharge_limit_w))
        self.state_changed = state_changed
        return True


def read(backend):
    return asyncio.run(backend.read_state())


def test_api_telemetry_success_is_source_of_truth_even_when_modbus_exists():
    backend = GoodWeCompositeBackend(
        FakeClient(state(battery_power_w=100, battery_voltage_v=52.1, battery_mode="charge", battery_soc=1)),
        FakeClient(state(battery_soc=80, battery_soh=97, battery_temperature_c=24.5, battery_power_w=999, battery_voltage_v=51.0, battery_mode="idle")),
    )

    telemetry = read(backend)

    assert telemetry.battery_voltage_v == 51.0
    assert telemetry.battery_power_w == 999
    assert telemetry.battery_mode == "idle"
    assert telemetry.battery_soc == 80
    assert telemetry.field_sources["battery_power_w"] == "api"
    assert telemetry.modbus_available is True


def test_api_telemetry_failure_returns_degraded_unknowns_without_modbus_fallback():
    telemetry = read(GoodWeCompositeBackend(FakeClient(state(battery_power_w=-120, battery_voltage_v=51.9)), FakeClient(error=RuntimeError("api down"))))

    assert telemetry.battery_power_w is None
    assert telemetry.battery_voltage_v is None
    assert telemetry.api_error == "api down"
    assert telemetry.modbus_available is True


def test_only_api_available_keeps_api_telemetry_but_marks_modbus_disabled():
    telemetry = read(GoodWeCompositeBackend(None, FakeClient(state(battery_soc=72, battery_soh=99, battery_temperature_c=22.0))))

    assert telemetry.battery_soc == 72
    assert telemetry.battery_voltage_v is None
    assert telemetry.modbus_error == "disabled"


def test_both_api_and_modbus_disabled_returns_degraded_telemetry():
    telemetry = read(GoodWeCompositeBackend(None, None))

    assert telemetry.battery_soc is None
    assert telemetry.api_error == "disabled"
    assert telemetry.modbus_error == "disabled"


def test_merge_telemetry_never_uses_modbus_as_fallback():
    telemetry = GoodWeCompositeBackend.merge_telemetry(
        state(battery_power_w=12),
        state(battery_voltage_v=49.5, battery_soc=66),
    )

    assert telemetry.battery_power_w is None
    assert telemetry.field_sources["battery_power_w"] == "unavailable"
    assert telemetry.battery_voltage_v == 49.5
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


def test_protocol_logs_include_api_source_prefix(caplog):
    backend = GoodWeCompositeBackend(FakeClient(error=ConnectionError("modbus down")), FakeClient(error=RuntimeError("api down")))

    read(backend)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("[api] GoodWe api read failed") for message in messages)
    assert any("API telemetry degraded" in message for message in messages)


def test_set_battery_limits_returns_modbus_write_result_and_passes_state_changed():
    modbus = FakeClient()
    result = asyncio.run(GoodWeCompositeBackend(modbus, None).set_battery_limits(1200, 0, state_changed=True))

    assert result is True
    assert modbus.limits == [(1200, 0)]
    assert modbus.state_changed is True
