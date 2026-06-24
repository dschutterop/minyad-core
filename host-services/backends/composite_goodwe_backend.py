"""Dual-protocol GoodWe backend that composes Modbus and GoodWe API data."""

from __future__ import annotations

import logging
from .base import BatteryTelemetry, InverterBackend, InverterState

logger = logging.getLogger("goodwe_bridge")


class GoodWeCompositeBackend:
    """Merge GoodWe Modbus and API telemetry while keeping Modbus as truth for control fields."""

    def __init__(self, modbus_client: InverterBackend | None, api_client: InverterBackend | None) -> None:
        self.modbus_client = modbus_client
        self.api_client = api_client

    async def read_status(self) -> BatteryTelemetry:
        return await self.read_state()

    async def read_state(self) -> BatteryTelemetry:
        modbus_state, modbus_error = await self._read_optional("modbus", self.modbus_client)
        api_state, api_error = await self._read_optional("api", self.api_client)
        if modbus_state is None and api_state is None:
            raise RuntimeError(f"GoodWe telemetry unavailable: modbus={modbus_error}; api={api_error}")
        telemetry = self.merge_telemetry(modbus_state, api_state, modbus_error=modbus_error, api_error=api_error)
        logger.info(
            "[modbus|api] GoodWe telemetry merged sources=%s modbus_available=%s api_available=%s modbus_error=%s api_error=%s",
            telemetry.field_sources,
            telemetry.modbus_available,
            telemetry.api_available,
            telemetry.modbus_error,
            telemetry.api_error,
        )
        if modbus_error:
            logger.warning("[modbus] GoodWe Modbus telemetry degraded: %s", modbus_error)
        if api_error:
            logger.info("[api] GoodWe API telemetry unavailable; continuing with Modbus/control data: %s", api_error)
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
        sources: dict[str, str] = {}

        def pick(field: str, preferred: InverterState | None, preferred_name: str, fallback: InverterState | None, fallback_name: str):
            value = getattr(preferred, field) if preferred is not None else None
            if value is not None:
                sources[field] = preferred_name
                return value
            value = getattr(fallback, field) if fallback is not None else None
            if value is not None:
                sources[field] = fallback_name
                return value
            sources[field] = "unavailable"
            return None

        return BatteryTelemetry(
            battery_soc=pick("battery_soc", api, "api", modbus, "modbus"),
            battery_soh=pick("battery_soh", api, "api", modbus, "modbus"),
            battery_power_w=pick("battery_power_w", modbus, "modbus", None, "unavailable"),
            battery_voltage_v=pick("battery_voltage_v", modbus, "modbus", None, "unavailable"),
            battery_temperature_c=pick("battery_temperature_c", api, "api", modbus, "modbus"),
            battery_mode=pick("battery_mode", modbus, "modbus", None, "unavailable"),
            inverter_temperature_c=pick("inverter_temperature_c", api, "api", modbus, "modbus"),
            grid_power_w=pick("grid_power_w", api, "api", modbus, "modbus"),
            field_sources=sources,
            modbus_available=modbus is not None,
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
