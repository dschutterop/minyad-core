"""Fetch EPEX/ENTSO-E day-ahead electricity prices and publish them to MQTT."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised indirectly by import-only tests
    requests = None
from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

LOGGER = logging.getLogger(__name__)


def _load_local_config() -> Any:
    """Load this service's config module without colliding with other config.py files."""
    spec = spec_from_file_location("minyad_trade_config", Path(__file__).with_name("config.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load minyad-trade config.py")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CONFIG = _load_local_config()
AMSTERDAM_TZ = _CONFIG.AMSTERDAM_TZ
DAY_AHEAD_DEFAULTS = _CONFIG.DAY_AHEAD_DEFAULTS
ENTSOE = _CONFIG.ENTSOE
MQTT_TOPICS = _CONFIG.MQTT_TOPICS
ALLOWED_ENTSOE_HOST = "web-api.tp.entsoe.eu"
UTC_OFFSET_SUFFIX = "+00:00"
METRICS_PORT = int(os.getenv("METRICS_PORT", "9105"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))

PROMETHEUS_REGISTRY = CollectorRegistry()
BUILD_INFO = Gauge("minyad_trade_build_info", "Build and version information for minyad-trade.", ["version"], registry=PROMETHEUS_REGISTRY)
ERRORS_TOTAL = Counter("minyad_trade_errors_total", "Errors observed by minyad-trade.", ["type"], registry=PROMETHEUS_REGISTRY)
LAST_FETCH_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "minyad_trade_last_fetch_success_timestamp_seconds",
    "Unix timestamp of the most recent successful day-ahead price fetch.",
    registry=PROMETHEUS_REGISTRY,
)
FETCH_FAILURES_TOTAL = Counter("minyad_trade_fetch_failures_total", "Day-ahead price fetch failures.", registry=PROMETHEUS_REGISTRY)
PRICES_AVAILABLE_HOURS = Gauge("minyad_trade_prices_available_hours", "Hours of future prices available from the last successful fetch.", registry=PROMETHEUS_REGISTRY)


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    LOGGER.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)


@dataclass(frozen=True)
class DayAheadSettings:
    bidding_zone: str = DAY_AHEAD_DEFAULTS.bidding_zone
    poll_time_local: str = DAY_AHEAD_DEFAULTS.poll_time_local
    retry_attempts: int = DAY_AHEAD_DEFAULTS.retry_attempts
    retry_interval_minutes: int = DAY_AHEAD_DEFAULTS.retry_interval_minutes
    entsoe_api_url: str = DAY_AHEAD_DEFAULTS.entsoe_api_url


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
                elif key == "entsoe_api_url":
                    updated = replace(current, entsoe_api_url=normalize_entsoe_api_url(raw))
                    apply_entsoe_api_url(updated.entsoe_api_url)
                else:
                    LOGGER.debug("Ignoring unknown trade setting topic=%s", topic)
                    return
            except ValueError:
                LOGGER.warning("Ignoring invalid trade setting topic=%s payload=%r", topic, raw)
                return
            if updated != current:
                self._settings = updated
                LOGGER.info("Trade settings updated: %s", updated)


def normalize_entsoe_api_url(value: str) -> str:
    url = value.strip() or DAY_AHEAD_DEFAULTS.entsoe_api_url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("entsoe_api_url must be an absolute HTTP(S) URL")
    if parsed.hostname != ALLOWED_ENTSOE_HOST or parsed.username or parsed.password or parsed.port is not None:
        raise ValueError(f"entsoe_api_url must point to {ALLOWED_ENTSOE_HOST}")
    return url


def apply_entsoe_api_url(url: str) -> None:
    normalize_entsoe_api_url(url)


