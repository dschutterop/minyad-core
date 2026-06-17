"""Minyad control service scaffold."""

from __future__ import annotations

import logging
import time

from shared.mqtt_client import MinyadMqttClient

logging.basicConfig(level=logging.INFO)


def main() -> None:
    mqtt = MinyadMqttClient("minyad-control")
    mqtt.start()
    mqtt.publish_measurement("control", "state", "IDLE")
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
