"""Minyad battery control service."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import text

from hysteresis import HysteresisController, OverrideMode
from inverter import GoodWeInverter, InverterSettings
from shared.db import AsyncSessionLocal
from shared.mqtt_client import MinyadMqttClient
from state import ControlState

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

STATUS_PREFIX = "battery.status."
DEFAULT_SETPOINT_W = 0


async def load_settings() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
        rows = {row.key.removeprefix("battery."): row.value for row in result}
    int_keys = {"start_w", "stop_w", "start_duration", "stop_duration", "cooldown", "max_charge_w", "max_charge_a", "inverter_retries", "inverter_delay"}
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
        self.inverter: GoodWeInverter | None = None
        self.settings: dict[str, Any] = {}
        self.setpoint_w = DEFAULT_SETPOINT_W
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.reload_settings()
        await self.apply_override(await load_override())
        self.mqtt.start()
        self.mqtt.subscribe("minyad/dsmr/net_power_w", self._on_mqtt)
        self.mqtt.subscribe("minyad/control/override", self._on_mqtt)
        await asyncio.gather(self.poll_battery(), self.publish_state_loop())

    async def reload_settings(self) -> None:
        self.settings = await load_settings()
        self.inverter = GoodWeInverter(
            InverterSettings(
                inverter_ip=str(self.settings["inverter_ip"]),
                inverter_retries=int(self.settings["inverter_retries"]),
                inverter_delay=int(self.settings["inverter_delay"]),
                max_charge_a=min(30, int(self.settings["max_charge_a"])),
            )
        )
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
        if topic == "minyad/dsmr/net_power_w":
            surplus = int(payload.decode())
            if self.controller:
                state = self.controller.tick(surplus)
                if state:
                    await self.publish_state(state)
            return
        if topic == "minyad/control/override":
            command = json.loads(payload.decode())
            if command.get("mode") == "reload_settings":
                await self.reload_settings()
            else:
                await self.apply_override(command)

    async def apply_override(self, command: dict[str, Any]) -> None:
        if not self.controller or not self.inverter:
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
            await self.inverter.set_charge_power(watts)
            self.setpoint_w = watts
        elif mode is OverrideMode.FORCE_OFF:
            await self.inverter.stop_charging()
            self.setpoint_w = 0
        elif mode is OverrideMode.FORCE_DISCHARGE:
            await self.inverter.stop_charging()
            await self.inverter.set_discharge_power(watts)
            self.setpoint_w = -watts
        elif mode is OverrideMode.PAUSE:
            await self.inverter.stop_charging()
            self.setpoint_w = 0
        await self.publish_state(self.controller.state)

    async def start_charging(self) -> None:
        if self.inverter:
            self.setpoint_w = int(self.settings["max_charge_w"])
            await self.inverter.set_charge_power(self.setpoint_w)

    async def stop_charging(self) -> None:
        if self.inverter:
            await self.inverter.stop_charging()
            self.setpoint_w = 0

    async def poll_battery(self) -> None:
        while True:
            try:
                if self.inverter and self.controller:
                    status = await self.inverter.read_status()
                    status.update(state=self.controller.state.value, override_mode=self.controller.override_mode.value)
                    await store_status(**status)
                    self.mqtt.publish_measurement("battery", "soc", status["soc"])
                    self.mqtt.publish_measurement("battery", "power_w", status["power_w"])
                    self.mqtt.publish_measurement("battery", "voltage", status["voltage"])
            except Exception:
                LOGGER.exception("Battery poll failed")
            await asyncio.sleep(30)

    async def publish_state_loop(self) -> None:
        while True:
            if self.controller:
                await self.publish_state(self.controller.state)
            await asyncio.sleep(10)

    async def publish_state(self, state: ControlState) -> None:
        mode = self.controller.override_mode.value if self.controller else "none"
        self.mqtt.publish_measurement("control", "state", state.value)
        self.mqtt.publish_measurement("control", "setpoint_w", self.setpoint_w)
        self.mqtt.publish_measurement("control", "override_mode", mode)
        await store_status(state=state.value, override_mode=mode)


async def run_control_app() -> None:
    app = ControlApp()
    await app.start()


def main() -> None:
    asyncio.run(run_control_app())


if __name__ == "__main__":
    main()
