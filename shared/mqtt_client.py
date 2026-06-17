"""Shared MQTT client wrapper for Minyad modules."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

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

    def _on_connect(self, _client: mqtt.Client, _userdata: object, _flags: mqtt.ConnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        LOGGER.info("MQTT connected: %s", reason_code)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: mqtt.DisconnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        LOGGER.warning("MQTT disconnected: %s", reason_code)

    def connect_forever(self) -> None:
        while True:
            try:
                self.client.connect(self.config.host, self.config.port, self.config.keepalive)
                self.client.loop_forever(retry_first_connection=True)
            except OSError:
                LOGGER.exception("MQTT connection failed; retrying")
                time.sleep(5)

    def start(self) -> None:
        self.client.connect(self.config.host, self.config.port, self.config.keepalive)
        self.client.loop_start()

    def publish_measurement(self, source: str, measurement: str, payload: str | int | float) -> None:
        self.client.publish(f"minyad/{source}/{measurement}", payload=str(payload), qos=0, retain=False)

    def subscribe(self, topic: str, handler: Callable[[str, bytes], None]) -> None:
        def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
            handler(message.topic, message.payload)

        self.client.on_message = on_message
        self.client.subscribe(topic)
