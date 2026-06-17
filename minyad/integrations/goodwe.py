import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from minyad.common.config import AppConfig
from minyad.common.retry import with_backoff

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatteryState:
    soc_pct: float | None
    charge_w: int
    discharge_w: int
    mode: str
    grid_feed_w: int | None = None
    raw: dict[str, Any] | None = None


class GoodWeClient(ABC):
    @abstractmethod
    def read_state(self) -> BatteryState: ...

    @abstractmethod
    def read_runtime_data(self) -> dict[str, Any]: ...

    @abstractmethod
    def set_charge_power(self, watts: int) -> None: ...

    @abstractmethod
    def set_discharge_power(self, watts: int) -> None: ...

    @abstractmethod
    def set_idle(self) -> None: ...


class LocalGoodWeClient(GoodWeClient):
    """GoodWe local LAN client using the community `goodwe` Python library.

    The library exposes broad inverter telemetry reliably. Control-register support varies by
    firmware, so write methods are isolated here and can be replaced with site-specific register
    writes without affecting the control loop.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._inverter: Any | None = None

    async def _get_inverter(self) -> Any:
        import goodwe

        if self._inverter is None:
            self._inverter = await goodwe.connect(self.config.goodwe_host)
        return self._inverter

    async def _read_runtime_data(self) -> dict[str, Any]:
        inverter = await self._get_inverter()
        return await inverter.read_runtime_data()

    def read_runtime_data(self) -> dict[str, Any]:
        return with_backoff(
            lambda: asyncio.run(self._read_runtime_data()),
            label="goodwe runtime data",
        )

    def read_state(self) -> BatteryState:
        def call() -> BatteryState:
            data = self.read_runtime_data()
            soc = data.get("battery_soc") or data.get("soc") or data.get("battery_state_of_charge")
            battery_power = int(data.get("battery_power") or data.get("pbattery1") or 0)
            charge_w = abs(battery_power) if battery_power < 0 else 0
            discharge_w = battery_power if battery_power > 0 else 0
            mode = "charging" if charge_w else "discharging" if discharge_w else "idle"
            grid_feed = data.get("grid_power") or data.get("meter_active_power_total")
            return BatteryState(
                soc_pct=float(soc) if soc is not None else None,
                charge_w=charge_w,
                discharge_w=discharge_w,
                mode=mode,
                grid_feed_w=int(grid_feed) if grid_feed is not None else None,
                raw=data,
            )

        return with_backoff(call, label="goodwe runtime data")

    def set_charge_power(self, watts: int) -> None:
        self._log_pending_control("charge", watts)

    def set_discharge_power(self, watts: int) -> None:
        self._log_pending_control("discharge", watts)

    def set_idle(self) -> None:
        self._log_pending_control("idle", 0)

    def _log_pending_control(self, action: str, watts: int) -> None:
        LOG.warning(
            "GoodWe %s target %sW requested. Configure firmware-specific write registers in LocalGoodWeClient for active control.",
            action,
            watts,
        )


class ModbusGoodWeClient(GoodWeClient):
    def __init__(self, config: AppConfig):
        self.config = config

    def read_runtime_data(self) -> dict[str, Any]:
        raise NotImplementedError("Modbus/RS485 fallback is scaffolded; configure site-specific registers.")

    def read_state(self) -> BatteryState:
        raise NotImplementedError("Modbus/RS485 fallback is scaffolded; configure site-specific registers.")

    def set_charge_power(self, watts: int) -> None:
        raise NotImplementedError("Modbus/RS485 fallback is scaffolded; configure site-specific registers.")

    def set_discharge_power(self, watts: int) -> None:
        raise NotImplementedError("Modbus/RS485 fallback is scaffolded; configure site-specific registers.")

    def set_idle(self) -> None:
        raise NotImplementedError("Modbus/RS485 fallback is scaffolded; configure site-specific registers.")


class FallbackGoodWeClient(GoodWeClient):
    def __init__(self, primary: GoodWeClient, fallback: GoodWeClient):
        self.primary = primary
        self.fallback = fallback

    def read_runtime_data(self) -> dict[str, Any]:
        try:
            return self.primary.read_runtime_data()
        except Exception as exc:  # noqa: BLE001 - fallback boundary
            LOG.warning("Primary GoodWe runtime data failed, trying Modbus fallback: %s", exc)
            return self.fallback.read_runtime_data()

    def read_state(self) -> BatteryState:
        try:
            return self.primary.read_state()
        except Exception as exc:  # noqa: BLE001 - fallback boundary
            LOG.warning("Primary GoodWe client failed, trying Modbus fallback: %s", exc)
            return self.fallback.read_state()

    def set_charge_power(self, watts: int) -> None:
        try:
            self.primary.set_charge_power(watts)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Primary GoodWe control failed, trying fallback: %s", exc)
            self.fallback.set_charge_power(watts)

    def set_discharge_power(self, watts: int) -> None:
        try:
            self.primary.set_discharge_power(watts)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Primary GoodWe control failed, trying fallback: %s", exc)
            self.fallback.set_discharge_power(watts)

    def set_idle(self) -> None:
        try:
            self.primary.set_idle()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Primary GoodWe control failed, trying fallback: %s", exc)
            self.fallback.set_idle()


def build_goodwe_client(config: AppConfig) -> GoodWeClient:
    return FallbackGoodWeClient(LocalGoodWeClient(config), ModbusGoodWeClient(config))
