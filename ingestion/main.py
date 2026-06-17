"""Minyad ingestion service: publish sensor readings to MQTT only."""

from __future__ import annotations

import logging
import time

from sensors.dsmr import parse_telegram
from shared.mqtt_client import MinyadMqttClient

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def main() -> None:
    mqtt = MinyadMqttClient("minyad-ingestion")
    mqtt.start()
    LOGGER.info("ingestion scaffold running; waiting for sensor adapters")
    while True:
        for measurement in parse_telegram(""):
            mqtt.publish_measurement("dsmr", measurement.measurement, measurement.value)
        time.sleep(10)


if __name__ == "__main__":
    main()
