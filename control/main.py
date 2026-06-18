"""Minyad battery control service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from hysteresis import HysteresisController, OverrideMode
from shared.db import AsyncSessionLocal
from shared.mqtt_client import MinyadMqttClient
from state import ControlState

logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
LOGGER = logging.getLogger(__name__)

STATUS_PREFIX = "battery.status."
DEFAULT_SETPOINT_W = 0
BRIDGE_OFFLINE_STATUSES = {"offline", "error"}
BRIDGE_LAST_SEEN_STALE_SECONDS = int(os.getenv("BRIDGE_LAST_SEEN_STALE_SECONDS", "60"))
BATTERY_TOPIC_TYPES = {
    "soc": int,
    "soh": int,
    "power_w": int,
    "voltage": float,
    "voltage_v": float,
    "temperature_c": float,
    "mode": str,
    "mode_label": str,
    "charge_i": int,
}


async def load_settings() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
        rows = {row.key.removeprefix("battery."): row.value for row in result}
    int_keys = {
        "start_w",
        "stop_w",
        "discharge_start_w",
        "discharge_stop_w",
        "start_duration",
        "stop_duration",
        "cooldown",
        "max_charge_w",
        "max_charge_a",
        "max_discharge_w",
    }
    return {key: int(value) if key in int_keys else value for key, value in rows.items() if not key.startswith("status.")}


async def store_status(**values: Any) -> None:
    async with AsyncSessionLocal() as session:
        for key, value in values.items():
            await session.execute(
                text("""
                    insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                    on conflict (key) do update set value=:value, updated_at=now()
                """),
                {"key": f"{STATUS_PREFIX}{key}", "value": str(value)},
            )
        await session.commit()


async def load_override() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select mode, watts, duration_seconds from battery_override where id=1"))
        row = result.first()
        if row is None:
            return {"mode": "none"}
        return {"mode": row.mode, "watts": row.watts, "duration_seconds": row.duration_seconds}


class ControlApp:
    def __init__(self) -> None:
        self.mqtt = MinyadMqttClient("minyad-control")
        self.controller: HysteresisController | None = None
        self.settings: dict[str, Any] = {}
        self.setpoint_w = DEFAULT_SETPOINT_W
        self.bridge_status = "offline"
        self.bridge_last_seen: datetime | None = None
        self.bridge_last_seen_raw: str | None = None
        self.bridge_last_seen_error: str | None = "missing bridge last_seen"
        self.bridge_health_event: asyncio.Event | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.bridge_health_event = asyncio.Event()
        await self.reload_settings()
        self.mqtt.subscribe("minyad/dsmr/net_power_w", self._on_mqtt)
        self.mqtt.subscribe("minyad/grid/net_power_w", self._on_mqtt)
        self.mqtt.subscribe("minyad/battery/+", self._on_mqtt)
        self.mqtt.subscribe("minyad/bridge/+", self._on_mqtt)
        self.mqtt.subscribe("minyad/control/override", self._on_mqtt)
        self.mqtt.start()
        await self.wait_for_initial_bridge_health()
        await self.apply_override(await load_override())
        await self.publish_state_loop()

    async def reload_settings(self) -> None:
        self.settings = await load_settings()
        self.controller = HysteresisController(
            start_w=int(self.settings["start_w"]),
            stop_w=int(self.settings["stop_w"]),
            discharge_start_w=int(self.settings["discharge_start_w"]),
            discharge_stop_w=int(self.settings["discharge_stop_w"]),
            start_duration=int(self.settings["start_duration"]),
            stop_duration=int(self.settings["stop_duration"]),
            cooldown=int(self.settings["cooldown"]),
            on_start=self._schedule_start_charging,
            on_stop=self._schedule_stop_charging,
            on_discharge_start=self._schedule_start_discharging,
            on_discharge_stop=self._schedule_stop_discharging,
        )
        LOGGER.info("Battery control settings loaded")

    async def wait_for_initial_bridge_health(self) -> None:
        """Give retained bridge health topics a chance to arrive before applying overrides."""
        if self.bridge_health_event is None:
            return
        timeout = float(os.getenv("BRIDGE_INITIAL_HEALTH_TIMEOUT_SECONDS", "5"))
        try:
            await asyncio.wait_for(self.bridge_health_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            LOGGER.warning(
                "Timed out waiting %.1fs for retained GoodWe bridge health; starting with status=%s",
                timeout,
                self.bridge_status,
            )

    def _schedule_start_charging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.start_charging(), self.loop)

    def _schedule_stop_charging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.stop_charging(), self.loop)

    def _schedule_start_discharging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.start_discharging(), self.loop)

    def _schedule_stop_discharging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.stop_discharging(), self.loop)

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.handle_message(topic, payload))

    async def handle_message(self, topic: str, payload: bytes) -> None:
        decoded = payload.decode()
        LOGGER.debug("MQTT message topic=%s payload=%r", topic, decoded)
        if topic in {"minyad/dsmr/net_power_w", "minyad/grid/net_power_w"}:
            grid_power_w = int(decoded)
            # DSMR/grid net power is positive for grid import and negative for export.
            # HysteresisController expects surplus-style samples: positive export/available
            # power starts charging, while negative import starts discharging.
            surplus_w = -grid_power_w
            if not self.controller:
                LOGGER.info("Skipping grid control sample topic=%s grid_power=%sW: controller not ready", topic, grid_power_w)
                return
            if not self.bridge_is_available:
                LOGGER.info(
                    "Skipping grid control sample topic=%s grid_power=%sW surplus=%sW: GoodWe bridge unavailable status=%s last_seen=%s error=%s",
                    topic,
                    grid_power_w,
                    surplus_w,
                    self.bridge_status,
                    self.bridge_last_seen_raw,
                    self.bridge_last_seen_error,
                )
                return
            previous_state = self.controller.state
            state = self.controller.tick(surplus_w)
            LOGGER.info(
                "Grid control sample topic=%s grid_power=%sW surplus=%sW state=%s%s",
                topic,
                grid_power_w,
                surplus_w,
                self.controller.state.value,
                " transitioned_from=" + previous_state.value if state else "",
            )
            if state:
                await self.publish_state(state)
            return
        if topic == "minyad/control/override":
            command = json.loads(decoded)
            if command.get("mode") == "reload_settings":
                await self.reload_settings()
            else:
                await self.apply_override(command)
            return
        if topic.startswith("minyad/bridge/"):
            await self.handle_bridge_topic(topic, decoded)
            return
        if topic.startswith("minyad/battery/"):
            await self.handle_battery_topic(topic, decoded)
            return

    async def handle_battery_topic(self, topic: str, payload: str) -> None:
        measurement = topic.removeprefix("minyad/battery/")
        value_type = BATTERY_TOPIC_TYPES.get(measurement)
        if value_type is None:
            LOGGER.debug("Ignoring unsupported battery topic %s", topic)
            return
        try:
            value = value_type(payload)
        except (TypeError, ValueError):
            LOGGER.warning("Ignoring invalid battery topic payload topic=%s payload=%r", topic, payload)
            return
        await store_status(**{measurement: value})

    async def handle_bridge_topic(self, topic: str, payload: str) -> None:
        measurement = topic.removeprefix("minyad/bridge/")
        if measurement == "status":
            await self.handle_bridge_status(payload.strip().lower())
            self._mark_bridge_health_seen()
            return
        if measurement == "last_seen":
            await self.handle_bridge_last_seen(payload.strip())
            self._mark_bridge_health_seen()
            return
        LOGGER.debug("Ignoring unsupported bridge topic %s", topic)

    def _mark_bridge_health_seen(self) -> None:
        if self.bridge_health_event is None:
            return
        # A retained status message is enough to prove the bridge status topic is flowing.
        # last_seen may arrive later, so do not keep startup blocked just because only
        # minyad/bridge/status has been delivered so far.
        if self.bridge_status not in {"offline"}:
            self.bridge_health_event.set()

    def parse_bridge_last_seen(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def bridge_last_seen_age_seconds(self) -> float | None:
        if self.bridge_last_seen is None:
            return None
        return (datetime.now(timezone.utc) - self.bridge_last_seen).total_seconds()

    @property
    def bridge_is_available(self) -> bool:
        if self.bridge_status in BRIDGE_OFFLINE_STATUSES:
            return False
        age = self.bridge_last_seen_age_seconds()
        if age is None:
            return True
        return age <= BRIDGE_LAST_SEEN_STALE_SECONDS

    async def handle_bridge_status(self, status: str) -> None:
        self.bridge_status = status
        LOGGER.info("GoodWe bridge status update: %s", status)
        await store_status(bridge_status=status, available=self.bridge_is_available)
        if status in BRIDGE_OFFLINE_STATUSES:
            LOGGER.warning("GoodWe bridge is %s; stopping control and suppressing setpoints", status)
            await self.mark_bridge_unavailable()

    async def handle_bridge_last_seen(self, value: str) -> None:
        self.bridge_last_seen_raw = value
        parsed = self.parse_bridge_last_seen(value)
        if parsed is None:
            self.bridge_last_seen = None
            self.bridge_last_seen_error = f"invalid bridge last_seen timestamp: {value!r}"
            LOGGER.warning(self.bridge_last_seen_error)
        else:
            self.bridge_last_seen = parsed
            age = self.bridge_last_seen_age_seconds()
            self.bridge_last_seen_error = None if age is not None and age <= BRIDGE_LAST_SEEN_STALE_SECONDS else "bridge last_seen is stale"
            LOGGER.info("GoodWe bridge heartbeat timestamp=%s age=%.1fs valid=%s", value, age or 0, self.bridge_last_seen_error is None)
        await store_status(bridge_last_seen=value, bridge_last_seen_valid=self.bridge_last_seen_error is None, bridge_last_seen_error=self.bridge_last_seen_error or "", available=self.bridge_is_available)
        if not self.bridge_is_available:
            await self.mark_bridge_unavailable()

    async def mark_bridge_unavailable(self) -> None:
        if self.setpoint_w != 0 or (self.controller and self.controller.state is not ControlState.IDLE):
            LOGGER.warning("GoodWe bridge unavailable (status=%s, last_seen=%s, error=%s); stopping control", self.bridge_status, self.bridge_last_seen_raw, self.bridge_last_seen_error)
        self.setpoint_w = 0
        self._force_controller_idle()
        self.mqtt.publish_measurement("control", "command", "stop")
        await self.publish_state(ControlState.IDLE, publish_setpoint=False)

    def _force_controller_idle(self) -> None:
        if self.controller is None:
            return
        with self.controller._lock:  # HysteresisController intentionally remains unchanged.
            self.controller._state = ControlState.IDLE
            self.controller._start_since = None
            self.controller._stop_since = None
            self.controller._cooldown_until = None

    async def apply_override(self, command: dict[str, Any]) -> None:
        if not self.controller:
            return
        mode = OverrideMode(command.get("mode", "none"))
        watts = int(command.get("watts") or 0)
        duration = command.get("duration_seconds")
        if mode is OverrideMode.NONE:
            self.controller.clear_override()
            self.setpoint_w = 0
        else:
            self.controller.set_override(mode, int(duration) if duration else None)
        if mode is OverrideMode.FORCE_ON:
            await self.publish_setpoint(watts)
        elif mode is OverrideMode.FORCE_DISCHARGE:
            await self.publish_discharge_setpoint(watts)
        elif mode in {OverrideMode.FORCE_OFF, OverrideMode.PAUSE}:
            await self.stop_charging()
        await self.publish_state(self.controller.state)

    async def start_charging(self) -> None:
        await self.publish_setpoint(int(self.settings["max_charge_w"]))

    async def start_discharging(self) -> None:
        await self.publish_discharge_setpoint(int(self.settings["max_discharge_w"]))

    async def stop_discharging(self) -> None:
        await self.stop_charging()

    async def stop_charging(self) -> None:
        self.setpoint_w = 0
        self.mqtt.publish_measurement("control", "command", "stop")
        if self.bridge_is_available:
            self.mqtt.publish_measurement("control", "charge_w", 0)
            self.mqtt.publish_measurement("control", "setpoint_w", 0)
            self.mqtt.publish_measurement("control", "discharge_w", 0)

    async def publish_setpoint(self, watts: int) -> None:
        if not self.bridge_is_available:
            LOGGER.warning("GoodWe bridge is %s; charge setpoint %sW not published", self.bridge_status, watts)
            self.setpoint_w = 0
            return
        self.setpoint_w = max(0, watts)
        self.mqtt.publish_measurement("control", "command", "resume" if self.setpoint_w else "stop")
        self.mqtt.publish_measurement("control", "discharge_w", 0)
        self.mqtt.publish_measurement("control", "charge_w", self.setpoint_w)
        self.mqtt.publish_measurement("control", "setpoint_w", self.setpoint_w)

    async def publish_discharge_setpoint(self, watts: int) -> None:
        if not self.bridge_is_available:
            LOGGER.warning("GoodWe bridge is %s; discharge setpoint %sW not published", self.bridge_status, watts)
            self.setpoint_w = 0
            return
        max_discharge_w = int(self.settings.get("max_discharge_w", 5000))
        self.setpoint_w = max(0, min(watts, max_discharge_w))
        self.mqtt.publish_measurement("control", "command", "discharge" if self.setpoint_w else "stop")
        self.mqtt.publish_measurement("control", "charge_w", 0)
        self.mqtt.publish_measurement("control", "setpoint_w", 0)
        self.mqtt.publish_measurement("control", "discharge_w", self.setpoint_w)

    async def publish_state_loop(self) -> None:
        while True:
            if self.bridge_last_seen is not None and not self.bridge_is_available and self.bridge_status not in BRIDGE_OFFLINE_STATUSES:
                self.bridge_last_seen_error = "bridge last_seen is stale"
                await store_status(bridge_last_seen_valid=False, bridge_last_seen_error=self.bridge_last_seen_error, available=False)
                await self.mark_bridge_unavailable()
            if self.controller:
                await self.publish_state(self.controller.state)
            await asyncio.sleep(10)

    async def publish_state(self, state: ControlState, *, publish_setpoint: bool = True) -> None:
        mode = self.controller.override_mode.value if self.controller else "none"
        self.mqtt.publish_measurement("control", "state", state.value)
        if publish_setpoint and self.bridge_is_available:
            self.mqtt.publish_measurement("control", "setpoint_w", self.setpoint_w)
        self.mqtt.publish_measurement("control", "override_mode", mode)
        await store_status(state=state.value, override_mode=mode, setpoint_w=self.setpoint_w)


async def run_control_app() -> None:
    app = ControlApp()
    await app.start()


def main() -> None:
    asyncio.run(run_control_app())


if __name__ == "__main__":
    main()
