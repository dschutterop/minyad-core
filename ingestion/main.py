"""Minyad ingestion service: adapt external sensors to internal MQTT only."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)
from sensors.dsmr import P1Reader
from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

configure_container_logging(logging.INFO)
LOGGER = logging.getLogger(__name__)

DEFAULT_DSMR_BROKER = os.getenv("DEFAULT_DSMR_BROKER", "minyad-mqtt")
DEFAULT_DSMR_PORT = 1883
METRICS_PORT = int(os.getenv("METRICS_PORT", "9102"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))
PROMETHEUS_REGISTRY = CollectorRegistry()

BUILD_INFO = Gauge(
    "minyad_ingestion_build_info",
    "Build and version information for minyad-ingestion.",
    ["version"],
    registry=PROMETHEUS_REGISTRY,
)
ERRORS_TOTAL = Counter(
    "minyad_ingestion_errors_total",
    "Errors observed by minyad-ingestion.",
    ["type"],
    registry=PROMETHEUS_REGISTRY,
)
SAMPLES_TOTAL = Counter(
    "minyad_ingestion_samples_total",
    "Sensor samples processed by minyad-ingestion.",
    ["source"],
    registry=PROMETHEUS_REGISTRY,
)
LAST_SAMPLE_TIMESTAMP_SECONDS = Gauge(
    "minyad_ingestion_last_sample_timestamp_seconds",
    "Unix timestamp of the most recent sensor sample processed by minyad-ingestion.",
    ["source"],
    registry=PROMETHEUS_REGISTRY,
)
WRITE_DURATION_SECONDS = Histogram(
    "minyad_ingestion_write_duration_seconds",
    "Duration of ingestion database writes.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=PROMETHEUS_REGISTRY,
)


async def _setting(key: str, default: str) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select value from settings where key = :key and encrypted = false"), {"key": key})
        return result.scalar_one_or_none() or default


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    LOGGER.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)


async def main() -> None:
    start_metrics_server()
    mqtt = MinyadMqttClient("minyad-ingestion")
    mqtt.start()
    broker = await _setting("dsmr.mqtt.broker", DEFAULT_DSMR_BROKER)
    port = int(await _setting("dsmr.mqtt.port", str(DEFAULT_DSMR_PORT)))
    pending_grid_write_tasks: set[asyncio.Task[None]] = set()

    async def store_grid_point(net_power_w: int, per_phase_w: dict, timestamp, delivered_w: int, returned_w: int) -> None:
        with WRITE_DURATION_SECONDS.time():
            try:
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
                timestamp = timestamp.astimezone(UTC)
                bucket_start = timestamp.replace(second=0, microsecond=0)
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text("""
                            insert into power_curve_points
                              (timestamp, bucket_start, granularity_seconds, source, power_w, delivered_w, returned_w, net_w, metadata)
                            values (:timestamp, :bucket_start, 60, 'grid', :power_w, :delivered_w, :returned_w, :power_w, cast(:metadata as json))
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
                    for granularity in (900, 3600):
                        await session.execute(
                            text("""
                                insert into power_curve_rollups
                                  (bucket_start, granularity_seconds, source, sample_count, power_w, delivered_w, returned_w, net_w, updated_at)
                                values (
                                  to_timestamp(floor(extract(epoch from :timestamp) / :granularity) * :granularity),
                                  :granularity, 'grid', 1, :power_w, :delivered_w, :returned_w, :power_w, now()
                                )
                                on conflict (bucket_start, granularity_seconds, source) do update set
                                  power_w = round(((power_curve_rollups.power_w * power_curve_rollups.sample_count) + excluded.power_w)::numeric / (power_curve_rollups.sample_count + 1)),
                                  delivered_w = round(((coalesce(power_curve_rollups.delivered_w, 0) * power_curve_rollups.sample_count) + excluded.delivered_w)::numeric / (power_curve_rollups.sample_count + 1)),
                                  returned_w = round(((coalesce(power_curve_rollups.returned_w, 0) * power_curve_rollups.sample_count) + excluded.returned_w)::numeric / (power_curve_rollups.sample_count + 1)),
                                  net_w = round(((coalesce(power_curve_rollups.net_w, power_curve_rollups.power_w) * power_curve_rollups.sample_count) + excluded.net_w)::numeric / (power_curve_rollups.sample_count + 1)),
                                  sample_count = power_curve_rollups.sample_count + 1,
                                  updated_at = now()
                            """),
                            {"timestamp": timestamp, "granularity": granularity, "power_w": net_power_w, "delivered_w": delivered_w, "returned_w": returned_w},
                        )
                    await session.commit()
            except Exception:
                ERRORS_TOTAL.labels(type="db_write").inc()
                LOGGER.exception("Failed to write DSMR grid point")
                raise

    def publish_update(net_power_w: int, per_phase_w: dict, timestamp, delivered_w: int, returned_w: int) -> None:
        sample_timestamp = timestamp
        if sample_timestamp.tzinfo is None:
            sample_timestamp = sample_timestamp.replace(tzinfo=UTC)
        SAMPLES_TOTAL.labels(source="dsmr").inc()
        LAST_SAMPLE_TIMESTAMP_SECONDS.labels(source="dsmr").set(sample_timestamp.timestamp())
        mqtt.publish_measurement("dsmr", "net_power_w", net_power_w)
        mqtt.publish_measurement("dsmr", "phase_w_l1", per_phase_w["L1"])
        mqtt.publish_measurement("dsmr", "phase_w_l2", per_phase_w["L2"])
        mqtt.publish_measurement("dsmr", "phase_w_l3", per_phase_w["L3"])
        mqtt.publish_measurement("dsmr", "timestamp", timestamp.isoformat())
        task = asyncio.create_task(store_grid_point(net_power_w, per_phase_w, timestamp, delivered_w, returned_w))
        pending_grid_write_tasks.add(task)
        task.add_done_callback(pending_grid_write_tasks.discard)

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
