#!/usr/bin/env python3
"""Host-side inverter to MQTT bridge for Minyad VPP."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import psycopg2
from dotenv import load_dotenv

from backends import GoodWeBackend, InverterBackend, ModbusBackend

load_dotenv()

LOGGER_NAME = "goodwe_bridge"
logger = logging.getLogger(LOGGER_NAME)

MQTT_TOPIC_CHARGE_W = "minyad/control/charge_w"
MQTT_TOPIC_DISCHARGE_W = "minyad/control/discharge_w"
MQTT_TOPIC_CONTROL_STATE = "minyad/control/state"
BATTERY_POLL_INTERVAL_SETTING = "battery.inverter_poll_interval_s"
DEFAULT_POLL_INTERVAL_SECONDS = 120

MQTT_TOPIC_INVERTER_STATUS = "minyad/inverter/status"
MQTT_TOPIC_BRIDGE_STATUS = "minyad/bridge/status"
MQTT_TOPIC_BRIDGE_LAST_SEEN = "minyad/bridge/last_seen"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_OFFLINE = "offline"
STATUS_OK = "ok"
STATUS_UNREACHABLE = "unreachable"
STATUS_ERROR = "error"
CLIENT_ID = "goodwe-bridge"


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ValueError(f"{name} is required")
    return value.strip()


@dataclass(frozen=True)
class Config:
    inverter_backend: str
    goodwe_api_host: str
    inverter_max_w: int
    modbus_gw_ip: str
    modbus_gw_port: int
    modbus_slave_id: int
    modbus_timeout: float
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_pass: str | None
    poll_interval: int
    database_url: str | None
    max_charge_a: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not mqtt_host:
            raise ValueError("MQTT_BROKER is required")

        inverter_backend = os.getenv("INVERTER_BACKEND", "goodwe").lower()
        if inverter_backend not in {"modbus", "goodwe"}:
            raise ValueError("INVERTER_BACKEND must be 'modbus' or 'goodwe'")

        max_charge_a = _get_env_int("MAX_CHARGE_A", 30)
        return cls(
            inverter_backend=inverter_backend,
            goodwe_api_host=_get_required_env("GOODWE_API_HOST"),
            inverter_max_w=_get_env_int("INVERTER_MAX_W", _get_env_int("MAX_DISCHARGE_W", 5000)),
            modbus_gw_ip=_get_required_env("MODBUS_GW_IP"),
            modbus_gw_port=_get_env_int("MODBUS_GW_PORT", 502),
            modbus_slave_id=_get_env_int("MODBUS_SLAVE_ID", 247),
            modbus_timeout=_get_env_float("MODBUS_TIMEOUT", 5.0),
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            mqtt_user=os.getenv("MQTT_USER"),
            mqtt_pass=os.getenv("MQTT_PASS"),
            poll_interval=_get_env_int("POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS),
            database_url=os.getenv("DB_URL") or os.getenv("DATABASE_URL"),
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


def build_backend(config: Config) -> InverterBackend:
    if config.inverter_backend == "modbus":
        return ModbusBackend(
            host=config.modbus_gw_ip,
            port=config.modbus_gw_port,
            slave_id=config.modbus_slave_id,
            timeout=config.modbus_timeout,
            max_w=config.inverter_max_w,
        )
    if config.inverter_backend == "goodwe":
        return GoodWeBackend(config.goodwe_api_host, config.inverter_max_w)
    raise ValueError("INVERTER_BACKEND must be 'modbus' or 'goodwe'")


class GoodWeBridge:
    def __init__(self, config: Config, backend: InverterBackend) -> None:
        self.config = config
        self.backend = backend
        self.loop: asyncio.AbstractEventLoop | None = None
        self.shutdown_event = asyncio.Event()
        self.mqtt_client = mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)
        self.mqtt_client.will_set(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_OFFLINE, retain=True)
        if config.mqtt_user:
            self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_pass)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.control_state = "IDLE"
        self._immediate_poll_task: Future[None] | None = None

    def load_poll_interval(self) -> int:
        """Return the current inverter polling interval in seconds.

        The setting is loaded from PostgreSQL on every polling cycle so operators
        can slow down GoodWe telemetry without restarting the host-side bridge.
        MQTT command handling remains event-driven and is not delayed by this
        telemetry interval.
        """
        configured = self.config.poll_interval
        if not self.config.database_url:
            return configured
        try:
            with closing(psycopg2.connect(self.config.database_url)) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "select value from settings where key = %s and encrypted = false",
                        (BATTERY_POLL_INTERVAL_SETTING,),
                    )
                    row = cur.fetchone()
        except Exception as exc:
            logger.warning("Could not load %s; using %ss: %s", BATTERY_POLL_INTERVAL_SETTING, configured, exc)
            return configured
        if row is None:
            return configured
        try:
            interval = int(row[0])
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid %s=%r; using %ss", BATTERY_POLL_INTERVAL_SETTING, row[0], configured)
            return configured
        if interval < 1:
            logger.warning("Ignoring non-positive %s=%s; using %ss", BATTERY_POLL_INTERVAL_SETTING, interval, configured)
            return configured
        return interval

    def publish(self, topic: str, payload: object, retain: bool = True) -> None:
        self.mqtt_client.publish(topic, str(payload), retain=retain)

    def on_connect(self, client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        if rc == 0:
            logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
            client.subscribe([(MQTT_TOPIC_CHARGE_W, 1), (MQTT_TOPIC_DISCHARGE_W, 1), (MQTT_TOPIC_CONTROL_STATE, 1)])
            self.publish_bridge_alive()
        else:
            logger.error("MQTT connection failed with rc=%s", rc)

    def on_disconnect(self, _client: mqtt.Client, _userdata: Any, rc: int) -> None:
        logger.warning("MQTT disconnected with rc=%s", rc)

    def publish_bridge_alive(self) -> None:
        timestamp = utc_now_iso()
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_ONLINE, retain=True)
        self.publish(MQTT_TOPIC_BRIDGE_LAST_SEEN, timestamp, retain=True)
        logger.debug("Published bridge heartbeat timestamp=%s", timestamp)

    def on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if self.loop is None:
            logger.warning("Ignoring MQTT message before event loop is ready")
            return

        payload = message.payload.decode("utf-8", errors="replace").strip()
        if message.topic == MQTT_TOPIC_CONTROL_STATE:
            self.handle_control_state(payload)
            return

        try:
            watts = int(payload)
        except ValueError:
            logger.warning("Ignoring invalid watt payload on %s: %r", message.topic, payload)
            return

        if message.topic == MQTT_TOPIC_CHARGE_W:
            asyncio.run_coroutine_threadsafe(self.handle_charge_setpoint(watts), self.loop)
        elif message.topic == MQTT_TOPIC_DISCHARGE_W:
            asyncio.run_coroutine_threadsafe(self.handle_discharge_setpoint(watts), self.loop)

    def handle_control_state(self, state: str) -> None:
        previous_state = self.control_state
        self.control_state = state
        if previous_state == "IDLE" and state in {"CHARGING", "DISCHARGING"}:
            logger.info("Control state changed %s -> %s; polling inverter status immediately", previous_state, state)
            self.schedule_immediate_poll()

    def schedule_immediate_poll(self) -> None:
        if self.loop is None:
            logger.warning("Ignoring immediate poll request before event loop is ready")
            return
        if self._immediate_poll_task is not None and not self._immediate_poll_task.done():
            logger.debug("Immediate inverter status poll already queued")
            return
        self._immediate_poll_task = asyncio.run_coroutine_threadsafe(self.poll_once_safely(), self.loop)

    async def poll_once_safely(self) -> None:
        try:
            await self.poll_once()
        except (ConnectionError, TimeoutError) as exc:
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)
        except Exception as exc:
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)

    async def handle_charge_setpoint(self, watts: int) -> None:
        try:
            await self.backend.set_charge(watts)
        except Exception:
            logger.exception("Failed to handle charge_w=%s", watts)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)

    async def handle_discharge_setpoint(self, watts: int) -> None:
        try:
            await self.backend.set_discharge(watts)
        except Exception:
            logger.exception("Failed to handle discharge_w=%s", watts)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)

    async def poll_once(self) -> None:
        state = await self.backend.read_state()
        values = {
            "minyad/battery/soc": state.battery_soc,
            "minyad/battery/soh": state.battery_soh,
            "minyad/battery/power_w": state.battery_power_w,
            "minyad/battery/voltage_v": state.battery_voltage_v,
            "minyad/battery/temperature_c": state.battery_temperature_c,
            "minyad/battery/mode": state.battery_mode,
            "minyad/inverter/temperature_c": state.inverter_temperature_c,
            "minyad/inverter/grid_power_w": state.grid_power_w,
            MQTT_TOPIC_INVERTER_STATUS: STATUS_OK,
        }
        for topic, value in values.items():
            self.publish(topic, value, retain=True)
        self.publish_bridge_alive()
        logger.info(
            "Poll timestamp=%s soc=%s power_w=%s grid_power_w=%s",
            utc_now_iso(),
            state.battery_soc,
            state.battery_power_w,
            state.grid_power_w,
        )

    async def polling_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                await self.poll_once()
            except (ConnectionError, TimeoutError) as exc:
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
                logger.warning("Polling failed: %s", exc, exc_info=True)
            except Exception as exc:
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
                logger.warning("Polling failed: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=self.load_poll_interval())
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.mqtt_client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()
        await self.polling_loop()
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_OFFLINE, retain=True)
        self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    backend = build_backend(config)
    logger.info("Using inverter backend: %s", config.inverter_backend)
    bridge = GoodWeBridge(config, backend)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
