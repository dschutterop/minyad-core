#!/usr/bin/env python3
"""Host-side DSMR to MQTT bridge for Minyad VPP."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

LOGGER_NAME = "dsmr_bridge"
logger = logging.getLogger(LOGGER_NAME)

CLIENT_ID = "minyad-dsmr-bridge"
STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_DISCONNECTED = "disconnected"
STATUS_INTERVAL_SECONDS = 30

PRIMARY_DELIVERED = "electricity_currently_delivered"
PRIMARY_RETURNED = "electricity_currently_returned"

KW_FIELDS = {
    PRIMARY_DELIVERED: "delivered_w",
    PRIMARY_RETURNED: "returned_w",
    "phase_currently_delivered_l1": "phase_delivered_l1_w",
    "phase_currently_delivered_l2": "phase_delivered_l2_w",
    "phase_currently_delivered_l3": "phase_delivered_l3_w",
    "phase_currently_returned_l1": "phase_returned_l1_w",
    "phase_currently_returned_l2": "phase_returned_l2_w",
    "phase_currently_returned_l3": "phase_returned_l3_w",
}

VOLTAGE_FIELDS = {
    "phase_voltage_l1": "voltage_l1_v",
    "phase_voltage_l2": "voltage_l2_v",
    "phase_voltage_l3": "voltage_l3_v",
}

STRING_FIELDS = {"timestamp": "timestamp"}

SUBSCRIBED_FIELDS = set(KW_FIELDS) | set(VOLTAGE_FIELDS) | set(STRING_FIELDS)


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
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_pass: str | None
    dsmr_topic_prefix: str
    minyad_topic_prefix: str
    stale_timeout: int
    dead_timeout: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not mqtt_host:
            raise ValueError("MQTT_BROKER is required")

        stale_timeout = _get_env_int("STALE_TIMEOUT", 60)
        dead_timeout = _get_env_int("DEAD_TIMEOUT", 300)
        if stale_timeout < 1:
            raise ValueError("STALE_TIMEOUT must be greater than 0")
        if dead_timeout <= stale_timeout:
            raise ValueError("DEAD_TIMEOUT must be greater than STALE_TIMEOUT")

        return cls(
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            mqtt_user=os.getenv("MQTT_USER") or None,
            mqtt_pass=os.getenv("MQTT_PASS") or None,
            dsmr_topic_prefix=os.getenv("DSMR_TOPIC_PREFIX", "dsmr/reading").strip("/"),
            minyad_topic_prefix=os.getenv("MINYAD_TOPIC_PREFIX", "minyad/grid").strip("/"),
            stale_timeout=stale_timeout,
            dead_timeout=dead_timeout,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class DsmrBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.shutdown_event = asyncio.Event()
        self.state: dict[str, float | str] = {}
        self.state_lock = threading.Lock()
        self.last_update_monotonic: float | None = None
        self.connected = False
        self.status_thread: threading.Thread | None = None
        self.status_stop_event = threading.Event()

        self.mqtt_client = mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)
        self.mqtt_client.will_set(self.minyad_topic("status"), STATUS_DISCONNECTED, retain=True)
        if config.mqtt_user:
            self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_pass)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

    def dsmr_topic(self, field: str) -> str:
        return f"{self.config.dsmr_topic_prefix}/{field}"

    def minyad_topic(self, field: str) -> str:
        return f"{self.config.minyad_topic_prefix}/{field}"

    def publish(self, field: str, payload: object) -> None:
        topic = self.minyad_topic(field)
        result = self.mqtt_client.publish(topic, str(payload), retain=True)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish failed for %s with rc=%s", topic, result.rc)
            return
        logger.debug("Published %s=%s", topic, payload)

    def on_connect(self, client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        if rc != 0:
            self.connected = False
            logger.warning("MQTT connection failed with rc=%s", rc)
            return

        self.connected = True
        logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
        subscriptions = [(self.dsmr_topic(field), 1) for field in sorted(SUBSCRIBED_FIELDS)]
        client.subscribe(subscriptions)

    def on_disconnect(self, _client: mqtt.Client, _userdata: Any, rc: int) -> None:
        self.connected = False
        logger.warning("MQTT disconnected with rc=%s", rc)
        self.publish("status", STATUS_DISCONNECTED)

    def on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            self.handle_message(message)
        except Exception:
            logger.warning("Unexpected error while handling MQTT message on %s", message.topic, exc_info=True)

    def handle_message(self, message: mqtt.MQTTMessage) -> None:
        field = message.topic.removeprefix(f"{self.config.dsmr_topic_prefix}/")
        if field not in SUBSCRIBED_FIELDS or field == message.topic:
            return

        payload = message.payload.decode("utf-8", errors="replace").strip()
        if field in KW_FIELDS or field in VOLTAGE_FIELDS:
            try:
                value: float | str = float(payload)
            except ValueError:
                logger.warning("Ignoring malformed numeric payload on %s: %r", message.topic, payload)
                return
        else:
            value = payload

        with self.state_lock:
            self.state[field] = value
            self.last_update_monotonic = time.monotonic()
            snapshot = dict(self.state)

        if PRIMARY_DELIVERED in snapshot and PRIMARY_RETURNED in snapshot:
            self.publish_grid_values(snapshot)

    def publish_grid_values(self, snapshot: dict[str, float | str]) -> None:
        for dsmr_field, minyad_field in KW_FIELDS.items():
            value = snapshot.get(dsmr_field)
            if isinstance(value, (float, int)):
                self.publish(minyad_field, max(0, round(value * 1000)))

        for dsmr_field, minyad_field in VOLTAGE_FIELDS.items():
            value = snapshot.get(dsmr_field)
            if isinstance(value, (float, int)):
                self.publish(minyad_field, f"{value:.1f}")

        timestamp = snapshot.get("timestamp")
        if isinstance(timestamp, str):
            self.publish("timestamp", timestamp)

        delivered_kw = snapshot[PRIMARY_DELIVERED]
        returned_kw = snapshot[PRIMARY_RETURNED]
        if not isinstance(delivered_kw, (float, int)) or not isinstance(returned_kw, (float, int)):
            logger.warning("Primary DSMR values have invalid types; skipping net power publish")
            return

        net_grid_power_w = round((delivered_kw - returned_kw) * 1000)
        self.publish("net_power_w", net_grid_power_w)

    def current_status(self) -> str:
        with self.state_lock:
            last_update = self.last_update_monotonic
            connected = self.connected

        if not connected or last_update is None:
            return STATUS_DISCONNECTED

        age = time.monotonic() - last_update
        if age > self.config.dead_timeout:
            return STATUS_DISCONNECTED
        if age >= self.config.stale_timeout:
            return STATUS_STALE
        return STATUS_OK

    def status_loop(self) -> None:
        while not self.status_stop_event.wait(STATUS_INTERVAL_SECONDS):
            try:
                self.publish("status", self.current_status())
            except Exception:
                logger.warning("Failed to publish DSMR status", exc_info=True)

    async def run(self) -> None:
        self.status_thread = threading.Thread(target=self.status_loop, name="dsmr-status", daemon=True)
        self.status_thread.start()
        self.mqtt_client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()
        await self.shutdown_event.wait()
        self.publish("status", STATUS_DISCONNECTED)
        self.status_stop_event.set()
        if self.status_thread:
            self.status_thread.join(timeout=5)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    bridge = DsmrBridge(config)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
