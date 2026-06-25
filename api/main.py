"""Minyad REST API."""

from __future__ import annotations

import asyncio
import json
import math
import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
import httpx
import paho.mqtt.client as paho_mqtt
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal, get_session
from shared.mqtt_client import MinyadMqttClient

app = FastAPI(title="Minyad API")
mqtt = MinyadMqttClient("minyad-api")
LOGGER = logging.getLogger(__name__)

STARTUP_AT = datetime.now(timezone.utc)
MQTT_EVENTS: deque[dict[str, str]] = deque(maxlen=100)
LAST_RETAINED_FETCH: dict[str, Any] = {}
TRADE_PRICE_CACHE_LOCK = Lock()
TRADE_PRICE_CACHE: dict[str, list[dict[str, Any]]] = {}
_debug_enabled = False

MQTT_STATUS_KEYS = {
    "minyad/battery/soc": "soc",
    "minyad/battery/soh": "soh",
    "minyad/battery/power_w": "power_w",
    "minyad/battery/voltage": "voltage",
    "minyad/battery/voltage_v": "voltage",
    "minyad/battery/mode": "mode",
    "minyad/battery/mode_label": "mode_label",
    "minyad/battery/charge_i": "charge_i",
    "minyad/bridge/status": "bridge_status",
    "minyad/bridge/last_seen": "bridge_last_seen",
    "minyad/inverter/grid_power_w": "grid_power_w",
    "minyad/control/state": "state",
    "minyad/control/override_mode": "override_mode",
    "minyad/control/setpoint_w": "setpoint_w",
    "minyad/control/discharge_w": "discharge_w",
}

GRID_STATUS_KEYS = {
    "minyad/grid/delivered_w": "grid_delivered_w",
    "minyad/grid/returned_w": "grid_returned_w",
    "minyad/grid/net_power_w": "grid_net_power_w",
    "minyad/grid/phase_delivered_l1_w": "grid_phase_delivered_l1_w",
    "minyad/grid/phase_delivered_l2_w": "grid_phase_delivered_l2_w",
    "minyad/grid/phase_delivered_l3_w": "grid_phase_delivered_l3_w",
    "minyad/grid/phase_returned_l1_w": "grid_phase_returned_l1_w",
    "minyad/grid/phase_returned_l2_w": "grid_phase_returned_l2_w",
    "minyad/grid/phase_returned_l3_w": "grid_phase_returned_l3_w",
    "minyad/grid/voltage_l1_v": "grid_voltage_l1_v",
    "minyad/grid/voltage_l2_v": "grid_voltage_l2_v",
    "minyad/grid/voltage_l3_v": "grid_voltage_l3_v",
    "minyad/grid/timestamp": "grid_timestamp",
    "minyad/grid/status": "grid_status",
}
SOLAR_STATUS_KEYS = {
    "minyad/solar/production_w": "solar_power_w",
    "minyad/solar/production_updated_at": "solar_updated_at",
    "minyad/solar/bridge/status": "solar_bridge_status",
    "minyad/solar/bridge/last_seen": "solar_bridge_last_seen",
}
MQTT_STATUS_KEYS.update(GRID_STATUS_KEYS)
MQTT_STATUS_KEYS.update(SOLAR_STATUS_KEYS)
MQTT_STATUS_LOCK = Lock()
MQTT_STATUS: dict[str, str] = {}
RETAINED_STATUS_TIMEOUT_SECONDS = 1.0
MQTT_BATTERY_SETTINGS_PREFIX = "minyad/settings/battery"
MQTT_BATTERY_SETTING_TOPICS = {
    "inverter_poll_interval_s": f"{MQTT_BATTERY_SETTINGS_PREFIX}/inverter_poll_interval_s",
    "soc_floor": f"{MQTT_BATTERY_SETTINGS_PREFIX}/soc_floor",
    "soc_ceiling": f"{MQTT_BATTERY_SETTINGS_PREFIX}/soc_ceiling",
}
MQTT_TRADE_SETTINGS_PREFIX = "minyad/settings/trade"
MQTT_TRADE_SETTING_TOPICS = {
    "bidding_zone": f"{MQTT_TRADE_SETTINGS_PREFIX}/bidding_zone",
    "poll_time_local": f"{MQTT_TRADE_SETTINGS_PREFIX}/poll_time_local",
    "retry_attempts": f"{MQTT_TRADE_SETTINGS_PREFIX}/retry_attempts",
    "retry_interval_minutes": f"{MQTT_TRADE_SETTINGS_PREFIX}/retry_interval_minutes",
    "entsoe_api_url": f"{MQTT_TRADE_SETTINGS_PREFIX}/entsoe_api_url",
}

BATTERY_KEYS = {
    "start_w": (100, 5000),
    "stop_w": (0, 5000),
    "start_duration": (10, 3600),
    "stop_duration": (10, 3600),
    "cooldown": (60, 7200),
    "max_charge_w": (100, 5000),
    "max_charge_a": (1, 200),
    "max_discharge_w": (0, 5000),
    "soc_floor": (0, 100),
    "soc_ceiling": (0, 100),
    "nominal_v": (40, 60),
    "inverter_retries": (1, 10),
    "inverter_delay": (1, 30),
    "inverter_poll_interval_s": (1, 3600),
}
TEXT_KEYS = {"inverter_ip"}

STRATEGY_DEFAULTS = {
    "ghi_solar_rich_threshold": "4.5",
    "ghi_solar_poor_threshold": "1.5",
    "dynamic_tariff_ceiling_eur_kwh": "0.10",
    "daily_recalculate_local_time": "22:00",
    "ramp_floor_w": "200",
    "ramp_ceiling_w": "1000",
    "ramp_hold_seconds": "120",
}
CLAUDE_AGENT_DEFAULTS = {
    "enabled": "false",
    "token_guard_enabled": "true",
    "min_tokens_remaining": "5000",
}

TRADE_DEFAULTS = {
    "bidding_zone": "10YNL----------L",
    "poll_time_local": "13:30",
    "retry_attempts": "3",
    "retry_interval_minutes": "15",
    "entsoe_api_url": "https://web-api.tp.entsoe.eu/api",
}
TRADE_NUMERIC_LIMITS = {
    "retry_attempts": (1, 24),
    "retry_interval_minutes": (1, 240),
}

STRATEGY_NUMERIC_LIMITS = {
    "ghi_solar_rich_threshold": (0.0, 20.0),
    "ghi_solar_poor_threshold": (0.0, 20.0),
    "dynamic_tariff_ceiling_eur_kwh": (-1.0, 5.0),
    "ramp_floor_w": (0, 5000),
    "ramp_ceiling_w": (1, 5000),
    "ramp_hold_seconds": (0, 3600),
}
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_LATITUDE = 51.9788
FORECAST_LONGITUDE = 4.3158
SOLAR_PEAK_W = 5000
SOLAR_FORECAST_EFFICIENCY = 0.80
OPEN_METEO_RETRY_ATTEMPTS = max(1, int(os.getenv("OPEN_METEO_RETRY_ATTEMPTS", "3")))
OPEN_METEO_RETRY_BASE_DELAY_SECONDS = float(os.getenv("OPEN_METEO_RETRY_BASE_DELAY_SECONDS", "2"))


def _apply_log_level(debug: bool) -> None:
    global _debug_enabled
    _debug_enabled = debug
    level = logging.DEBUG if debug else logging.INFO
    logging.getLogger().setLevel(level)
    logging.getLogger("paho").setLevel(level)
    LOGGER.info("Log level set to %s (debug_logging=%s)", logging.getLevelName(level), debug)


async def _refresh_debug_setting() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(text("select value from settings where key = 'system.debug_logging'"))
                val = result.scalar_one_or_none() or "false"
                new_debug = val == "true"
                if new_debug != _debug_enabled:
                    _apply_log_level(new_debug)
        except Exception:
            LOGGER.debug("Could not refresh debug setting from DB")


