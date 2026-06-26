"""Fetch and persist Open-Meteo solar forecasts for Minyad."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

LOGGER = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LATITUDE = float(os.getenv("FORECAST_LATITUDE", "51.9788"))
LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", "4.3158"))
PEAK_W = int(os.getenv("SOLAR_PEAK_W", "5000"))
EFFICIENCY = 0.80
REFRESH_SECONDS = 15 * 60
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BASE_DELAY_SECONDS = 2


def _retry_delay_seconds(attempt: int) -> int:
    return FETCH_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))


def scale_to_system(direct_w_m2: float | None, diffuse_w_m2: float | None) -> int:
    total = max(0.0, float(direct_w_m2 or 0) + float(diffuse_w_m2 or 0))
    return round((total / 1000.0) * PEAK_W * EFFICIENCY)


async def fetch_solar_forecast() -> list[dict]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "direct_radiation,diffuse_radiation,shortwave_radiation",
        "forecast_days": 2,
        "timezone": "Europe/Amsterdam",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(1, FETCH_RETRY_ATTEMPTS + 1):
            try:
                response = await client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                data = response.json()
                break
            except httpx.RequestError as exc:
                if attempt == FETCH_RETRY_ATTEMPTS:
                    raise
                delay = _retry_delay_seconds(attempt)
                LOGGER.warning(
                    "Open-Meteo request failed on attempt %d/%d; retrying in %ss: %s",
                    attempt,
                    FETCH_RETRY_ATTEMPTS,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError:
                raise

    hourly = data["hourly"]
    points = []
    for forecast_time, direct, diffuse, shortwave in zip(
        hourly["time"],
        hourly.get("direct_radiation", []),
        hourly.get("diffuse_radiation", []),
        hourly.get("shortwave_radiation", []),
    ):
        direct_value = float(direct or 0)
        diffuse_value = float(diffuse if diffuse is not None else max(0, float(shortwave or 0) - direct_value))
        forecast_dt = datetime.fromisoformat(forecast_time).replace(tzinfo=ZoneInfo("Europe/Amsterdam")).astimezone(timezone.utc)
        points.append({
            "forecast_time": forecast_dt,
            "direct_w_m2": direct_value,
            "diffuse_w_m2": diffuse_value,
            "estimated_w": scale_to_system(direct_value, diffuse_value),
        })
    return points


async def persist_forecast(points: list[dict]) -> None:
    fetched_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        for point in points:
            await session.execute(
                text("""
                    insert into solar_forecast_points
                      (timestamp, bucket_start, granularity_seconds, power_w, forecast_ghi, provider,
                       fetched_at, forecast_time, direct_w_m2, diffuse_w_m2, estimated_w, source)
                    values
                      (:forecast_time, date_trunc('minute', :forecast_time), 900, :estimated_w, null, 'open-meteo',
                       :fetched_at, :forecast_time, :direct_w_m2, :diffuse_w_m2, :estimated_w, 'open-meteo')
                    on conflict (forecast_time) do update set
                      timestamp = excluded.timestamp,
                      bucket_start = excluded.bucket_start,
                      granularity_seconds = 900,
                      power_w = excluded.power_w,
                      provider = 'open-meteo',
                      fetched_at = excluded.fetched_at,
                      direct_w_m2 = excluded.direct_w_m2,
                      diffuse_w_m2 = excluded.diffuse_w_m2,
                      estimated_w = excluded.estimated_w,
                      source = 'open-meteo'
                """),
                {"fetched_at": fetched_at, **point},
            )
        await session.commit()


async def main() -> None:
    configure_container_logging(logging.INFO)
    mqtt = MinyadMqttClient("minyad-forecast")
    mqtt.start()
    while True:
        try:
            points = await fetch_solar_forecast()
            await persist_forecast(points)
            if points:
                mqtt.publish_measurement("forecast", "solar_power_w", points[0]["estimated_w"])
            LOGGER.info("persisted %d Open-Meteo solar forecast points", len(points))
        except Exception:
            LOGGER.exception("solar forecast refresh failed")
        await asyncio.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
