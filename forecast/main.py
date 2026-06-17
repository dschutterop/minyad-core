"""Minyad forecast service scaffold."""

from __future__ import annotations

import time

from shared.db import init_db
from shared.mqtt_client import MinyadMqttClient


def main() -> None:
    init_db()
    mqtt = MinyadMqttClient("minyad-forecast")
    mqtt.start()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
