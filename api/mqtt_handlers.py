"""MQTT callback/publish functions and the retained-status fallback fetch.

Reads and writes api.state's locks/caches and mqtt client directly.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from threading import Event
from typing import Any
from uuid import uuid4

import paho.mqtt.client as paho_mqtt

try:
    from api.payload_helpers import (
        battery_health_component,
        component_status,
        grid_health_component,
        mqtt_status_key,
        solar_health_component,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        battery_health_component,
        component_status,
        grid_health_component,
        mqtt_status_key,
        solar_health_component,
    )
try:
    from api.state import (
        LAST_RETAINED_FETCH,
        MQTT_BATTERY_SETTING_TOPICS,
        MQTT_EVENTS,
        MQTT_STATUS,
        MQTT_STATUS_KEYS,
        MQTT_STATUS_LOCK,
        MQTT_TRADE_SETTING_TOPICS,
        RETAINED_STATUS_TIMEOUT_SECONDS,
        STARTUP_AT,
        TRADE_PRICE_CACHE,
        TRADE_PRICE_CACHE_LOCK,
        mqtt,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        LAST_RETAINED_FETCH,
        MQTT_BATTERY_SETTING_TOPICS,
        MQTT_EVENTS,
        MQTT_STATUS,
        MQTT_STATUS_KEYS,
        MQTT_STATUS_LOCK,
        MQTT_TRADE_SETTING_TOPICS,
        RETAINED_STATUS_TIMEOUT_SECONDS,
        STARTUP_AT,
        TRADE_PRICE_CACHE,
        TRADE_PRICE_CACHE_LOCK,
        mqtt,
    )

LOGGER = logging.getLogger(__name__)


def handle_trade_price_mqtt(topic: str, payload: bytes) -> None:
    parts = topic.split("/")
    if len(parts) != 6 or parts[:4] != ["minyad", "trade", "prices", "da"] or parts[5] != "full":
        return
    day = parts[4]
    try:
        prices = json.loads(payload.decode())
    except json.JSONDecodeError:
        LOGGER.warning("Ignoring invalid day-ahead price payload on %s", topic)
        return
    if not isinstance(prices, list):
        LOGGER.warning("Ignoring non-list day-ahead price payload on %s", topic)
        return
    normalized = []
    for point in prices:
        if not isinstance(point, dict):
            continue
        try:
            price = float(point["price_eur_kwh"])
            starts_at = str(point["starts_at"])
        except (KeyError, TypeError, ValueError):
            continue
        normalized.append({
            "date": str(point.get("date") or day),
            "hour": str(point.get("hour") or starts_at[11:13]),
            "starts_at": starts_at,
            "price_eur_kwh": price,
        })
    normalized.sort(key=lambda item: item["starts_at"])
    with TRADE_PRICE_CACHE_LOCK:
        TRADE_PRICE_CACHE[day] = normalized
    LOGGER.info("Cached %d day-ahead price points for %s", len(normalized), day)


def latest_trade_prices() -> list[dict[str, Any]]:
    with TRADE_PRICE_CACHE_LOCK:
        if not TRADE_PRICE_CACHE:
            return []
        day = max(TRADE_PRICE_CACHE)
        return list(TRADE_PRICE_CACHE[day])


def handle_status_mqtt(topic: str, payload: bytes) -> None:
    key = mqtt_status_key(topic)
    decoded = payload.decode()
    if key is None:
        LOGGER.debug("Ignoring unsupported status MQTT topic %s", topic)
        return
    LOGGER.debug("MQTT status update: topic=%s key=%s value=%r", topic, key, decoded)
    with MQTT_STATUS_LOCK:
        MQTT_STATUS[key] = decoded
    MQTT_EVENTS.append({
        "ts": datetime.now(UTC).isoformat(),
        "topic": topic,
        "payload": decoded[:200],
    })


def latest_mqtt_status() -> dict[str, str]:
    with MQTT_STATUS_LOCK:
        return dict(MQTT_STATUS)


def collect_retained_mqtt_status(timeout_seconds: float = RETAINED_STATUS_TIMEOUT_SECONDS) -> dict[str, str]:
    """Fetch retained status topics directly from MQTT as a startup/cache fallback."""
    attempt_ts = datetime.now(UTC).isoformat()
    LOGGER.debug(
        "collect_retained_mqtt_status: connecting to %s:%s timeout=%.1fs",
        mqtt.config.host, mqtt.config.port, timeout_seconds,
    )
    retained_status: dict[str, str] = {}
    received = Event()
    expected_keys = set(MQTT_STATUS_KEYS.values())

    def on_message(_client: paho_mqtt.Client, _userdata: object, message: paho_mqtt.MQTTMessage) -> None:
        key = mqtt_status_key(message.topic)
        if key is None:
            return
        decoded = message.payload.decode()
        LOGGER.debug(
            "collect_retained_mqtt_status: rx topic=%s key=%s value=%r retain=%d",
            message.topic, key, decoded, message.retain,
        )
        retained_status[key] = decoded
        if expected_keys.issubset(retained_status):
            received.set()

    client = paho_mqtt.Client(
        paho_mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"minyad-api-retained-{uuid4()}",
    )
    if mqtt.config.username:
        client.username_pw_set(mqtt.config.username, mqtt.config.password)
    client.on_message = on_message
    try:
        client.connect(mqtt.config.host, mqtt.config.port, mqtt.config.keepalive)
        LOGGER.debug("collect_retained_mqtt_status: connected, subscribing")
        client.loop_start()
        try:
            for topic in (
                "minyad/battery/+",
                "minyad/bridge/+",
                "minyad/control/+",
                "minyad/grid/+",
                "minyad/inverter/+",
                "minyad/solar/#",
            ):
                client.subscribe(topic)
                LOGGER.debug("collect_retained_mqtt_status: subscribed %s", topic)
            completed = received.wait(timeout_seconds)
            LOGGER.debug(
                "collect_retained_mqtt_status: done completed=%s keys=%d/%d received=%s",
                completed, len(retained_status), len(expected_keys), sorted(retained_status.keys()),
            )
        finally:
            client.loop_stop()
            client.disconnect()
    except OSError as exc:
        LOGGER.exception(
            "collect_retained_mqtt_status: connection failed host=%s port=%s: %s",
            mqtt.config.host, mqtt.config.port, exc,
        )
        LAST_RETAINED_FETCH.clear()
        LAST_RETAINED_FETCH.update({"ts": attempt_ts, "success": False, "error": str(exc), "result": {}})
        raise

    if retained_status:
        with MQTT_STATUS_LOCK:
            MQTT_STATUS.update(retained_status)
    LAST_RETAINED_FETCH.clear()
    LAST_RETAINED_FETCH.update({
        "ts": attempt_ts,
        "success": True,
        "all_keys_received": received.is_set(),
        "keys_received": sorted(retained_status.keys()),
        "result": retained_status,
    })
    return retained_status


def _mqtt_health_component() -> dict[str, Any]:
    mqtt_info = mqtt.connection_info()
    mqtt_ok = bool(mqtt_info.get("connected"))
    return component_status(
        "MQTT broker",
        "ok" if mqtt_ok else "error",
        "API MQTT client is connected" if mqtt_ok else "API MQTT client is not connected",
        endpoint=f"{mqtt_info.get('host')}:{mqtt_info.get('port')}",
        **mqtt_info,
    )


def build_health_status(cache: dict[str, Any], db_ok: bool, db_error: str | None = None) -> dict[str, Any]:
    api_status = component_status("API", "ok", "Minyad API process is serving requests", endpoint="/health")
    db_status = component_status(
        "PostgreSQL",
        "ok" if db_ok else "error",
        "Database query succeeded" if db_ok else f"Database query failed: {db_error or 'unknown error'}",
        endpoint="DB_URL",
    )
    mqtt_status = _mqtt_health_component()
    battery = battery_health_component(cache)
    grid = grid_health_component(cache)
    solar = solar_health_component(cache)

    endpoint_items = [
        component_status("Dashboard state", "ok", "Energy dashboard API endpoint is registered", endpoint="/api/state"),
        component_status("Forecast", "ok", "Forecast API endpoint is registered", endpoint="/api/forecast"),
        component_status("History curves", "ok", "Dashboard curves API endpoint is registered", endpoint="/dashboard/curves"),
        component_status(
            "Trade prices",
            "ok" if latest_trade_prices() else "warning",
            "Latest cached day-ahead prices available" if latest_trade_prices() else "No day-ahead prices cached yet",
            endpoint="/trade/prices",
        ),
        component_status("Agent messages", "ok", "Agent mailbox API endpoint is registered", endpoint="/api/messages"),
    ]
    components = [api_status, db_status, mqtt_status, battery, grid, solar, *endpoint_items]
    if any(item["status"] == "error" for item in components):
        overall = "error"
    elif any(item["status"] == "warning" for item in components):
        overall = "warning"
    else:
        overall = "ok"
    return {
        "status": overall,
        "generated_at": datetime.now(UTC).isoformat(),
        "startup_at": STARTUP_AT.isoformat(),
        "components": components,
    }


async def publish_trade_mqtt_settings(settings: dict[str, Any]) -> None:
    for key, topic in MQTT_TRADE_SETTING_TOPICS.items():
        if key in settings:
            mqtt.client.publish(topic, str(settings[key]), qos=0, retain=True)


async def publish_battery_mqtt_settings(settings: dict[str, Any]) -> None:
    for key, topic in MQTT_BATTERY_SETTING_TOPICS.items():
        if key in settings:
            mqtt.client.publish(topic, str(settings[key]), qos=0, retain=True)
