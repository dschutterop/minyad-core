"""Minyad deadman watchdog scaffold."""

from __future__ import annotations

import logging
import time

from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

configure_container_logging(logging.INFO)


def main() -> None:
    mqtt = MinyadMqttClient("minyad-deadman")
    mqtt.start()
    while True:
        mqtt.publish_measurement("deadman", "heartbeat", "alive")
        time.sleep(5)


if __name__ == "__main__":
    main()
