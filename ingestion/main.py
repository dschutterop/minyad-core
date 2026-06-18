"""Minyad ingestion service: adapt external sensors to internal MQTT only."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timezone

from sensors.dsmr import P1Reader
from shared.db import AsyncSessionLocal
from shared.mqtt_client import MinyadMqttClient
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

DEFAULT_DSMR_BROKER = "192.168.110.2"
DEFAULT_DSMR_PORT = 1883


async def _setting(key: str, default: str) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select value from settings where key = :key and encrypted = false"), {"key": key})
        return result.scalar_one_or_none() or default


async def main() -> None:
    mqtt = MinyadMqttClient("minyad-ingestion")
    mqtt.start()
    broker = await _setting("dsmr.mqtt.broker", DEFAULT_DSMR_BROKER)
    port = int(await _setting("dsmr.mqtt.port", str(DEFAULT_DSMR_PORT)))

    async def store_grid_point(net_power_w: int, per_phase_w: dict, timestamp, delivered_w: int, returned_w: int) -> None:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        bucket_start = timestamp.replace(second=0, microsecond=0)
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    insert into power_curve_points
                      (timestamp, bucket_start, granularity_seconds, source, power_w, delivered_w, returned_w, metadata)
                    values (:timestamp, :bucket_start, 60, 'grid', :power_w, :delivered_w, :returned_w, cast(:metadata as json))
                """),
                {
                    "timestamp": timestamp,
                    "bucket_start": bucket_start,
                    "power_w": net_power_w,
                    "delivered_w": delivered_w,
                    "returned_w": returned_w,
                    "metadata": json.dumps(per_phase_w),
                },
            )
            await session.commit()

    def publish_update(net_power_w: int, per_phase_w: dict, timestamp, delivered_w: int, returned_w: int) -> None:
        mqtt.publish_measurement("dsmr", "net_power_w", net_power_w)
        mqtt.publish_measurement("dsmr", "phase_w_l1", per_phase_w["L1"])
        mqtt.publish_measurement("dsmr", "phase_w_l2", per_phase_w["L2"])
        mqtt.publish_measurement("dsmr", "phase_w_l3", per_phase_w["L3"])
        mqtt.publish_measurement("dsmr", "timestamp", timestamp.isoformat())
        asyncio.create_task(store_grid_point(net_power_w, per_phase_w, timestamp, delivered_w, returned_w))

    reader = P1Reader(broker, port, publish_update)
    reader.start()
    LOGGER.info("ingestion running; DSMR external broker=%s:%s", broker, port)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        reader.stop()


if __name__ == "__main__":
    asyncio.run(main())
