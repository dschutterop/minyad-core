"""GoodWe backend composition: API telemetry, Modbus limit actuator only."""

from __future__ import annotations

import logging
from .base import BatteryTelemetry, InverterBackend, InverterState

logger = logging.getLogger("goodwe_bridge")


class GoodWeCompositeBackend:
    """Use GoodWe API as primary telemetry and Modbus only as the limit actuator.

    Live RS485 tests proved only charge/discharge limit writes on 45565/45566.
    475xx EMS force registers are not available on this inverter, so Modbus
    limits are ceilings, not active charge/discharge setpoints.
    """

    def __init__(self, modbus_client: InverterBackend | None, api_client: InverterBackend | None) -> None:
        self.modbus_client = modbus_client
        self.api_client = api_client

    async def read_status(self) -> BatteryTelemetry:
        return await self.read_state()

    async def read_state(self) -> BatteryTelemetry:
        api_state, api_error = await self._read_optional("api", self.api_client)
        if api_state is None:
            logger.warning("[api] GoodWe API telemetry degraded; values unknown: %s", api_error)
            return BatteryTelemetry(
                battery_soc=None,
                battery_soh=None,
                battery_power_w=None,
                battery_voltage_v=None,
                battery_temperature_c=None,
                battery_mode=None,
                inverter_temperature_c=None,
                grid_power_w=None,
                field_sources={
                    "battery_soc": "unavailable",
                    "battery_soh": "unavailable",
                    "battery_power_w": "unavailable",
                    "battery_voltage_v": "unavailable",
                    "battery_temperature_c": "unavailable",
                    "battery_mode": "unavailable",
                    "inverter_temperature_c": "unavailable",
                    "grid_power_w": "unavailable",
                },
                modbus_available=self.modbus_client is not None,
                api_available=False,
                modbus_error=None if self.modbus_client is not None else "disabled",
                api_error=api_error,
            )
        telemetry = self.merge_telemetry(None, api_state, modbus_error=None if self.modbus_client is not None else "disabled", api_error=api_error)
        logger.info("[api] GoodWe telemetry success sources=%s", telemetry.field_sources)
        return telemetry

    async def _read_optional(self, name: str, client: InverterBackend | None) -> tuple[InverterState | None, str | None]:
        if client is None:
            return None, "disabled"
        try:
            return await client.read_state(), None
        except Exception as exc:
            logger.warning("[%s] GoodWe %s read failed: %s", name, name, exc, exc_info=True)
            return None, str(exc)

    @staticmethod
    def merge_telemetry(
        modbus: InverterState | None,
        api: InverterState | None,
        *,
        modbus_error: str | None = None,
        api_error: str | None = None,
    ) -> BatteryTelemetry:
        # API is the primary and only normal telemetry source. The modbus
        # argument is accepted for backward-compatible tests/callers but is not
        # used as fallback telemetry. P1 remains the decision source outside this backend.
        del modbus
        fields = (
            "battery_soc",
            "battery_soh",
            "battery_power_w",
            "battery_voltage_v",
            "battery_temperature_c",
            "battery_mode",
            "inverter_temperature_c",
            "grid_power_w",
        )
        sources = {field: ("api" if api is not None and getattr(api, field) is not None else "unavailable") for field in fields}
        return BatteryTelemetry(
            battery_soc=None if api is None else api.battery_soc,
            battery_soh=None if api is None else api.battery_soh,
            battery_power_w=None if api is None else api.battery_power_w,
            battery_voltage_v=None if api is None else api.battery_voltage_v,
            battery_temperature_c=None if api is None else api.battery_temperature_c,
            battery_mode=None if api is None else api.battery_mode,
            inverter_temperature_c=None if api is None else api.inverter_temperature_c,
            grid_power_w=None if api is None else api.grid_power_w,
            field_sources=sources,
            modbus_available=modbus_error is None,
            api_available=api is not None,
            modbus_error=modbus_error,
            api_error=api_error,
        )

    async def set_battery_limits(self, charge_limit_w: int, discharge_limit_w: int, *, state_changed: bool = False) -> bool | None:
        if self.modbus_client is None:
            raise RuntimeError("GoodWe Modbus actuator disabled; battery limit writes are unavailable")
        return await self.modbus_client.set_battery_limits(charge_limit_w, discharge_limit_w, state_changed=state_changed)

    async def set_charge(self, watts: int) -> None:
        await self.set_battery_limits(watts, 0)

    async def set_discharge(self, watts: int) -> None:
        await self.set_battery_limits(0, watts)
