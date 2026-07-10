"""MQTT observer sidecar for Minyad Mosquitto metrics."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt
from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server

LOGGER = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST", "minyad-mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
METRICS_PORT = int(os.getenv("METRICS_PORT", "9106"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))

PROMETHEUS_REGISTRY = CollectorRegistry()
BUILD_INFO = Gauge("minyad_mqtt_build_info", "Build and version information for the MQTT observer.", ["version"], registry=PROMETHEUS_REGISTRY)
ERRORS_TOTAL = Counter("minyad_mqtt_errors_total", "Errors observed by the MQTT observer.", ["type"], registry=PROMETHEUS_REGISTRY)
MESSAGES_TOTAL = Counter("minyad_mqtt_messages_total", "MQTT messages observed by fixed topic group.", ["topic_group"], registry=PROMETHEUS_REGISTRY)
CONNECTED = Gauge("minyad_mqtt_connected", "MQTT observer connection state, 1 connected and 0 disconnected.", registry=PROMETHEUS_REGISTRY)

STOP = threading.Event()


def topic_group(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != "minyad":
        return "other"
    if parts[1] in {"battery", "bridge", "control", "dsmr", "grid", "inverter", "market", "settings", "solar", "strategy", "strategy3", "trade"}:
        return parts[1]
    return "other"


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    LOGGER.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)


def on_connect(client: mqtt.Client, _userdata: object, _flags: mqtt.ConnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
    if reason_code.is_failure:
        CONNECTED.set(0)
        ERRORS_TOTAL.labels(type="connect").inc()
        LOGGER.warning("MQTT observer connection failed with reason=%s", reason_code)
        return
    CONNECTED.set(1)
    client.subscribe("minyad/#")
    LOGGER.info("MQTT observer connected to %s:%s", MQTT_HOST, MQTT_PORT)


def on_disconnect(_client: mqtt.Client, _userdata: object, _flags: mqtt.DisconnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
    CONNECTED.set(0)
    if reason_code.value != 0:
        ERRORS_TOTAL.labels(type="disconnect").inc()
    LOGGER.warning("MQTT observer disconnected with reason=%s", reason_code)


def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
    MESSAGES_TOTAL.labels(topic_group=topic_group(message.topic)).inc()


def request_shutdown(_signum: int, _frame: object) -> None:
    STOP.set()


def main() -> None:
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    start_metrics_server()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="minyad-mqtt-observer")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    while not STOP.wait(1):
        time.sleep(0)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
