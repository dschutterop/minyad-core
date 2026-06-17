"""Minyad deadman watchdog scaffold."""

from __future__ import annotations

import logging
import time

from shared.db import init_db
from shared.mqtt_client import MinyadMqttClient

logging.basicConfig(level=logging.INFO)


def main() -> None:
    init_db()
    mqtt = MinyadMqttClient("minyad-deadman")
    mqtt.start()
    while True:
        mqtt.publish_measurement("deadman", "heartbeat", "alive")
        time.sleep(5)


if __name__ == "__main__":
    main()
