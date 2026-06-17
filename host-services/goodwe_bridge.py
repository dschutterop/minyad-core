#!/usr/bin/env python3
"""Host-side GoodWe inverter to MQTT bridge for Minyad VPP."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import goodwe
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

LOGGER_NAME = "goodwe_bridge"
logger = logging.getLogger(LOGGER_NAME)

MQTT_TOPIC_SETPOINT_W = "minyad/control/setpoint_w"
MQTT_TOPIC_COMMAND = "minyad/control/command"
MQTT_TOPIC_STATUS = "minyad/bridge/status"
MQTT_TOPIC_LAST_SEEN = "minyad/bridge/last_seen"

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"

WORK_MODE_ECO = 3
CLIENT_ID = "goodwe-bridge"


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True)
class Config:
    inverter_ip: str
    mqtt_host: str
    mqtt_port: int
    poll_interval: int
    max_charge_a: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        inverter_ip = os.getenv("INVERTER_IP")
        mqtt_host = os.getenv("MQTT_HOST")
        if not inverter_ip:
            raise ValueError("INVERTER_IP is required")
        if not mqtt_host:
            raise ValueError("MQTT_HOST is required")

        max_charge_a = _get_env_int("MAX_CHARGE_A", 30)
        return cls(
            inverter_ip=inverter_ip,
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            poll_interval=_get_env_int("POLL_INTERVAL", 30),
            max_charge_a=min(max_charge_a, 30),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoodWeBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stopped = False
        self.last_status: str | None = None
        self.shutdown_event = asyncio.Event()
        self.mqtt_client = mqtt.Client(
            client_id=CLIENT_ID,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.will_set(MQTT_TOPIC_STATUS, STATUS_OFFLINE, retain=True)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

    async def get_inverter(self, retries: int = 5, delay: int = 3) -> Any:
        for attempt in range(retries):
            try:
                return await goodwe.connect(
                    self.config.inverter_ip,
                    family="ES",
                )
            except goodwe.exceptions.InverterError as e:
                logger.warning("Connect attempt %s/%s failed: %s", attempt + 1, retries, e)
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
        raise RuntimeError(f"Inverter unreachable after {retries} attempts")

    def publish(self, topic: str, payload: object, retain: bool = True) -> None:
        self.mqtt_client.publish(topic, str(payload), retain=retain)

    def publish_status(self, status: str) -> None:
        self.publish(MQTT_TOPIC_STATUS, status, retain=True)
        if status != self.last_status:
            logger.info("Bridge status transition: %s -> %s", self.last_status, status)
            self.last_status = status

    def on_connect(self, client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        if rc == 0:
            logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
            client.subscribe([(MQTT_TOPIC_SETPOINT_W, 1), (MQTT_TOPIC_COMMAND, 1)])
        else:
            logger.error("MQTT connection failed with rc=%s", rc)

    def on_disconnect(self, _client: mqtt.Client, _userdata: Any, rc: int) -> None:
        logger.warning("MQTT disconnected with rc=%s", rc)
        if rc == 0:
            self.publish_status(STATUS_OFFLINE)

    def on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if self.loop is None:
            logger.warning("Ignoring MQTT message before event loop is ready")
            return

        payload = message.payload.decode("utf-8", errors="replace").strip()
        if message.topic == MQTT_TOPIC_SETPOINT_W:
            try:
                setpoint_w = int(payload)
            except ValueError:
                logger.warning("Ignoring invalid setpoint_w payload: %r", payload)
                return
            asyncio.run_coroutine_threadsafe(self.handle_setpoint(setpoint_w), self.loop)
        elif message.topic == MQTT_TOPIC_COMMAND:
            asyncio.run_coroutine_threadsafe(self.handle_command(payload.lower()), self.loop)

    def watts_to_amps(self, watts: int, vbattery1: float) -> int:
        amps = round(watts / vbattery1)
        return max(0, min(self.config.max_charge_a, amps))

    async def write_charge_current(
        self,
        inv: Any,
        amps: int,
        *,
        setpoint_w: int | None,
        vbattery1: float,
    ) -> None:
        safe_amps = max(0, min(self.config.max_charge_a, int(amps)))
        await inv.write_setting("work_mode", WORK_MODE_ECO)
        await inv.write_setting("charge_i", safe_amps)
        logger.info(
            "Inverter write timestamp=%s setpoint_w=%s amps=%s vbattery1=%.3f",
            utc_now_iso(),
            setpoint_w,
            safe_amps,
            vbattery1,
        )

    async def handle_setpoint(self, setpoint_w: int) -> None:
        if self.stopped:
            logger.warning("Ignoring setpoint_w=%s because bridge is stopped", setpoint_w)
            return

        try:
            inv = await self.get_inverter()
            data = await inv.read_runtime_data()
            vbattery1 = float(data["vbattery1"])
            if vbattery1 <= 0:
                raise ValueError(f"Invalid live battery voltage: {vbattery1}")
            amps = self.watts_to_amps(setpoint_w, vbattery1)
            await self.write_charge_current(inv, amps, setpoint_w=setpoint_w, vbattery1=vbattery1)
        except Exception:
            logger.exception("Failed to handle setpoint_w=%s", setpoint_w)
            self.publish_status(STATUS_ERROR)

    async def handle_command(self, command: str) -> None:
        if command == "stop":
            self.stopped = True
            try:
                inv = await self.get_inverter()
                data = await inv.read_runtime_data()
                vbattery1 = float(data["vbattery1"])
                await self.write_charge_current(inv, 0, setpoint_w=0, vbattery1=vbattery1)
            except Exception:
                logger.exception("Failed to stop charging")
                self.publish_status(STATUS_ERROR)
        elif command == "resume":
            self.stopped = False
            logger.info("Resumed normal setpoint handling")
        else:
            logger.warning("Ignoring unknown command: %r", command)

    async def poll_once(self) -> None:
        inv = await self.get_inverter()
        data = await inv.read_runtime_data()
        charge_i = await inv.read_setting("charge_i")

        values = {
            "minyad/battery/soc": int(data["battery_soc"]),
            "minyad/battery/soh": int(data["battery_soh"]),
            "minyad/battery/power_w": int(data["pbattery1"]),
            "minyad/battery/voltage": float(data["vbattery1"]),
            "minyad/battery/mode": int(data["battery_mode"]),
            "minyad/battery/mode_label": str(data["battery_mode_label"]),
            "minyad/battery/charge_i": int(charge_i),
        }
        for topic, value in values.items():
            self.publish(topic, value, retain=True)
        self.publish_status(STATUS_ONLINE)
        self.publish(MQTT_TOPIC_LAST_SEEN, utc_now_iso(), retain=True)
        logger.info(
            "Poll timestamp=%s soc=%s power_w=%s charge_i=%s",
            utc_now_iso(),
            values["minyad/battery/soc"],
            values["minyad/battery/power_w"],
            values["minyad/battery/charge_i"],
        )

    async def polling_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                await self.poll_once()
            except Exception as exc:
                self.publish_status(STATUS_ERROR)
                logger.warning("Polling failed: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=self.config.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.mqtt_client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()
        await self.polling_loop()
        self.publish_status(STATUS_OFFLINE)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    bridge = GoodWeBridge(config)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
