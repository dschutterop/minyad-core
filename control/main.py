"""Minyad battery control service."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import text

from hysteresis import HysteresisController, OverrideMode
from shared.db import AsyncSessionLocal
from shared.mqtt_client import MinyadMqttClient
from state import ControlState

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

STATUS_PREFIX = "battery.status."
DEFAULT_SETPOINT_W = 0
BRIDGE_OFFLINE_STATUSES = {"offline", "error"}
BATTERY_TOPIC_TYPES = {
    "soc": int,
    "soh": int,
    "power_w": int,
    "voltage": float,
    "mode": int,
    "mode_label": str,
    "charge_i": int,
}


async def load_settings() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
        rows = {row.key.removeprefix("battery."): row.value for row in result}
    int_keys = {"start_w", "stop_w", "start_duration", "stop_duration", "cooldown", "max_charge_w", "max_charge_a", "max_discharge_w"}
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
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.reload_settings()
        await self.apply_override(await load_override())
        self.mqtt.start()
        self.mqtt.subscribe("minyad/dsmr/net_power_w", self._on_mqtt)
        self.mqtt.subscribe("minyad/battery/+", self._on_mqtt)
        self.mqtt.subscribe("minyad/bridge/+", self._on_mqtt)
        self.mqtt.subscribe("minyad/control/override", self._on_mqtt)
        await self.publish_state_loop()

    async def reload_settings(self) -> None:
        self.settings = await load_settings()
        self.controller = HysteresisController(
            start_w=int(self.settings["start_w"]),
            stop_w=int(self.settings["stop_w"]),
            start_duration=int(self.settings["start_duration"]),
            stop_duration=int(self.settings["stop_duration"]),
            cooldown=int(self.settings["cooldown"]),
            on_start=self._schedule_start_charging,
            on_stop=self._schedule_stop_charging,
        )
        LOGGER.info("Battery control settings loaded")

    def _schedule_start_charging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.start_charging(), self.loop)

    def _schedule_stop_charging(self) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        asyncio.run_coroutine_threadsafe(self.stop_charging(), self.loop)

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        if self.loop is None:
            raise RuntimeError("control app event loop is not initialized")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.handle_message(topic, payload))

    async def handle_message(self, topic: str, payload: bytes) -> None:
        decoded = payload.decode()
        if topic == "minyad/dsmr/net_power_w":
            surplus = int(decoded)
            if self.controller and self.bridge_is_available:
                state = self.controller.tick(surplus)
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
        await store_status(**{measurement: value_type(payload)})

    async def handle_bridge_topic(self, topic: str, payload: str) -> None:
        measurement = topic.removeprefix("minyad/bridge/")
        if measurement == "status":
            await self.handle_bridge_status(payload.strip().lower())
            return
        if measurement == "last_seen":
            await store_status(bridge_last_seen=payload.strip())
            return
        LOGGER.debug("Ignoring unsupported bridge topic %s", topic)

    @property
    def bridge_is_available(self) -> bool:
        return self.bridge_status not in BRIDGE_OFFLINE_STATUSES

    async def handle_bridge_status(self, status: str) -> None:
        self.bridge_status = status
        await store_status(bridge_status=status, available=self.bridge_is_available)
        if status in BRIDGE_OFFLINE_STATUSES:
            LOGGER.warning("GoodWe bridge is %s; stopping control and suppressing setpoints", status)
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

    async def stop_charging(self) -> None:
        self.setpoint_w = 0
        self.mqtt.publish_measurement("control", "command", "stop")
        if self.bridge_is_available:
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
        self.mqtt.publish_measurement("control", "setpoint_w", self.setpoint_w)

    async def publish_discharge_setpoint(self, watts: int) -> None:
        if not self.bridge_is_available:
            LOGGER.warning("GoodWe bridge is %s; discharge setpoint %sW not published", self.bridge_status, watts)
            self.setpoint_w = 0
            return
        max_discharge_w = int(self.settings.get("max_discharge_w", 5000))
        self.setpoint_w = max(0, min(watts, max_discharge_w))
        self.mqtt.publish_measurement("control", "command", "discharge" if self.setpoint_w else "stop")
        self.mqtt.publish_measurement("control", "setpoint_w", 0)
        self.mqtt.publish_measurement("control", "discharge_w", self.setpoint_w)

    async def publish_state_loop(self) -> None:
        while True:
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