def solar_dynamic_status_key(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) == 5 and parts[:3] == ["minyad", "solar", "inverter"] and parts[4] in {"power_w", "last_report_at"}:
        return f"solar_inverter_{parts[3]}_{parts[4]}"
    if len(parts) == 5 and parts[:3] == ["minyad", "solar", "array"] and parts[4] == "power_w":
        return f"solar_array_{parts[3]}_power_w"
    return None


def mqtt_status_key(topic: str) -> str | None:
    return MQTT_STATUS_KEYS.get(topic) or solar_dynamic_status_key(topic)


def handle_trade_price_mqtt(topic: str, payload: bytes) -> None:
    parts = topic.split("/")
    if len(parts) != 6 or parts[:4] != ["minyad", "trade", "prices", "da"] or parts[5] != "full":
        return
    day = parts[4]
    try:
        prices = json.loads(payload.decode())
    except json.JSONDecodeError:
        LOGGER.warning("Ignoring invalid ENTSO-E price payload on %s", topic)
        return
    if not isinstance(prices, list):
        LOGGER.warning("Ignoring non-list ENTSO-E price payload on %s", topic)
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
    LOGGER.info("Cached %d ENTSO-E day-ahead price points for %s", len(normalized), day)


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
        "ts": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "payload": decoded[:200],
    })


def latest_mqtt_status() -> dict[str, str]:
    with MQTT_STATUS_LOCK:
        return dict(MQTT_STATUS)


def cached_status_is_incomplete(payload: dict[str, Any]) -> bool:
    required_keys = (
        "soc",
        "soh",
        "power_w",
        "voltage",
        "mode",
        "bridge_status",
        "bridge_last_seen",
    )
    return any(key not in payload or payload[key] in (None, "") for key in required_keys)


def collect_retained_mqtt_status(timeout_seconds: float = RETAINED_STATUS_TIMEOUT_SECONDS) -> dict[str, str]:
    """Fetch retained status topics directly from MQTT as a startup/cache fallback."""
    global LAST_RETAINED_FETCH
    attempt_ts = datetime.now(timezone.utc).isoformat()
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
        LAST_RETAINED_FETCH = {"ts": attempt_ts, "success": False, "error": str(exc), "result": {}}
        raise

    if retained_status:
        with MQTT_STATUS_LOCK:
            MQTT_STATUS.update(retained_status)
    LAST_RETAINED_FETCH = {
        "ts": attempt_ts,
        "success": True,
        "all_keys_received": received.is_set(),
        "keys_received": sorted(retained_status.keys()),
        "result": retained_status,
    }
    return retained_status



def coerce_int_status_value(key: str, value: Any) -> int | Any:
    if value in (None, ""):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-integer status value for %s: %r", key, value)
        return value


def coerce_float_status_value(key: str, value: Any) -> float | Any:
    if value in (None, ""):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-float status value for %s: %r", key, value)
        return value


def grid_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.startswith("grid_") or key.startswith("solar_")
    }


def battery_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("grid_") or key == "grid_power_w"
    }


def derive_battery_state(payload: dict[str, Any], fallback: str = "IDLE") -> str:
    """Derive actual battery activity from bridge telemetry.

    The control state describes what Minyad asked the inverter to do, but the
    bridge telemetry is the source of truth for what the battery is doing.  A
    small deadband avoids reporting activity from inverter measurement noise.
    """
    deadband_w = 25
    power_w = _numeric_w(payload, "power_w")
    mode_text = " ".join(
        str(payload.get(key, "")).strip().lower()
        for key in ("mode", "mode_label")
        if payload.get(key) not in (None, "")
    )

    if power_w is not None and abs(power_w) > deadband_w:
        if "discharge" in mode_text:
            return "DISCHARGING"
        if "charge" in mode_text:
            return "CHARGING"
        return "DISCHARGING" if power_w > 0 else "CHARGING"

    if "discharge" in mode_text:
        return "DISCHARGING"
    if "charge" in mode_text:
        return "CHARGING"
    return fallback or "IDLE"


def solar_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    inverters: dict[str, dict[str, Any]] = {}
    arrays: dict[str, int | str] = {}
    for key, value in payload.items():
        if key.startswith("solar_inverter_") and key.endswith("_power_w"):
            serial = key.removeprefix("solar_inverter_").removesuffix("_power_w")
            inverters.setdefault(serial, {"serial": serial})["power_w"] = coerce_int_status_value(key, value)
        elif key.startswith("solar_inverter_") and key.endswith("_last_report_at"):
            serial = key.removeprefix("solar_inverter_").removesuffix("_last_report_at")
            inverters.setdefault(serial, {"serial": serial})["last_report_at"] = value
        elif key.startswith("solar_array_") and key.endswith("_power_w"):
            array = key.removeprefix("solar_array_").removesuffix("_power_w")
            arrays[array] = coerce_int_status_value(key, value)
    inverter_list = sorted(inverters.values(), key=lambda item: str(item.get("serial", "")))
    total = payload.get("solar_power_w")
    if total is None:
        numeric = [item.get("power_w") for item in inverter_list]
        total = sum(value for value in numeric if isinstance(value, int))
    else:
        total = coerce_int_status_value("solar_power_w", total)
    return {
        "power_w": total,
        "updated_at": payload.get("solar_updated_at"),
        "bridge_status": payload.get("solar_bridge_status"),
        "bridge_last_seen": payload.get("solar_bridge_last_seen"),
        "inverters": inverter_list,
        "arrays": arrays,
    }


