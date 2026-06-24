"""Fetch EPEX/ENTSO-E day-ahead electricity prices and publish them to MQTT."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from config import AMSTERDAM_TZ, DAY_AHEAD_DEFAULTS, ENTSOE, MQTT_TOPICS
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DayAheadSettings:
    bidding_zone: str = DAY_AHEAD_DEFAULTS.bidding_zone
    poll_time_local: str = DAY_AHEAD_DEFAULTS.poll_time_local
    retry_attempts: int = DAY_AHEAD_DEFAULTS.retry_attempts
    retry_interval_minutes: int = DAY_AHEAD_DEFAULTS.retry_interval_minutes


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settings = DayAheadSettings()

    def get(self) -> DayAheadSettings:
        with self._lock:
            return self._settings

    def apply_mqtt(self, topic: str, payload: bytes) -> None:
        key = topic.removeprefix(f"{MQTT_TOPICS.settings_prefix}/")
        raw = payload.decode().strip()
        with self._lock:
            current = self._settings
            try:
                if key == "bidding_zone":
                    updated = replace(current, bidding_zone=raw or DAY_AHEAD_DEFAULTS.bidding_zone)
                elif key == "poll_time_local":
                    datetime.strptime(raw, "%H:%M")
                    updated = replace(current, poll_time_local=raw)
                elif key == "retry_attempts":
                    updated = replace(current, retry_attempts=max(1, int(raw)))
                elif key == "retry_interval_minutes":
                    updated = replace(current, retry_interval_minutes=max(1, int(raw)))
                else:
                    LOGGER.debug("Ignoring unknown trade setting topic=%s", topic)
                    return
            except ValueError:
                LOGGER.warning("Ignoring invalid trade setting topic=%s payload=%r", topic, raw)
                return
            if updated != current:
                self._settings = updated
                LOGGER.info("Trade settings updated: %s", updated)


def next_poll_time(now: datetime, poll_time_local: str) -> datetime:
    hour, minute = [int(part) for part in poll_time_local.split(":", 1)]
    candidate = now.astimezone(AMSTERDAM_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now.astimezone(AMSTERDAM_TZ):
        candidate += timedelta(days=1)
    return candidate


def normalize_prices(series: pd.Series) -> list[dict[str, Any]]:
    prices = []
    for timestamp, eur_mwh in series.items():
        local_ts = timestamp.to_pydatetime().astimezone(AMSTERDAM_TZ)
        prices.append({
            "date": local_ts.strftime("%Y-%m-%d"),
            "hour": local_ts.strftime("%H"),
            "starts_at": local_ts.isoformat(),
            "price_eur_kwh": float(eur_mwh) / ENTSOE.price_unit_divisor,
        })
    return prices


def fetch_day_ahead(client: Any, settings: DayAheadSettings, target_day: datetime) -> list[dict[str, Any]]:
    start = pd.Timestamp(target_day.date(), tz=ENTSOE.timezone_name)
    end = start + pd.DateOffset(days=1)
    LOGGER.info("Fetching day-ahead prices zone=%s day=%s", settings.bidding_zone, start.date())
    series = client.query_day_ahead_prices(settings.bidding_zone, start=start, end=end)
    if series is None or series.empty:
        return []
    prices = normalize_prices(series)
    target_date = start.date().isoformat()
    return [point for point in prices if point["date"] == target_date]


def publish_prices(mqtt: MinyadMqttClient, prices: list[dict[str, Any]]) -> None:
    if not prices:
        raise RuntimeError("No day-ahead prices returned")
    day = prices[0]["date"]
    prefix = f"{MQTT_TOPICS.day_ahead_price_prefix}/{day}"
    full_payload = json.dumps(prices, separators=(",", ":"))
    mqtt.publish(f"{prefix}/{MQTT_TOPICS.day_ahead_full_suffix}", full_payload, retain=True)
    for point in prices:
        mqtt.publish(f"{prefix}/{point['hour']}", point["price_eur_kwh"], retain=True)
    LOGGER.info("Published %d day-ahead price points for %s", len(prices), day)


def collect_with_retries(client: Any, mqtt: MinyadMqttClient, settings: DayAheadSettings, target_day: datetime) -> bool:
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            prices = fetch_day_ahead(client, settings, target_day)
            publish_prices(mqtt, prices)
            return True
        except Exception as exc:  # ENTSO-E uses several exception types for unavailable data.
            if attempt >= settings.retry_attempts:
                LOGGER.exception("Day-ahead price collection failed after %d attempts: %r", attempt, exc)
                return False
            LOGGER.warning(
                "Day-ahead prices unavailable attempt %d/%d; retrying in %d minutes: %r",
                attempt,
                settings.retry_attempts,
                settings.retry_interval_minutes,
                exc,
            )
            time.sleep(settings.retry_interval_minutes * 60)
    return False


def collect_startup_prices(client: Any, mqtt: MinyadMqttClient, settings: DayAheadSettings, now: datetime) -> None:
    target = _target_day(now)
    LOGGER.info("Running startup ENTSO-E day-ahead poll for %s", target.date())
    if collect_with_retries(client, mqtt, settings, target):
        return

    current_day = now.astimezone(AMSTERDAM_TZ)
    LOGGER.warning(
        "Startup day-ahead prices for %s are unavailable; fetching current-day prices for %s so the dashboard is populated",
        target.date(),
        current_day.date(),
    )
    collect_with_retries(client, mqtt, settings, current_day)


def _target_day(now: datetime) -> datetime:
    return now.astimezone(AMSTERDAM_TZ) + timedelta(days=1)


def main() -> None:
    configure_container_logging(format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        LOGGER.critical("ENTSOE_API_KEY is required; minyad-trade cannot fetch ENTSO-E prices without it")
        raise RuntimeError("ENTSOE_API_KEY is required")

    store = SettingsStore()
    mqtt = MinyadMqttClient("minyad-trade")
    mqtt.start()
    mqtt.subscribe(f"{MQTT_TOPICS.settings_prefix}/#", store.apply_mqtt)
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=api_key)
    LOGGER.info(
        "minyad-trade started with settings: %s (ENTSOE_API_KEY configured length=%d)",
        store.get(),
        len(api_key),
    )

    startup_now = datetime.now(AMSTERDAM_TZ)
    collect_startup_prices(client, mqtt, store.get(), startup_now)

    while True:
        settings = store.get()
        now = datetime.now(AMSTERDAM_TZ)
        poll_at = next_poll_time(now, settings.poll_time_local)
        sleep_seconds = max(1.0, (poll_at - now).total_seconds())
        LOGGER.info("Next EPEX day-ahead poll scheduled at %s", poll_at.isoformat())
        time.sleep(sleep_seconds)
        collect_with_retries(client, mqtt, store.get(), _target_day(datetime.now(AMSTERDAM_TZ)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOGGER.exception("minyad-trade stopped after an unhandled error")
        raise
