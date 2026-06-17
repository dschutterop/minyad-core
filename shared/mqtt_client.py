"""Shared MQTT client wrapper for Minyad modules."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import paho.mqtt.client as mqtt

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MqttConfig:
    host: str = os.getenv("MQTT_HOST", "minyad-mqtt")
    port: int = int(os.getenv("MQTT_PORT", "1883"))
    keepalive: int = 30


class MinyadMqttClient:
    """Small paho-mqtt wrapper with reconnect and Minyad topic helpers."""

    def __init__(self, client_id: str, config: MqttConfig | None = None) -> None:
        self.config = config or MqttConfig()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._subscriptions: dict[str, Callable[[str, bytes], None]] = {}
        self._subscriptions_lock = Lock()
        self._client_id = client_id
        self._connected = False
        self._connect_count = 0
        self._disconnect_count = 0
        self._last_connect_at: datetime | None = None
        self._last_disconnect_at: datetime | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connection_info(self) -> dict[str, Any]:
        return {
            "client_id": self._client_id,
            "host": self.config.host,
            "port": self.config.port,
            "keepalive": self.config.keepalive,
            "connected": self._connected,
            "connect_count": self._connect_count,
            "disconnect_count": self._disconnect_count,
            "last_connect_at": self._last_connect_at.isoformat() if self._last_connect_at else None,
            "last_disconnect_at": self._last_disconnect_at.isoformat() if self._last_disconnect_at else None,
        }

    def _on_connect(self, client: mqtt.Client, _userdata: object, _flags: mqtt.ConnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        self._connected = True
        self._connect_count += 1
        self._last_connect_at = datetime.now(timezone.utc)
        LOGGER.info("MQTT connected: reason=%s host=%s port=%s connect_count=%d", reason_code, self.config.host, self.config.port, self._connect_count)
        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions)
        for topic in subscriptions:
            client.subscribe(topic)
            LOGGER.info("MQTT re-subscribed after connect: %s", topic)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: mqtt.DisconnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        self._connected = False
        self._disconnect_count += 1
        self._last_disconnect_at = datetime.now(timezone.utc)
        LOGGER.warning("MQTT disconnected: reason=%s disconnect_count=%d", reason_code, self._disconnect_count)

    def _on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        LOGGER.debug("MQTT rx: topic=%s qos=%d retain=%d payload=%r", message.topic, message.qos, message.retain, message.payload[:200])
        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions.items())
        matched = False
        for topic_filter, handler in subscriptions:
            if mqtt.topic_matches_sub(topic_filter, message.topic):
                matched = True
                handler(message.topic, message.payload)
        if not matched:
            LOGGER.debug("MQTT rx: topic=%s matched no subscription filter", message.topic)

    def _on_subscribe(self, _client: mqtt.Client, _userdata: object, mid: int, reason_codes: list, _properties: mqtt.Properties | None) -> None:
        LOGGER.debug("MQTT subscribe ack: mid=%d reason_codes=%s", mid, reason_codes)

    def connect_forever(self) -> None:
        while True:
            try:
                LOGGER.info("MQTT connecting to %s:%s (client_id=%s)", self.config.host, self.config.port, self._client_id)
                self.client.connect(self.config.host, self.config.port, self.config.keepalive)
                self.client.loop_forever(retry_first_connection=True)
            except OSError:
                LOGGER.exception("MQTT connection failed; retrying in 5s (host=%s port=%s)", self.config.host, self.config.port)
                time.sleep(5)

    def start(self) -> None:
        LOGGER.info("MQTT async connect: host=%s port=%s client_id=%s", self.config.host, self.config.port, self._client_id)
        self.client.connect_async(self.config.host, self.config.port, self.config.keepalive)
        self.client.loop_start()

    def publish_measurement(self, source: str, measurement: str, payload: str | int | float) -> None:
        topic = f"minyad/{source}/{measurement}"
        LOGGER.debug("MQTT tx: topic=%s payload=%r", topic, str(payload))
        self.client.publish(topic, payload=str(payload), qos=0, retain=False)

    def subscribe(self, topic: str, handler: Callable[[str, bytes], None]) -> None:
        LOGGER.debug("MQTT register subscription: %s", topic)
        with self._subscriptions_lock:
            self._subscriptions[topic] = handler
        self.client.subscribe(topic)