def next_poll_time(now: datetime, poll_time_local: str) -> datetime:
    hour, minute = [int(part) for part in poll_time_local.split(":", 1)]
    candidate = now.astimezone(AMSTERDAM_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now.astimezone(AMSTERDAM_TZ):
        candidate += timedelta(days=1)
    return candidate


def _format_entsoe_period(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H00")


def _points_for_period(period: ET.Element, ns: dict[str, str]) -> list[dict[str, Any]]:
    start_element = period.find("./ns:timeInterval/ns:start", ns)
    if start_element is None or not start_element.text:
        return []
    interval_start = datetime.fromisoformat(start_element.text.replace("Z", UTC_OFFSET_SUFFIX))

    points: list[dict[str, Any]] = []
    for point in period.findall("./ns:Point", ns):
        position_element = point.find("ns:position", ns)
        price_element = point.find("ns:price.amount", ns)
        if position_element is None or price_element is None:
            continue
        timestamp = interval_start + timedelta(hours=int(position_element.text or "0") - 1)
        local_ts = timestamp.astimezone(AMSTERDAM_TZ)
        eur_mwh = float(price_element.text or "0")
        points.append({
            "date": local_ts.strftime("%Y-%m-%d"),
            "hour": local_ts.strftime("%H"),
            "starts_at": local_ts.isoformat(),
            "price_eur_kwh": eur_mwh / ENTSOE.price_unit_divisor,
        })
    return points


def parse_entsoe_publication_document(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    ns = {"ns": root.tag.removesuffix("Publication_MarketDocument").rstrip("}").lstrip("{")}
    prices: list[dict[str, Any]] = []

    for series in root.findall(".//ns:TimeSeries", ns):
        for period in series.findall(".//ns:Period", ns):
            prices.extend(_points_for_period(period, ns))

    return prices


def fetch_day_ahead(client: Any, settings: DayAheadSettings, target_day: datetime) -> list[dict[str, Any]]:
    start = datetime.combine(target_day.astimezone(AMSTERDAM_TZ).date(), datetime.min.time(), AMSTERDAM_TZ)
    end = start + timedelta(days=1)
    LOGGER.info("Fetching day-ahead prices zone=%s day=%s", settings.bidding_zone, start.date())
    params = {
        "securityToken": client.api_key,
        "documentType": "A44",
        "in_Domain": settings.bidding_zone,
        "out_Domain": settings.bidding_zone,
        "periodStart": _format_entsoe_period(start),
        "periodEnd": _format_entsoe_period(end),
    }
    response = client.session.get(settings.entsoe_api_url, params=params, timeout=30)
    response.raise_for_status()
    target_date = start.date().isoformat()
    return [point for point in parse_entsoe_publication_document(response.text) if point["date"] == target_date]


@dataclass(frozen=True)
class EntsoeXmlClient:
    api_key: str
    session: Any = requests


def publish_prices(mqtt: MinyadMqttClient, prices: list[dict[str, Any]]) -> None:
    if not prices:
        raise RuntimeError("No day-ahead prices returned")
    day = prices[0]["date"]
    prefix = f"{MQTT_TOPICS.day_ahead_price_prefix}/{day}"
    full_payload = json.dumps(prices, separators=(",", ":"))
    mqtt.publish(f"{prefix}/{MQTT_TOPICS.day_ahead_full_suffix}", full_payload, retain=True)
    for point in prices:
        mqtt.publish(f"{prefix}/{point['hour']}", point["price_eur_kwh"], retain=True)
    mqtt.publish("minyad/market/signals", json.dumps(_price_vector_signal(day, prices), separators=(",", ":")), retain=True)
    LAST_FETCH_SUCCESS_TIMESTAMP_SECONDS.set(time.time())
    PRICES_AVAILABLE_HOURS.set(_prices_available_hours(prices, datetime.now(AMSTERDAM_TZ)))
    LOGGER.info("Published %d day-ahead price points for %s", len(prices), day)


def _price_vector_signal(day: str, prices: list[dict[str, Any]]) -> dict[str, Any]:
    starts = [datetime.fromisoformat(str(point["starts_at"]).replace("Z", UTC_OFFSET_SUFFIX)) for point in prices]
    valid_from = min(starts)
    valid_until = max(starts) + timedelta(hours=1)
    created_at = datetime.now(timezone.utc).astimezone(AMSTERDAM_TZ)
    return {
        "id": f"minyad-trade:price-vector:{day}",
        "source": "minyad-trade",
        "type": "price_vector",
        "created_at": created_at.isoformat(),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "priority": 50,
        "hard": False,
        "payload": {
            "slot_seconds": 900,
            "slots": [
                {
                    "start": (start + timedelta(minutes=15 * quarter)).isoformat(),
                    "price_import_eur_kwh": float(point["price_eur_kwh"]),
                    "price_export_eur_kwh": 0.0,
                }
                for point, start in zip(prices, starts, strict=False)
                for quarter in range(4)
            ],
        },
    }


def _prices_available_hours(prices: list[dict[str, Any]], now: datetime) -> float:
    latest_until: datetime | None = None
    for point in prices:
        try:
            starts_at = datetime.fromisoformat(str(point["starts_at"]).replace("Z", UTC_OFFSET_SUFFIX))
        except (KeyError, ValueError):
            continue
        until = starts_at + timedelta(hours=1)
        if latest_until is None or until > latest_until:
            latest_until = until
    if latest_until is None:
        return 0.0
    return max(0.0, (latest_until - now.astimezone(latest_until.tzinfo)).total_seconds() / 3600.0)


def collect_once(client: Any, mqtt: MinyadMqttClient, settings: DayAheadSettings, target_day: datetime) -> None:
    prices = fetch_day_ahead(client, settings, target_day)
    publish_prices(mqtt, prices)


def collect_with_retries(client: Any, mqtt: MinyadMqttClient, settings: DayAheadSettings, target_day: datetime) -> bool:
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            collect_once(client, mqtt, settings, target_day)
            return True
        except Exception as exc:  # ENTSO-E uses several exception types for unavailable data.
            FETCH_FAILURES_TOTAL.inc()
            ERRORS_TOTAL.labels(type="fetch").inc()
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
    try:
        collect_once(client, mqtt, settings, target)
        return
    except Exception as exc:  # ENTSO-E uses several exception types for unavailable data.
        FETCH_FAILURES_TOTAL.inc()
        ERRORS_TOTAL.labels(type="fetch").inc()
        LOGGER.warning(
            "Startup day-ahead prices for %s are unavailable; immediately fetching current-day prices so the dashboard is populated: %r",
            target.date(),
            exc,
        )

    current_day = now.astimezone(AMSTERDAM_TZ)
    try:
        collect_once(client, mqtt, settings, current_day)
        LOGGER.info(
            "Published current-day prices for %s during startup; continuing to retry target day %s",
            current_day.date(),
            target.date(),
        )
    except Exception as exc:  # ENTSO-E uses several exception types for unavailable data.
        FETCH_FAILURES_TOTAL.inc()
        ERRORS_TOTAL.labels(type="fetch").inc()
        LOGGER.warning(
            "Current-day prices for %s are unavailable during startup; retrying target day %s with configured retry policy: %r",
            current_day.date(),
            target.date(),
            exc,
        )
    collect_with_retries(client, mqtt, settings, target)


def _target_day(now: datetime) -> datetime:
    return now.astimezone(AMSTERDAM_TZ) + timedelta(days=1)


def main() -> None:
    configure_container_logging(format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    start_metrics_server()
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        LOGGER.critical("ENTSOE_API_KEY is required; minyad-trade cannot fetch ENTSO-E prices without it")
        raise RuntimeError("ENTSOE_API_KEY is required")

    store = SettingsStore()
    mqtt = MinyadMqttClient("minyad-trade")
    mqtt.start()
    mqtt.subscribe(f"{MQTT_TOPICS.settings_prefix}/#", store.apply_mqtt)
    client = EntsoeXmlClient(api_key=api_key)
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