def coerce_grid_status(payload: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(payload)
    int_keys = {
        "solar_power_w",
        "grid_delivered_w",
        "grid_returned_w",
        "grid_net_power_w",
        "grid_phase_delivered_l1_w",
        "grid_phase_delivered_l2_w",
        "grid_phase_delivered_l3_w",
        "grid_phase_returned_l1_w",
        "grid_phase_returned_l2_w",
        "grid_phase_returned_l3_w",
    }
    float_keys = {"grid_voltage_l1_v", "grid_voltage_l2_v", "grid_voltage_l3_v"}
    for key in int_keys:
        if key in coerced:
            coerced[key] = coerce_int_status_value(key, coerced[key])
    for key in float_keys:
        if key in coerced:
            coerced[key] = coerce_float_status_value(key, coerced[key])
    return coerced

def parse_bridge_last_seen(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def enrich_bridge_health(payload: dict[str, Any]) -> None:
    last_seen_value = payload.get("bridge_last_seen")
    last_seen = parse_bridge_last_seen(last_seen_value if isinstance(last_seen_value, str) else None)
    payload["bridge_last_seen_valid"] = False
    if last_seen is None:
        payload["bridge_last_seen_error"] = "missing or invalid bridge last_seen"
        if payload.get("bridge_status") == "online":
            payload["available"] = False
        return

    age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
    payload["bridge_last_seen_age_seconds"] = max(0, round(age_seconds))
    payload["bridge_last_seen_valid"] = age_seconds <= 60
    if age_seconds > 60:
        payload["bridge_last_seen_error"] = "bridge last_seen is older than 60 seconds"
        payload["available"] = False


def component_status(name: str, status: Literal["ok", "warning", "error"], detail: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    payload.update(extra)
    return payload


def value_is_fresh_iso(value: Any, max_age_seconds: int = 120) -> tuple[bool, int | None]:
    if not isinstance(value, str) or not value:
        return False, None
    parsed = parse_bridge_last_seen(value)
    if parsed is None:
        return False, None
    age = max(0, round((datetime.now(timezone.utc) - parsed).total_seconds()))
    return age <= max_age_seconds, age


def build_health_status(cache: dict[str, Any], db_ok: bool, db_error: str | None = None) -> dict[str, Any]:
    api_status = component_status("API", "ok", "Minyad API process is serving requests", endpoint="/health")
    db_status = component_status(
        "PostgreSQL",
        "ok" if db_ok else "error",
        "Database query succeeded" if db_ok else f"Database query failed: {db_error or 'unknown error'}",
        endpoint="DB_URL",
    )
    mqtt_info = mqtt.connection_info()
    mqtt_ok = bool(mqtt_info.get("connected"))
    mqtt_status = component_status(
        "MQTT broker",
        "ok" if mqtt_ok else "error",
        "API MQTT client is connected" if mqtt_ok else "API MQTT client is not connected",
        endpoint=f"{mqtt_info.get('host')}:{mqtt_info.get('port')}",
        **mqtt_info,
    )

    battery_required = ("soc", "power_w", "voltage", "mode", "bridge_status", "bridge_last_seen")
    battery_missing = [key for key in battery_required if not cache.get(key)]
    bridge_fresh, bridge_age = value_is_fresh_iso(cache.get("bridge_last_seen"), 90)
    battery_ok = not battery_missing and str(cache.get("bridge_status", "")).lower() == "online" and bridge_fresh
    battery = component_status(
        "Battery / GoodWe bridge",
        "ok" if battery_ok else "warning",
        "GoodWe bridge telemetry is current" if battery_ok else "Missing, stale, or offline GoodWe telemetry",
        endpoint="/battery/status",
        missing_keys=battery_missing,
        bridge_status=cache.get("bridge_status"),
        last_seen=cache.get("bridge_last_seen"),
        age_seconds=bridge_age,
    )

    grid_required = ("grid_net_power_w", "grid_timestamp", "grid_status")
    grid_missing = [key for key in grid_required if not cache.get(key)]
    grid_fresh, grid_age = value_is_fresh_iso(cache.get("grid_timestamp"), 120)
    grid_ok = not grid_missing and grid_fresh
    grid = component_status(
        "DSMR / grid meter",
        "ok" if grid_ok else "warning",
        "Grid meter telemetry is current" if grid_ok else "Missing or stale DSMR grid telemetry",
        endpoint="/dsmr/status",
        missing_keys=grid_missing,
        grid_status=cache.get("grid_status"),
        last_seen=cache.get("grid_timestamp"),
        age_seconds=grid_age,
    )

    solar_fresh, solar_age = value_is_fresh_iso(cache.get("solar_updated_at") or cache.get("solar_bridge_last_seen"), 180)
    inverter_keys = [key for key in cache if key.startswith("solar_inverter_") and key.endswith("_power_w")]
    solar_ok = bool(cache.get("solar_power_w") is not None or inverter_keys) and solar_fresh
    solar = component_status(
        "Solar / Enphase bridge",
        "ok" if solar_ok else "warning",
        "Solar production telemetry is current" if solar_ok else "Missing or stale solar telemetry",
        endpoint="/solar/status",
        bridge_status=cache.get("solar_bridge_status"),
        last_seen=cache.get("solar_updated_at") or cache.get("solar_bridge_last_seen"),
        age_seconds=solar_age,
        inverter_count=len(inverter_keys),
    )

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
    overall = "error" if any(item["status"] == "error" for item in components) else "warning" if any(item["status"] == "warning" for item in components) else "ok"
    return {
        "status": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "startup_at": STARTUP_AT.isoformat(),
        "components": components,
    }


class ApiKeyCreate(BaseModel):
    name: str


class SystemSettingsUpdate(BaseModel):
    debug_logging: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None


class ClaudeAgentSettingsUpdate(BaseModel):
    enabled: bool | None = None
    token_guard_enabled: bool | None = None
    min_tokens_remaining: int | None = Field(default=None, ge=0)


class AssetSteeringSettingsUpdate(BaseModel):
    ghi_solar_rich_threshold: float | None = None
    ghi_solar_poor_threshold: float | None = None
    dynamic_tariff_ceiling_eur_kwh: float | None = None
    daily_recalculate_local_time: str | None = None
    ramp_floor_w: int | None = None
    ramp_ceiling_w: int | None = None
    ramp_hold_seconds: int | None = None

    @field_validator("daily_recalculate_local_time")
    @classmethod
    def validate_local_time(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("daily_recalculate_local_time must use HH:MM format") from exc
        return value


class AgentDecisionRequest(BaseModel):
    action_taken: Literal["charge", "discharge", "hold"]
    setpoint_w: int | None = None
    reasoning: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    input_snapshot: dict[str, Any]
    dry_run: bool = True
    model: str = "claude-sonnet-4-6"


class AgentBatteryControlRequest(BaseModel):
    setpoint_w: int = Field(ge=-5000, le=5000)
    duration_minutes: int = Field(default=15, ge=1, le=240)


class AgentMessageCreate(BaseModel):
    sender: Literal["agent", "operator"]
    category: Literal["anomaly", "suggestion", "info", "reply"]
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1)
    related_decision_id: int | None = None
    thread_id: int | None = None
    severity: Literal["low", "normal", "high"] = "normal"


class BatteryOverrideRequest(BaseModel):
    mode: Literal["none", "force_on", "force_off", "force_discharge", "pause"]
    watts: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_required_fields(self) -> "BatteryOverrideRequest":
        if self.mode in {"force_on", "force_discharge"} and self.watts is None:
            raise ValueError("watts is required for force_on and force_discharge")
        if self.mode == "pause" and self.duration_seconds is None:
            raise ValueError("duration_seconds is required for pause")
        return self


class TradeSettingsUpdate(BaseModel):
    bidding_zone: str | None = None
    poll_time_local: str | None = None
    retry_attempts: int | None = Field(default=None, ge=1, le=24)
    retry_interval_minutes: int | None = Field(default=None, ge=1, le=240)
    entsoe_api_url: str | None = None

    @field_validator("poll_time_local")
    @classmethod
    def validate_poll_time(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("poll_time_local must use HH:MM format") from exc
        return value

    @field_validator("entsoe_api_url")
    @classmethod
    def validate_entsoe_api_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("entsoe_api_url must be an absolute HTTP(S) URL")
        return url


class BatterySettingsUpdate(BaseModel):
    start_w: int | None = None
    stop_w: int | None = None
    start_duration: int | None = None
    stop_duration: int | None = None
    cooldown: int | None = None
    max_charge_w: int | None = None
    max_charge_a: int | None = Field(default=None, ge=1, le=200)
    nominal_v: int | None = Field(default=None, ge=40, le=60)
    max_discharge_w: int | None = None
    soc_floor: int | None = Field(default=None, ge=0, le=100)
    soc_ceiling: int | None = Field(default=None, ge=0, le=100)
    inverter_ip: str | None = None
    inverter_retries: int | None = None
    inverter_delay: int | None = None
    inverter_poll_interval_s: int | None = Field(default=None, ge=1)

    @field_validator("inverter_ip")
    @classmethod
    def validate_ip(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split(".")
        if len(parts) != 4 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            raise ValueError("inverter_ip must be a valid IPv4 address")
        return value


async def publish_trade_mqtt_settings(settings: dict[str, Any] | None = None) -> None:
    if settings is None:
        async with AsyncSessionLocal() as session:
            settings = await trade_settings(session)
    for key, topic in MQTT_TRADE_SETTING_TOPICS.items():
        if key in settings:
            mqtt.client.publish(topic, str(settings[key]), qos=0, retain=True)


async def publish_battery_mqtt_settings(settings: dict[str, Any] | None = None) -> None:
    if settings is None:
        async with AsyncSessionLocal() as session:
            settings = await battery_settings(session)
    for key, topic in MQTT_BATTERY_SETTING_TOPICS.items():
        if key in settings:
            mqtt.client.publish(topic, str(settings[key]), qos=0, retain=True)

@app.on_event("startup")
async def startup() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("select value from settings where key = 'system.debug_logging'"))
        val = result.scalar_one_or_none() or "false"
        _apply_log_level(val == "true")
    mqtt.start()
    mqtt.subscribe("minyad/battery/+", handle_status_mqtt)
    mqtt.subscribe("minyad/bridge/+", handle_status_mqtt)
    mqtt.subscribe("minyad/control/+", handle_status_mqtt)
    mqtt.subscribe("minyad/grid/+", handle_status_mqtt)
    mqtt.subscribe("minyad/inverter/+", handle_status_mqtt)
    mqtt.subscribe("minyad/solar/#", handle_status_mqtt)
    mqtt.subscribe("minyad/trade/prices/da/+/full", handle_trade_price_mqtt)
    await publish_battery_mqtt_settings()
    await publish_trade_mqtt_settings()
    asyncio.create_task(_refresh_debug_setting())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/status")
async def health_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    db_ok = True
    db_error = None
    try:
        await session.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - depends on deployment database state
        db_ok = False
        db_error = str(exc)
    with MQTT_STATUS_LOCK:
        cache = dict(MQTT_STATUS)
    return build_health_status(cache, db_ok=db_ok, db_error=db_error)


@app.get("/debug/status")
async def debug_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(text("select value from settings where key = 'system.debug_logging'"))
    debug_val = result.scalar_one_or_none() or "false"
    with MQTT_STATUS_LOCK:
        cache = dict(MQTT_STATUS)
    with mqtt._subscriptions_lock:
        subscriptions = list(mqtt._subscriptions.keys())
    missing_keys = [k for k in ("soc", "soh", "power_w", "voltage", "mode", "bridge_status", "bridge_last_seen") if not cache.get(k)]
    return {
        "startup_at": STARTUP_AT.isoformat(),
        "debug_logging": debug_val == "true",
        "log_level": logging.getLevelName(logging.getLogger().level),
        "mqtt": mqtt.connection_info(),
        "mqtt_subscriptions": subscriptions,
        "mqtt_status_cache": cache,
        "mqtt_status_cache_complete": not cached_status_is_incomplete(cache),
        "mqtt_status_missing_keys": missing_keys,
        "recent_mqtt_events": list(MQTT_EVENTS)[-50:],
        "last_retained_fetch": LAST_RETAINED_FETCH,
        "claude_agent": await claude_agent_settings(session),
    }


@app.get("/system-settings")
async def get_system_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key in ('system.debug_logging', 'system.theme')"))
    settings = {row.key: row.value for row in result}
    return {
        "debug_logging": settings.get("system.debug_logging", "false") == "true",
        "theme": settings.get("system.theme", "system"),
    }


@app.put("/system-settings")
async def update_system_settings(update: SystemSettingsUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if update.debug_logging is not None:
        val = "true" if update.debug_logging else "false"
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values ('system.debug_logging', :val, false, now())
                on conflict (key) do update set value=:val, updated_at=now()
            """),
            {"val": val},
        )
        _apply_log_level(update.debug_logging)
    if update.theme is not None:
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values ('system.theme', :val, false, now())
                on conflict (key) do update set value=:val, updated_at=now()
            """),
            {"val": update.theme},
        )
    if update.debug_logging is not None or update.theme is not None:
        await session.commit()
    return await get_system_settings(session)


async def claude_agent_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'claude_agent.%'"))
    values = {row.key.removeprefix("claude_agent."): row.value for row in result}
    merged = {**CLAUDE_AGENT_DEFAULTS, **values}
    enabled = str(merged["enabled"]).lower() in {"1", "true", "yes", "on"}
    token_guard_enabled = str(merged["token_guard_enabled"]).lower() in {"1", "true", "yes", "on"}
    min_tokens_remaining = max(0, int(merged["min_tokens_remaining"]))
    return {
        "enabled": enabled,
        "token_guard_enabled": token_guard_enabled,
        "min_tokens_remaining": min_tokens_remaining,
        "status": "enabled" if enabled else "disabled",
        "token_guard_status": "enabled" if token_guard_enabled else "disabled",
    }


@app.get("/api/claude-agent/settings")
@app.get("/claude-agent/settings")
async def get_claude_agent_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await claude_agent_settings(session)


@app.patch("/api/claude-agent/settings")
@app.patch("/claude-agent/settings")
@app.put("/api/claude-agent/settings")
@app.put("/claude-agent/settings")
async def update_claude_agent_settings(
    update: ClaudeAgentSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    for key, value in data.items():
        stored = "true" if isinstance(value, bool) and value else "false" if isinstance(value, bool) else str(value)
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
            """),
            {"key": f"claude_agent.{key}", "value": stored},
        )
    if data:
        await session.commit()
    return await claude_agent_settings(session)


async def asset_steering_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'strategy.%'"))
    values = {row.key.removeprefix("strategy."): row.value for row in result}
    merged = {**STRATEGY_DEFAULTS, **values}
    return {
        "ghi_solar_rich_threshold": float(merged["ghi_solar_rich_threshold"]),
        "ghi_solar_poor_threshold": float(merged["ghi_solar_poor_threshold"]),
        "dynamic_tariff_ceiling_eur_kwh": float(merged["dynamic_tariff_ceiling_eur_kwh"]),
        "daily_recalculate_local_time": merged["daily_recalculate_local_time"],
        "ramp_floor_w": int(float(merged["ramp_floor_w"])),
        "ramp_ceiling_w": int(float(merged["ramp_ceiling_w"])),
        "ramp_hold_seconds": int(float(merged["ramp_hold_seconds"])),
    }


@app.get("/asset-steering/settings")
async def get_asset_steering_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await asset_steering_settings(session)


@app.put("/asset-steering/settings")
async def update_asset_steering_settings(
    update: AssetSteeringSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in STRATEGY_NUMERIC_LIMITS:
            lo, hi = STRATEGY_NUMERIC_LIMITS[key]
            if not lo <= float(value) <= hi:
                raise HTTPException(status_code=422, detail=f"{key} must be between {lo} and {hi}")
        elif key != "daily_recalculate_local_time":
            raise HTTPException(status_code=422, detail=f"unknown setting {key}")
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
            """),
            {"key": f"strategy.{key}", "value": str(value)},
        )
    await session.commit()
    return await asset_steering_settings(session)


@app.get("/asset-steering/status")
async def asset_steering_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    latest_decision = (await session.execute(text("""
        select id, timestamp, mode, soc_floor, soc_ceiling, forecast_ghi, trigger_reason, applied_at
        from strategy_decisions order by timestamp desc limit 1
    """))).mappings().first()
    latest_setpoint = (await session.execute(text("""
        select id, timestamp, source, soc_floor, soc_ceiling, setpoint_w, discharge_allowed,
               battery_soc_at_time, grid_power_at_time, trigger_reason, ack_received, ack_latency_ms
        from setpoint_log order by timestamp desc limit 1
    """))).mappings().first()
    recent_setpoints = (await session.execute(text("""
        select id, timestamp, source, setpoint_w, discharge_allowed, trigger_reason, ack_received
        from setpoint_log order by timestamp desc limit 10
    """))).mappings().all()
    return {
        "settings": await asset_steering_settings(session),
        "latest_decision": dict(latest_decision) if latest_decision else None,
        "latest_setpoint": dict(latest_setpoint) if latest_setpoint else None,
        "recent_setpoints": [dict(row) for row in recent_setpoints],
    }


async def trade_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'trade.%'"))
    values = {row.key.removeprefix("trade."): row.value for row in result}
    merged = {**TRADE_DEFAULTS, **values}
    return {
        "bidding_zone": merged["bidding_zone"],
        "poll_time_local": merged["poll_time_local"],
        "retry_attempts": int(merged["retry_attempts"]),
        "retry_interval_minutes": int(merged["retry_interval_minutes"]),
        "entsoe_api_url": merged["entsoe_api_url"],
    }


@app.get("/trade/prices")
async def get_trade_prices() -> dict[str, Any]:
    prices = latest_trade_prices()
    return {
        "source": "ENTSO-E",
        "unit": "EUR/kWh",
        "date": prices[0]["date"] if prices else None,
        "prices": prices,
    }


@app.get("/trade/settings")
async def get_trade_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await trade_settings(session)


@app.put("/trade/settings")
async def update_trade_settings(update: TradeSettingsUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in TRADE_NUMERIC_LIMITS:
            lo, hi = TRADE_NUMERIC_LIMITS[key]
            if not lo <= int(value) <= hi:
                raise HTTPException(status_code=422, detail=f"{key} must be between {lo} and {hi}")
        elif key == "bidding_zone":
            if not str(value).strip():
                raise HTTPException(status_code=422, detail="bidding_zone cannot be empty")
        elif key == "entsoe_api_url":
            if not str(value).strip():
                raise HTTPException(status_code=422, detail="entsoe_api_url cannot be empty")
        elif key != "poll_time_local":
            raise HTTPException(status_code=422, detail=f"unknown setting {key}")
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
            """),
            {"key": f"trade.{key}", "value": str(value)},
        )
    await session.commit()
    settings = await trade_settings(session)
    await publish_trade_mqtt_settings(settings)
    return settings


@app.get("/settings")
async def list_settings(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    result = await session.execute(text("select key, encrypted, updated_at from settings order by key"))
    return [{"key": row.key, "encrypted": row.encrypted, "updated_at": row.updated_at} for row in result]


@app.post("/api-keys", status_code=202)
async def scaffold_api_key(request: ApiKeyCreate, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("select id from api_keys where name = :name"), {"name": request.name})
    return {"status": "scaffolded", "message": "API key generation is intentionally not implemented yet"}


async def battery_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
    settings: dict[str, Any] = {}
    for row in result:
        name = row.key.removeprefix("battery.")
        if name.startswith("status."):
            continue
        settings[name] = row.value if name in TEXT_KEYS else int(row.value)
    return settings


async def store_power_curve_point(
    session: AsyncSession,
    source: str,
    power_w: int,
    timestamp: datetime | None = None,
    delivered_w: int | None = None,
    returned_w: int | None = None,
    net_w: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    timestamp = timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    net_w = power_w if net_w is None else net_w
    await session.execute(
        text("""
            insert into power_curve_points
              (timestamp, bucket_start, granularity_seconds, source, power_w, delivered_w, returned_w, net_w, metadata)
            values (:timestamp, date_trunc('minute', :timestamp), 60, :source, :power_w, :delivered_w, :returned_w, :net_w, cast(:metadata as json))
        """),
        {
            "timestamp": timestamp,
            "source": source,
            "power_w": power_w,
            "delivered_w": delivered_w,
            "returned_w": returned_w,
            "net_w": net_w,
            "metadata": json.dumps(metadata or {}),
        },
    )
    for granularity in (900, 3600):
        await session.execute(
            text("""
                insert into power_curve_rollups
                  (bucket_start, granularity_seconds, source, sample_count, power_w, delivered_w, returned_w, net_w, updated_at)
                values (
                  to_timestamp(floor(extract(epoch from :timestamp) / :granularity) * :granularity),
                  :granularity, :source, 1, :power_w, :delivered_w, :returned_w, :net_w, now()
                )
                on conflict (bucket_start, granularity_seconds, source) do update set
                  power_w = round(((power_curve_rollups.power_w * power_curve_rollups.sample_count) + excluded.power_w)::numeric / (power_curve_rollups.sample_count + 1)),
                  delivered_w = case when excluded.delivered_w is null then power_curve_rollups.delivered_w else round(((coalesce(power_curve_rollups.delivered_w, 0) * power_curve_rollups.sample_count) + excluded.delivered_w)::numeric / (power_curve_rollups.sample_count + 1)) end,
                  returned_w = case when excluded.returned_w is null then power_curve_rollups.returned_w else round(((coalesce(power_curve_rollups.returned_w, 0) * power_curve_rollups.sample_count) + excluded.returned_w)::numeric / (power_curve_rollups.sample_count + 1)) end,
                  net_w = round(((coalesce(power_curve_rollups.net_w, power_curve_rollups.power_w) * power_curve_rollups.sample_count) + excluded.net_w)::numeric / (power_curve_rollups.sample_count + 1)),
                  sample_count = power_curve_rollups.sample_count + 1,
                  updated_at = now()
            """),
            {"timestamp": timestamp, "granularity": granularity, "source": source, "power_w": power_w, "delivered_w": delivered_w, "returned_w": returned_w, "net_w": net_w},
        )


def parse_status_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        LOGGER.warning("Ignoring invalid status timestamp: %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def active_battery_setpoint_w(payload: dict[str, Any]) -> int | None:
    discharge_w = coerce_int_status_value("discharge_w", payload["discharge_w"]) if payload.get("discharge_w") not in (None, "") else 0
    setpoint_w = coerce_int_status_value("setpoint_w", payload["setpoint_w"]) if payload.get("setpoint_w") not in (None, "") else 0
    if discharge_w:
        return abs(discharge_w)
    if setpoint_w:
        return -abs(setpoint_w)
    return None


def battery_curve_power_w(payload: dict[str, Any]) -> int | None:
    """Return the measured battery power for charts, falling back to setpoints.

    The dashboard graph should reflect what the inverter reports the battery is
    actually doing.  Setpoints are only useful when no measured power telemetry
    is available; otherwise stale discharge/charge commands can make an idle
    battery look active in the graph while the status card correctly shows
    standby.
    """
    actual_power_w = _numeric_w(payload, "power_w")
    if actual_power_w is not None:
        return actual_power_w
    return active_battery_setpoint_w(payload)



def _numeric_w(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-numeric watt value for %s: %r", key, value)
        return None


def compute_household_load(payload: dict[str, Any]) -> dict[str, Any]:
    solar_w = max(0, _numeric_w(payload, "solar_power_w") or 0)
    battery_power_w = battery_curve_power_w(payload) or 0
    battery_discharge_w = max(0, battery_power_w)
    battery_charge_w = max(0, -battery_power_w)
    grid_import_w = _numeric_w(payload, "grid_delivered_w")
    grid_export_w = _numeric_w(payload, "grid_returned_w")
    grid_net_w = _numeric_w(payload, "grid_net_power_w")
    has_dsmr = grid_import_w is not None or grid_export_w is not None or grid_net_w is not None
    if grid_import_w is None:
        grid_import_w = max(0, grid_net_w or 0)
    if grid_export_w is None:
        grid_export_w = max(0, -(grid_net_w or 0))

    method_a_raw = solar_w - grid_export_w - battery_charge_w
    method_b_raw = solar_w + battery_discharge_w - battery_charge_w + grid_import_w - grid_export_w
    using_method = "B" if has_dsmr else "A"
    raw = method_b_raw if has_dsmr else method_a_raw
    load_w = round(raw)
    if load_w < 0:
        LOGGER.warning("Clamping negative household load to zero: raw=%s method=%s payload_keys=%s", raw, using_method, sorted(payload.keys()))
        load_w = 0
    method_a_w = max(0, round(method_a_raw))
    method_b_w = max(0, round(method_b_raw))
    reference = max(abs(method_b_w), 1)
    deviation_pct = abs(method_a_w - method_b_w) / reference * 100
    mismatch = has_dsmr and deviation_pct > 15
    if mismatch:
        LOGGER.debug(
            "Household load sanity-check mismatch: method_a=%sW method_b=%sW deviation=%.1f%% solar=%sW battery_charge=%sW battery_discharge=%sW grid_import=%sW grid_export=%sW",
            method_a_w, method_b_w, deviation_pct, solar_w, battery_charge_w, battery_discharge_w, grid_import_w, grid_export_w,
        )
    return {
        "power_w": load_w,
        "method": using_method,
        "approx": not has_dsmr,
        "mismatch": mismatch,
        "deviation_pct": round(deviation_pct, 1),
        "method_a_w": method_a_w,
        "method_b_w": method_b_w,
        "solar_power_w": solar_w,
        "battery_charge_w": battery_charge_w,
        "battery_discharge_w": battery_discharge_w,
        "grid_import_w": grid_import_w,
        "grid_export_w": grid_export_w,
    }


async def household_status_payload(session: AsyncSession, store: bool = True) -> dict[str, Any]:
    payload = latest_mqtt_status()
    if not payload or not any(k.startswith("grid_") for k in payload):
        try:
            payload.update(collect_retained_mqtt_status())
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT household snapshot")
    result = compute_household_load(payload)
    if store:
        await store_power_curve_point(session, "household", int(result["power_w"]), metadata=result)
        await session.commit()
    return result


@app.get("/battery/status")
async def battery_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    status = await session.execute(text("select key, value from settings where key like 'battery.status.%'"))
    payload: dict[str, Any] = {row.key.removeprefix("battery.status."): row.value for row in status}
    LOGGER.debug("battery_status: db keys=%s", sorted(payload.keys()))
    mqtt_cache = battery_status_payload(latest_mqtt_status())
    LOGGER.debug("battery_status: mqtt cache keys=%s", sorted(mqtt_cache.keys()))
    payload.update(mqtt_cache)
    if cached_status_is_incomplete(payload):
        missing = [k for k in ("soc", "soh", "power_w", "voltage", "mode", "bridge_status", "bridge_last_seen") if not payload.get(k)]
        LOGGER.debug("battery_status: incomplete, missing=%s — attempting retained fetch", missing)
        try:
            retained = collect_retained_mqtt_status()
            LOGGER.debug("battery_status: retained fetch returned keys=%s", sorted(retained.keys()))
            payload.update(battery_status_payload(retained))
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT status snapshot")
    else:
        LOGGER.debug("battery_status: cache complete, skipping retained fetch")
    override = await session.execute(text("select mode from battery_override where id = 1"))
    control_state = str(payload.get("state") or "IDLE")
    payload["control_state"] = control_state
    payload["state"] = control_state
    payload["override_mode"] = override.scalar_one_or_none() or "none"
    for key in ("soc", "soh", "power_w", "charge_i"):
        if key in payload:
            payload[key] = coerce_int_status_value(key, payload[key])
    if "voltage" in payload:
        payload["voltage"] = coerce_float_status_value("voltage", payload["voltage"])
    if "grid_power_w" in payload:
        payload["grid_power_w"] = coerce_int_status_value("grid_power_w", payload["grid_power_w"])
    payload["state"] = derive_battery_state(payload, fallback=control_state)
    if "available" in payload and payload["available"] is not None:
        payload["available"] = str(payload["available"]).lower() == "true"
    enrich_bridge_health(payload)
    battery_power_w = battery_curve_power_w(payload)
    if battery_power_w is not None:
        await store_power_curve_point(session, "battery", battery_power_w, metadata={"soc": payload.get("soc"), "mode": payload.get("mode"), "setpoint_delta_w": active_battery_setpoint_w(payload)})
        await session.commit()
    LOGGER.debug("battery_status: final keys=%s", sorted(payload.keys()))
    return payload



@app.get("/grid/status")
async def grid_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    grid_payload = grid_status_payload(latest_mqtt_status())
    if not grid_payload:
        try:
            grid_payload.update(grid_status_payload(collect_retained_mqtt_status()))
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT grid snapshot")
    coerced = coerce_grid_status(grid_payload)
    stored_curve_point = False
    if isinstance(coerced.get("solar_power_w"), int):
        await store_power_curve_point(
            session,
            "solar",
            int(coerced["solar_power_w"]),
            timestamp=parse_status_timestamp(coerced.get("solar_updated_at")),
            metadata={"updated_at": coerced.get("solar_updated_at")},
        )
        stored_curve_point = True
    if isinstance(coerced.get("grid_net_power_w"), int):
        await store_power_curve_point(
            session,
            "grid",
            int(coerced["grid_net_power_w"]),
            net_w=int(coerced["grid_net_power_w"]),
            delivered_w=coerced.get("grid_delivered_w"),
            returned_w=coerced.get("grid_returned_w"),
            metadata={k: v for k, v in coerced.items() if k.startswith("grid_phase_")},
        )
        stored_curve_point = True
    if stored_curve_point:
        await session.commit()
    return coerced


@app.get("/dsmr/status")
async def dsmr_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await grid_status(session)


@app.get("/solar/status")
async def solar_status() -> dict[str, Any]:
    payload = latest_mqtt_status()
    if not any(key.startswith("solar_") for key in payload):
        try:
            payload.update(collect_retained_mqtt_status())
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT solar snapshot")
    return solar_status_payload(payload)


@app.get("/household/status")
async def household_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await household_status_payload(session)



WINDOWS = {
    "5m": (timedelta(minutes=5), 60, "power_curve_points"),
    "hour": (timedelta(hours=1), 60, "power_curve_points"),
    "day": (timedelta(days=1), 60, "power_curve_points"),
    "week": (timedelta(weeks=1), 900, "power_curve_rollups"),
    "month": (timedelta(days=31), 3600, "power_curve_rollups"),
    "year": (timedelta(days=366), 3600, "power_curve_rollups"),
}


def dashboard_window_bounds(window: str, duration: timedelta, now: datetime | None = None) -> tuple[datetime, datetime]:
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    end = end.astimezone(timezone.utc)
    if window != "day":
        return end - duration, end

    dashboard_tz = ZoneInfo(os.getenv("MINYAD_TIMEZONE", "Europe/Amsterdam"))
    local_end = end.astimezone(dashboard_tz)
    local_start = local_end.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc), end


def _bucket_expr(column: str, seconds: int) -> str:
    return f"to_timestamp(floor(extract(epoch from {column}) / {seconds}) * {seconds})"


def scale_to_system(direct_w_m2: float | None, diffuse_w_m2: float | None) -> int:
    total = max(0.0, float(direct_w_m2 or 0) + float(diffuse_w_m2 or 0))
    return round((total / 1000.0) * SOLAR_PEAK_W * SOLAR_FORECAST_EFFICIENCY)


def open_meteo_retry_delay_seconds(attempt: int) -> float:
    return OPEN_METEO_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))


async def fetch_open_meteo_forecast() -> list[dict[str, Any]]:
    params = {
        "latitude": FORECAST_LATITUDE,
        "longitude": FORECAST_LONGITUDE,
        "hourly": "direct_radiation,diffuse_radiation,shortwave_radiation",
        "forecast_days": 2,
        "timezone": "Europe/Amsterdam",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(1, OPEN_METEO_RETRY_ATTEMPTS + 1):
            try:
                response = await client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                data = response.json()
                break
            except httpx.RequestError as exc:
                if attempt == OPEN_METEO_RETRY_ATTEMPTS:
                    raise
                delay = open_meteo_retry_delay_seconds(attempt)
                LOGGER.warning(
                    "Open-Meteo request failed on attempt %d/%d; retrying in %ss: %s",
                    attempt,
                    OPEN_METEO_RETRY_ATTEMPTS,
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
        points.append({
            "forecast_time": datetime.fromisoformat(forecast_time).replace(tzinfo=ZoneInfo("Europe/Amsterdam")).astimezone(timezone.utc),
            "direct_w_m2": direct_value,
            "diffuse_w_m2": diffuse_value,
            "estimated_w": scale_to_system(direct_value, diffuse_value),
        })
    return points


async def persist_solar_forecast(session: AsyncSession, points: list[dict[str, Any]]) -> None:
    fetched_at = datetime.now(timezone.utc)
    for point in points:
        forecast_time = point["forecast_time"]
        if forecast_time.tzinfo is None:
            forecast_time = forecast_time.replace(tzinfo=timezone.utc)
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
            {"forecast_time": forecast_time, "fetched_at": fetched_at, **point},
        )
    await session.commit()


async def ensure_recent_solar_forecast(session: AsyncSession) -> None:
    latest = (await session.execute(text("select max(fetched_at) from solar_forecast_points where source = 'open-meteo'"))).scalar_one_or_none()
    if latest and latest > datetime.now(timezone.utc) - timedelta(minutes=20):
        return
    try:
        await persist_solar_forecast(session, await fetch_open_meteo_forecast())
    except Exception:
        LOGGER.exception("Unable to refresh Open-Meteo solar forecast")


def interpolate_points(points: list[dict[str, Any]], step_seconds: int) -> list[dict[str, Any]]:
    if len(points) < 2 or step_seconds >= 900:
        return points
    parsed = [(datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")), p["power_w"]) for p in points]
    output = []
    for (left_ts, left_w), (right_ts, right_w) in zip(parsed, parsed[1:]):
        span = max(1, (right_ts - left_ts).total_seconds())
        cursor = left_ts
        while cursor < right_ts:
            ratio = (cursor - left_ts).total_seconds() / span
            output.append({"timestamp": cursor.isoformat(), "power_w": round(left_w + ((right_w - left_w) * ratio))})
            cursor += timedelta(seconds=step_seconds)
    output.append({"timestamp": parsed[-1][0].isoformat(), "power_w": parsed[-1][1]})
    return output


def extrapolate_battery_curve(start: datetime, end: datetime, step_seconds: int, soc: float, forecast: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capacity_wh = 10000
    usable_wh = max(0, min(100, soc)) / 100 * capacity_wh
    points = []
    for point in forecast:
        ts = datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00"))
        if ts < start or ts > end:
            continue
        solar_w = int(point["power_w"])
        if solar_w > 1200 and usable_wh < capacity_wh:
            power_w = -min(2500, round((solar_w - 1200) * 0.6))
        elif solar_w < 400 and usable_wh > capacity_wh * 0.15:
            power_w = min(1200, round(400 - solar_w))
        else:
            power_w = 0
        usable_wh = max(0, min(capacity_wh, usable_wh - (power_w * step_seconds / 3600)))
        points.append({"timestamp": point["timestamp"], "power_w": power_w})
    return points


@app.get("/dashboard/curves")
async def dashboard_curves(window: Literal["5m", "hour", "day", "week", "month", "year"] = "day", session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    await ensure_recent_solar_forecast(session)
    duration, step_seconds, table_name = WINDOWS[window]
    start, end = dashboard_window_bounds(window, duration)
    if table_name == "power_curve_points":
        bucket = _bucket_expr("bucket_start", step_seconds)
        source_filter = "bucket_start >= :start and bucket_start <= :end"
        power_expr = "avg(power_w)"
        delivered_expr = "avg(delivered_w)"
        returned_expr = "avg(returned_w)"
        net_expr = "avg(net_w)"
    else:
        bucket = "bucket_start"
        source_filter = "granularity_seconds = :step_seconds and bucket_start >= :start and bucket_start <= :end"
        power_expr = "avg(power_w)"
        delivered_expr = "avg(delivered_w)"
        returned_expr = "avg(returned_w)"
        net_expr = "avg(net_w)"
    rows = (await session.execute(text(f"""
        select {bucket} as ts, source, {power_expr} as power_w,
               {delivered_expr} as delivered_w, {returned_expr} as returned_w, {net_expr} as net_w
        from {table_name}
        where {source_filter}
        group by ts, source order by ts
    """), {"start": start, "end": end, "step_seconds": step_seconds})).mappings().all()
    series = {"solar": [], "battery": [], "grid": [], "household": []}
    for row in rows:
        series[row["source"]].append({
            "timestamp": row["ts"].replace(tzinfo=timezone.utc).isoformat(),
            "power_w": round(float(row["power_w"] or 0)),
            "delivered_w": round(float(row["delivered_w"])) if row["delivered_w"] is not None else None,
            "returned_w": round(float(row["returned_w"])) if row["returned_w"] is not None else None,
            "net_w": round(float(row["net_w"])) if row["net_w"] is not None else round(float(row["power_w"] or 0)),
        })

    forecast_rows = (await session.execute(text(f"""
        select forecast_time as ts, estimated_w as power_w
        from solar_forecast_points
        where source = 'open-meteo' and forecast_time >= :start and forecast_time <= :end + interval '1 day'
        order by forecast_time
    """), {"start": start, "end": end})).mappings().all()
    forecast = [{"timestamp": r["ts"].replace(tzinfo=timezone.utc).isoformat(), "power_w": round(float(r["power_w"] or 0))} for r in forecast_rows]
    forecast = interpolate_points(forecast, step_seconds)

    mqtt_payload = latest_mqtt_status()
    soc = coerce_float_status_value("soc", mqtt_payload.get("soc", 50)) if mqtt_payload.get("soc") not in (None, "") else 50.0
    battery_forecast = extrapolate_battery_curve(end, end + duration, step_seconds, soc, forecast)

    return {
        "window": window,
        "granularity_seconds": step_seconds,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "forecast": forecast,
        "battery_forecast": battery_forecast,
        "series": series,
    }


@app.get("/api/state")
async def api_state(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    battery = await battery_status(session)
    grid = await grid_status(session)
    household = await household_status_payload(session, store=False)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "battery": battery,
        "grid": grid,
        "household": household,
    }


@app.get("/api/forecast")
async def api_forecast(hours_ahead: int = 12, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    hours = max(1, min(48, hours_ahead))
    await ensure_recent_solar_forecast(session)
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=hours)
    rows = (await session.execute(text("""
        select forecast_time as ts, estimated_w as power_w, direct_w_m2, diffuse_w_m2, fetched_at
        from solar_forecast_points
        where source = 'open-meteo' and forecast_time >= :start and forecast_time <= :end
        order by forecast_time
    """), {"start": start, "end": end})).mappings().all()
    points = [
        {
            "timestamp": row["ts"].replace(tzinfo=timezone.utc).isoformat(),
            "power_w": round(float(row["power_w"] or 0)),
            "direct_w_m2": float(row["direct_w_m2"] or 0),
            "diffuse_w_m2": float(row["diffuse_w_m2"] or 0),
            "fetched_at": row["fetched_at"].replace(tzinfo=timezone.utc).isoformat() if row["fetched_at"] else None,
        }
        for row in rows
    ]
    return {"hours_ahead": hours, "points": interpolate_points(points, 60)}


@app.post("/api/control/battery")
async def api_control_battery(request: AgentBatteryControlRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if request.setpoint_w > 0:
        override = BatteryOverrideRequest(mode="force_on", watts=request.setpoint_w, duration_seconds=request.duration_minutes * 60)
        action = "charge"
    elif request.setpoint_w < 0:
        override = BatteryOverrideRequest(mode="force_discharge", watts=abs(request.setpoint_w), duration_seconds=request.duration_minutes * 60)
        action = "discharge"
    else:
        override = BatteryOverrideRequest(mode="none", watts=None, duration_seconds=None)
        action = "hold"
    result = await set_battery_override(override, session)
    return {"status": "ok", "action": action, "setpoint_w": request.setpoint_w, "duration_minutes": request.duration_minutes, "override": result}


@app.post("/api/agent/decisions", status_code=201)
async def create_agent_decision(request: AgentDecisionRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_decisions (action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model)
        values (:action_taken, :setpoint_w, :reasoning, :confidence, cast(:input_snapshot as jsonb), :dry_run, :model)
        returning id, created_at
    """), {
        "action_taken": request.action_taken,
        "setpoint_w": request.setpoint_w,
        "reasoning": request.reasoning,
        "confidence": request.confidence,
        "input_snapshot": json.dumps(request.input_snapshot),
        "dry_run": request.dry_run,
        "model": request.model,
    })).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=timezone.utc).isoformat()}


