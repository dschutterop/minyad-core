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
from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server
from dotenv import load_dotenv

load_dotenv()

LOGGER_NAME = "dsmr_bridge"
logger = logging.getLogger(LOGGER_NAME)

SOURCE_CLIENT_ID = "minyad-dsmr-bridge-source"
TARGET_CLIENT_ID = "minyad-dsmr-bridge-target"
STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_DISCONNECTED = "disconnected"
STATUS_INTERVAL_SECONDS = 30
METRICS_PORT = int(os.getenv("METRICS_PORT", "9108"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))

PROMETHEUS_REGISTRY = CollectorRegistry()
BUILD_INFO = Gauge("minyad_bridge_dsmr_build_info", "Build and version information for the DSMR bridge.", ["version"], registry=PROMETHEUS_REGISTRY)
ERRORS_TOTAL = Counter("minyad_bridge_dsmr_errors_total", "Errors observed by the DSMR bridge.", ["type"], registry=PROMETHEUS_REGISTRY)
LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "minyad_bridge_dsmr_last_success_timestamp_seconds",
    "Unix timestamp of the most recent successful DSMR bridge publish.",
    registry=PROMETHEUS_REGISTRY,
)


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    logger.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)

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


def _get_first_env_int(names: tuple[str, ...], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return _get_env_int(name, default)
    return default


@dataclass(frozen=True)
class Config:
    dsmr_mqtt_host: str
    dsmr_mqtt_port: int
    dsmr_mqtt_user: str | None
    dsmr_mqtt_pass: str | None
    minyad_mqtt_host: str
    minyad_mqtt_port: int
    minyad_mqtt_user: str | None
    minyad_mqtt_pass: str | None
    dsmr_topic_prefix: str
    minyad_topic_prefix: str
    stale_timeout: int
    dead_timeout: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        dsmr_mqtt_host = os.getenv("DSMR_MQTT_BROKER") or os.getenv("DSMR_MQTT_HOST")
        if not dsmr_mqtt_host:
            raise ValueError("DSMR_MQTT_BROKER is required")

        minyad_mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MINYAD_MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not minyad_mqtt_host:
            raise ValueError("MQTT_BROKER is required for the Minyad target broker")

        dsmr_mqtt_port = _get_env_int("DSMR_MQTT_PORT", 1883)
        minyad_mqtt_port = _get_first_env_int(("MQTT_PORT", "MINYAD_MQTT_PORT"), 1883)
        if dsmr_mqtt_host == minyad_mqtt_host and dsmr_mqtt_port == minyad_mqtt_port:
            raise ValueError("DSMR_MQTT_BROKER must point to a different broker than the Minyad target MQTT_BROKER")

        stale_timeout = _get_env_int("STALE_TIMEOUT", 60)
        dead_timeout = _get_env_int("DEAD_TIMEOUT", 300)
        if stale_timeout < 1:
            raise ValueError("STALE_TIMEOUT must be greater than 0")
        if dead_timeout <= stale_timeout:
            raise ValueError("DEAD_TIMEOUT must be greater than STALE_TIMEOUT")

        return cls(
            dsmr_mqtt_host=dsmr_mqtt_host,
            dsmr_mqtt_port=dsmr_mqtt_port,
            dsmr_mqtt_user=os.getenv("DSMR_MQTT_USER") or None,
            dsmr_mqtt_pass=os.getenv("DSMR_MQTT_PASS") or None,
            minyad_mqtt_host=minyad_mqtt_host,
            minyad_mqtt_port=minyad_mqtt_port,
            minyad_mqtt_user=os.getenv("MQTT_USER") or os.getenv("MINYAD_MQTT_USER") or None,
            minyad_mqtt_pass=os.getenv("MQTT_PASS") or os.getenv("MINYAD_MQTT_PASS") or None,
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
        self.source_connected = False
        self.target_connected = False
        self.status_thread: threading.Thread | None = None
        self.status_stop_event = threading.Event()

        self.source_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=SOURCE_CLIENT_ID,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        if config.dsmr_mqtt_user:
            self.source_client.username_pw_set(config.dsmr_mqtt_user, config.dsmr_mqtt_pass)
        self.source_client.on_connect = self.on_source_connect
        self.source_client.on_disconnect = self.on_source_disconnect
        self.source_client.on_message = self.on_message
        self.source_client.reconnect_delay_set(min_delay=1, max_delay=60)

        self.target_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=TARGET_CLIENT_ID,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        self.target_client.will_set(self.minyad_topic("status"), STATUS_DISCONNECTED, retain=True)
        if config.minyad_mqtt_user:
            self.target_client.username_pw_set(config.minyad_mqtt_user, config.minyad_mqtt_pass)
        self.target_client.on_connect = self.on_target_connect
        self.target_client.on_disconnect = self.on_target_disconnect
        self.target_client.reconnect_delay_set(min_delay=1, max_delay=60)

    def dsmr_topic(self, field: str) -> str:
        return f"{self.config.dsmr_topic_prefix}/{field}"

    def minyad_topic(self, field: str) -> str:
        return f"{self.config.minyad_topic_prefix}/{field}"

    def publish(self, field: str, payload: object) -> None:
        topic = self.minyad_topic(field)
        result = self.target_client.publish(topic, str(payload), retain=True)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            ERRORS_TOTAL.labels(type="mqtt_publish").inc()
            logger.warning("MQTT publish failed for %s with rc=%s", topic, result.rc)
            return
        logger.debug("Published %s=%s", topic, payload)

    def on_source_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self.source_connected = False
            logger.warning("DSMR source MQTT connection failed with reason=%s", reason_code)
            return

        self.source_connected = True
        logger.info(
            "DSMR source MQTT connected to %s:%s",
            self.config.dsmr_mqtt_host,
            self.config.dsmr_mqtt_port,
        )
        subscriptions = [(self.dsmr_topic(field), 1) for field in sorted(SUBSCRIBED_FIELDS)]
        client.subscribe(subscriptions)

    def on_source_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self.source_connected = False
        logger.warning("DSMR source MQTT disconnected with reason=%s", reason_code)
        self.publish("status", STATUS_DISCONNECTED)

    def on_target_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self.target_connected = False
            logger.warning("Minyad target MQTT connection failed with reason=%s", reason_code)
            return

        self.target_connected = True
        logger.info(
            "Minyad target MQTT connected to %s:%s",
            self.config.minyad_mqtt_host,
            self.config.minyad_mqtt_port,
        )

    def on_target_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self.target_connected = False
        logger.warning("Minyad target MQTT disconnected with reason=%s", reason_code)

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
                ERRORS_TOTAL.labels(type="invalid_payload").inc()
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
            ERRORS_TOTAL.labels(type="invalid_primary_values").inc()
            logger.warning("Primary DSMR values have invalid types; skipping net power publish")
            return

        net_grid_power_w = round((delivered_kw - returned_kw) * 1000)
        self.publish("net_power_w", net_grid_power_w)
        LAST_SUCCESS_TIMESTAMP_SECONDS.set(time.time())

    def current_status(self) -> str:
        with self.state_lock:
            last_update = self.last_update_monotonic
            source_connected = self.source_connected
            target_connected = self.target_connected

        if not source_connected or not target_connected or last_update is None:
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
                ERRORS_TOTAL.labels(type="status_publish").inc()
                logger.warning("Failed to publish DSMR status", exc_info=True)

    async def run(self) -> None:
        self.status_thread = threading.Thread(target=self.status_loop, name="dsmr-status", daemon=True)
        self.status_thread.start()
        self.target_client.connect_async(self.config.minyad_mqtt_host, self.config.minyad_mqtt_port, keepalive=60)
        self.source_client.connect_async(self.config.dsmr_mqtt_host, self.config.dsmr_mqtt_port, keepalive=60)
        self.target_client.loop_start()
        self.source_client.loop_start()
        await self.shutdown_event.wait()
        self.publish("status", STATUS_DISCONNECTED)
        self.status_stop_event.set()
        if self.status_thread:
            self.status_thread.join(timeout=5)
        self.source_client.loop_stop()
        self.target_client.loop_stop()
        self.source_client.disconnect()
        self.target_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    start_metrics_server()
    bridge = DsmrBridge(config)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