def serialize_agent_decision(row: Any) -> dict[str, Any]:
    data = dict(row)
    value = data.get("created_at")
    if value is not None:
        data["created_at"] = value.replace(tzinfo=timezone.utc).isoformat()
    snapshot = data.get("input_snapshot")
    if isinstance(snapshot, str):
        try:
            data["input_snapshot"] = json.loads(snapshot)
        except json.JSONDecodeError:
            data["input_snapshot"] = {"raw": snapshot}
    return data


@app.get("/api/agent/decisions")
async def list_agent_decisions(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (await session.execute(text("""
        select id, created_at, action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model
        from agent_decisions
        order by created_at desc
        limit :limit
    """), {"limit": limit})).mappings().all()
    return [serialize_agent_decision(row) for row in rows]


def serialize_agent_message(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("created_at", "read_at", "archived_at", "operator_ack_at", "agent_ack_at"):
        value = data.get(key)
        if value is not None:
            data[key] = value.replace(tzinfo=timezone.utc).isoformat()
    return data


@app.get("/api/messages")
async def list_agent_messages(
    unread: bool | None = None,
    category: Literal["anomaly", "suggestion", "info", "reply"] | None = None,
    sender: Literal["agent", "operator"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    archived: bool | None = False,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if unread is True:
        clauses.append("read_at is null")
    elif unread is False:
        clauses.append("read_at is not null")
    if category is not None:
        clauses.append("category = :category")
        params["category"] = category
    if sender is not None:
        clauses.append("sender = :sender")
        params["sender"] = sender
    if archived is True:
        clauses.append("archived_at is not null")
    elif archived is False:
        clauses.append("archived_at is null")
    where = " where " + " and ".join(clauses) if clauses else ""
    rows = (await session.execute(text(f"""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        {where}
        order by created_at desc
        limit :limit
    """), params)).mappings().all()
    return [serialize_agent_message(row) for row in rows]


@app.get("/api/messages/unread-count")
async def agent_messages_unread_count(
    sender: Literal["agent", "operator"] | None = "agent",
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    clause = "read_at is null and archived_at is null"
    params: dict[str, Any] = {}
    if sender is not None:
        clause += " and sender = :sender"
        params["sender"] = sender
    count = (await session.execute(text(f"select count(*) from agent_messages where {clause}"), params)).scalar_one()
    return {"unread_count": int(count)}


@app.get("/api/messages/{message_id}")
async def get_agent_message(message_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :id
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    root_id = row["thread_id"] or row["id"]
    thread_rows = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :root_id or thread_id = :root_id
        order by created_at asc
    """), {"root_id": root_id})).mappings().all()
    return {"message": serialize_agent_message(row), "thread": [serialize_agent_message(thread_row) for thread_row in thread_rows]}


@app.post("/api/messages", status_code=201)
async def create_agent_message(request: AgentMessageCreate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_messages (sender, category, subject, body, related_decision_id, thread_id, severity, operator_ack_at, agent_ack_at)
        values (:sender, :category, :subject, :body, :related_decision_id, :thread_id, :severity, case when :sender = 'operator' then now() else null end, case when :sender = 'agent' then now() else null end)
        returning id, created_at
    """), request.model_dump())).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=timezone.utc).isoformat()}


@app.patch("/api/messages/{message_id}/read")
async def mark_agent_message_read(message_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set read_at = coalesce(read_at, now()),
            agent_ack_at = case when sender = 'operator' then coalesce(agent_ack_at, now()) else agent_ack_at end
        where id = :id
        returning id, read_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    await session.commit()
    return {"status": "ok", "id": row["id"], "read_at": row["read_at"].replace(tzinfo=timezone.utc).isoformat()}


@app.patch("/api/messages/{message_id}/archive")
async def archive_agent_message(message_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set archived_at = coalesce(archived_at, now())
        where id = :id
        returning id, archived_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    await session.commit()
    return {"status": "ok", "id": row["id"], "archived_at": row["archived_at"].replace(tzinfo=timezone.utc).isoformat()}


@app.patch("/api/messages/{message_id}/ack")
async def acknowledge_agent_message(message_id: int, actor: Literal["operator", "agent"] = "operator", session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    column = "operator_ack_at" if actor == "operator" else "agent_ack_at"
    row = (await session.execute(text(f"""
        update agent_messages
        set {column} = coalesce({column}, now())
        where id = :id
        returning id, operator_ack_at, agent_ack_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    await session.commit()
    return {"status": "ok", **serialize_agent_message(row)}


@app.delete("/api/messages/{message_id}")
async def delete_agent_message(message_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("delete from agent_messages where id = :id returning id"), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    await session.commit()
    return {"status": "ok", "id": row["id"]}


@app.post("/battery/override")
async def set_battery_override(request: BatteryOverrideRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = await battery_settings(session)
    soc_floor = int(settings.get("soc_floor", 20))
    soc_ceiling = int(settings.get("soc_ceiling", 90))
    payload_status = battery_status_payload(latest_mqtt_status())
    soc = payload_status.get("soc")
    if soc in (None, ""):
        db_soc = await session.execute(text("select value from settings where key = 'battery.status.soc'"))
        soc = db_soc.scalar_one_or_none()
    try:
        soc_value = float(soc) if soc not in (None, "") else None
    except (TypeError, ValueError):
        soc_value = None
    if request.mode == "force_discharge" and soc_value is not None and soc_value <= soc_floor:
        raise HTTPException(status_code=422, detail=f"discharge blocked because SoC {soc_value:g}% is at or below configured floor {soc_floor}%")
    if request.mode == "force_on" and soc_value is not None and soc_value >= soc_ceiling:
        raise HTTPException(status_code=422, detail=f"charge blocked because SoC {soc_value:g}% is at or above configured ceiling {soc_ceiling}%")
    configured_max_w = int(settings.get("max_charge_w", 0))
    hardware_max_w = int(settings.get("max_charge_a", 30)) * int(settings.get("nominal_v", 48))
    max_charge_w = min(configured_max_w, hardware_max_w)
    max_discharge_w = int(settings.get("max_discharge_w", 5000))
    max_allowed_w = max_discharge_w if request.mode == "force_discharge" else max_charge_w
    if request.watts is not None and request.watts > max_allowed_w:
        limit_name = "MAX_DISCHARGE_W" if request.mode == "force_discharge" else "MAX_CHARGE_W"
        raise HTTPException(status_code=422, detail=f"watts must not exceed {limit_name} ({max_allowed_w})")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.duration_seconds) if request.duration_seconds else None
    await session.execute(
        text("""
            insert into battery_override (id, mode, watts, duration_seconds, expires_at, updated_at)
            values (1, :mode, :watts, :duration_seconds, :expires_at, now())
            on conflict (id) do update set mode=:mode, watts=:watts, duration_seconds=:duration_seconds, expires_at=:expires_at, updated_at=now()
        """),
        {"mode": request.mode, "watts": request.watts, "duration_seconds": request.duration_seconds, "expires_at": expires_at},
    )
    await session.commit()
    payload = request.model_dump()
    mqtt.client.publish("minyad/control/override", json.dumps(payload), qos=0, retain=False)
    return {"status": "ok", **payload}


@app.delete("/battery/override")
async def clear_battery_override(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("update battery_override set mode='none', watts=null, duration_seconds=null, expires_at=null, updated_at=now() where id=1"))
    await session.commit()
    mqtt.client.publish("minyad/control/override", json.dumps({"mode": "none"}), qos=0, retain=False)
    return {"status": "ok", "mode": "none"}


@app.get("/api/battery/settings")
@app.get("/battery/settings")
async def get_battery_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await battery_settings(session)


@app.put("/api/battery/settings")
@app.put("/battery/settings")
async def update_battery_settings(update: BatterySettingsUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    current = await battery_settings(session)
    merged = {**current, **data}
    if "stop_w" in merged and "start_w" in merged and int(merged["stop_w"]) > int(merged["start_w"]):
        raise HTTPException(status_code=422, detail="stop_w must be less than or equal to start_w")
    if "soc_floor" in merged and "soc_ceiling" in merged and int(merged["soc_floor"]) >= int(merged["soc_ceiling"]):
        raise HTTPException(status_code=422, detail="soc_floor must be lower than soc_ceiling")
    for key, value in data.items():
        if key in BATTERY_KEYS:
            lo, hi = BATTERY_KEYS[key]
            if not lo <= int(value) <= hi:
                raise HTTPException(status_code=422, detail=f"{key} must be between {lo} and {hi}")
        elif key not in TEXT_KEYS:
            raise HTTPException(status_code=422, detail=f"unknown setting {key}")
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
            """),
            {"key": f"battery.{key}", "value": str(value)},
        )
    await session.commit()
    settings = await battery_settings(session)
    await publish_battery_mqtt_settings(settings)
    mqtt.client.publish("minyad/control/override", json.dumps({"mode": "reload_settings"}), qos=0, retain=False)
    return settings
