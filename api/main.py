"""Minyad REST API."""

from __future__ import annotations

import asyncio
import json
import math
import logging
import os
import secrets
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
import paho.mqtt.client as paho_mqtt
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal, get_session
from shared.mqtt_client import MinyadMqttClient

app = FastAPI(title="Minyad API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "MINYAD_CORS_ORIGINS",
            "http://localhost:8084,http://localhost:8085",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)
mqtt = MinyadMqttClient("minyad-api")
LOGGER = logging.getLogger(__name__)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Security(API_KEY_HEADER)) -> None:
    expected = os.getenv("MINYAD_API_SECRET", "")
    if not expected or not key or not secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


MUTATION_AUTH = [Depends(require_api_key)]

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
    "goodwe_poll_interval_grace_s": (0, 3600),
}
TEXT_KEYS = {"inverter_ip"}
BATTERY_DEFAULTS = {
    "inverter_poll_interval_s": 120,
    "goodwe_poll_interval_grace_s": 60,
}

STRATEGY_DEFAULTS = {
    "ghi_solar_rich_threshold": "4.5",
    "ghi_solar_poor_threshold": "1.5",
    "dynamic_tariff_ceiling_eur_kwh": "0.10",
    "daily_recalculate_local_time": "22:00",
    "ramp_floor_w": "200",
    "ramp_ceiling_w": "1000",
    "ramp_hold_seconds": "120",
}
STRATEGY3_DEFAULTS = {
    "traj_deadband_pct": "3",
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
ALLOWED_ENTSOE_HOST = "web-api.tp.entsoe.eu"
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
PLAN_STALE_MINUTES = 30
SURPLUS_API_VERSION = "v1"


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
    language: Literal["en", "nl"] | None = None


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
    mode: Literal["none", "force_on", "force_charge", "force_off", "force_idle", "force_discharge", "pause"]
    watts: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1)
    override_soc_limits: bool = False

    @model_validator(mode="after")
    def validate_required_fields(self) -> "BatteryOverrideRequest":
        if self.mode in {"force_on", "force_charge", "force_discharge"} and self.watts is None:
            raise ValueError("watts is required for force_charge and force_discharge")
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
        if parsed.hostname != ALLOWED_ENTSOE_HOST or parsed.username or parsed.password or parsed.port is not None:
            raise ValueError(f"entsoe_api_url must point to {ALLOWED_ENTSOE_HOST}")
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
    goodwe_poll_interval_grace_s: int | None = Field(default=None, ge=0)

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
    result = await session.execute(text("select key, value from settings where key in ('system.debug_logging', 'system.theme', 'system.language')"))
    settings = {row.key: row.value for row in result}
    return {
        "debug_logging": settings.get("system.debug_logging", "false") == "true",
        "theme": settings.get("system.theme", "system"),
        "language": settings.get("system.language", "en"),
    }


@app.put("/system-settings", dependencies=MUTATION_AUTH)
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
    if update.language is not None:
        await session.execute(
            text("""
                insert into settings (key, value, encrypted, updated_at) values ('system.language', :val, false, now())
                on conflict (key) do update set value=:val, updated_at=now()
            """),
            {"val": update.language},
        )
    if update.debug_logging is not None or update.theme is not None or update.language is not None:
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


@app.patch("/api/claude-agent/settings", dependencies=MUTATION_AUTH)
@app.patch("/claude-agent/settings", dependencies=MUTATION_AUTH)
@app.put("/api/claude-agent/settings", dependencies=MUTATION_AUTH)
@app.put("/claude-agent/settings", dependencies=MUTATION_AUTH)
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
    result_v3 = await session.execute(text("select key, value from settings where key like 'strategy3.%'"))
    values_v3 = {row.key.removeprefix("strategy3."): row.value for row in result_v3}
    merged = {**STRATEGY_DEFAULTS, **values}
    merged_v3 = {**STRATEGY3_DEFAULTS, **values_v3}
    return {
        "ghi_solar_rich_threshold": float(merged["ghi_solar_rich_threshold"]),
        "ghi_solar_poor_threshold": float(merged["ghi_solar_poor_threshold"]),
        "dynamic_tariff_ceiling_eur_kwh": float(merged["dynamic_tariff_ceiling_eur_kwh"]),
        "daily_recalculate_local_time": merged["daily_recalculate_local_time"],
        "ramp_floor_w": int(float(merged["ramp_floor_w"])),
        "ramp_ceiling_w": int(float(merged["ramp_ceiling_w"])),
        "ramp_hold_seconds": int(float(merged["ramp_hold_seconds"])),
        "strategy3": {
            "traj_deadband_pct": float(merged_v3["traj_deadband_pct"]),
        },
    }


@app.get("/asset-steering/settings")
async def get_asset_steering_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await asset_steering_settings(session)


@app.put("/asset-steering/settings", dependencies=MUTATION_AUTH)
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


def serialize_control_decision(row: Any) -> dict[str, Any]:
    data = dict(row)
    timestamp = data.get("timestamp")
    if timestamp is not None:
        data["timestamp"] = timestamp.replace(tzinfo=timezone.utc).isoformat()
    setpoint = data.get("setpoint_w") or 0
    source = data.get("source") or ""
    discharge_allowed = bool(data.get("discharge_allowed"))
    if setpoint == 0:
        action = "discharge" if discharge_allowed else "hold"
    elif source in {"strategy_v2", "strategy_v3", "goodwe_bridge"}:
        action = "charge" if setpoint > 0 else "discharge"
    else:
        action = "discharge" if setpoint > 0 else "charge"
    data["action"] = action
    return data


async def setpoint_log_columns(session: AsyncSession) -> set[str]:
    rows = (await session.execute(
        text("""
            select column_name
            from information_schema.columns
            where table_name = 'setpoint_log'
        """)
    )).scalars().all()
    return set(rows)


def setpoint_log_select_list(columns: set[str]) -> str:
    def col(name: str, fallback: str | None = None, alias: str | None = None) -> str:
        target = alias or name
        if name in columns:
            return name if target == name else f"{name} as {target}"
        if fallback and fallback in columns:
            return f"{fallback} as {target}"
        return f"null as {target}"

    return ", ".join(
        [
            col("id"),
            col("timestamp"),
            col("source"),
            col("soc_floor"),
            col("soc_ceiling"),
            col("setpoint_w", "charge_rate_w"),
            col("discharge_allowed"),
            col("battery_soc_at_time"),
            col("grid_power_at_time"),
            col("battery_power_at_time"),
            col("apparent_load_at_time", "home_load_at_time"),
            col("setpoint_delta"),
            col("trigger_reason"),
            col("ack_received"),
            col("ack_latency_ms"),
        ]
    )


@app.get("/reporting/decisions")
async def reporting_decisions(
    limit: int = Query(default=50, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    columns = await setpoint_log_columns(session)
    if not columns:
        return {"limit": limit, "offset": offset, "total": 0, "items": []}
    total = (await session.execute(text("select count(*) from setpoint_log"))).scalar_one()
    select_list = setpoint_log_select_list(columns)
    rows = (await session.execute(
        text(f"""
            select {select_list}
            from setpoint_log
            order by timestamp desc, id desc
            limit :limit offset :offset
        """),
        {"limit": limit, "offset": offset},
    )).mappings().all()
    return {
        "limit": limit,
        "offset": offset,
        "total": int(total),
        "items": [serialize_control_decision(row) for row in rows],
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


@app.put("/trade/settings", dependencies=MUTATION_AUTH)
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


@app.post("/api-keys", status_code=202, dependencies=MUTATION_AUTH)
async def scaffold_api_key(request: ApiKeyCreate, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("select id from api_keys where name = :name"), {"name": request.name})
    return {"status": "scaffolded", "message": "API key generation is intentionally not implemented yet"}


async def battery_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
    settings: dict[str, Any] = dict(BATTERY_DEFAULTS)
    for row in result:
        name = row.key.removeprefix("battery.")
        if name.startswith("status."):
            continue
        settings[name] = row.value if name in TEXT_KEYS else int(row.value)
    return settings


def derived_bridge_stale_seconds(settings: dict[str, Any]) -> int:
    return int(settings.get("inverter_poll_interval_s", BATTERY_DEFAULTS["inverter_poll_interval_s"])) + int(
        settings.get("goodwe_poll_interval_grace_s", BATTERY_DEFAULTS["goodwe_poll_interval_grace_s"])
    )


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

    method_a_raw = solar_w + battery_discharge_w - battery_charge_w - grid_export_w
    method_b_raw = solar_w + battery_discharge_w - battery_charge_w + grid_import_w - grid_export_w
    using_method = "B" if has_dsmr else "A"
    raw = method_b_raw if has_dsmr else method_a_raw
    load_w = round(raw)
    if load_w < 0:
        LOGGER.warning("Clamping negative household load to zero: raw=%s method=%s payload_keys=%s", raw, using_method, sorted(payload.keys()))
        load_w = 0
    method_a_w = max(0, round(method_a_raw))
    method_b_w = max(0, round(method_b_raw))
    comparable_method_b_w = max(0, round(method_b_raw - grid_import_w))
    reference = max(abs(comparable_method_b_w), 1)
    deviation_pct = abs(method_a_w - comparable_method_b_w) / reference * 100
    mismatch = has_dsmr and deviation_pct > 15
    if mismatch:
        LOGGER.debug(
            "Household load sanity-check mismatch: method_a=%sW method_b=%sW deviation=%.1f%% solar=%sW battery_charge=%sW battery_discharge=%sW grid_import=%sW grid_export=%sW",
            method_a_w, comparable_method_b_w, deviation_pct, solar_w, battery_charge_w, battery_discharge_w, grid_import_w, grid_export_w,
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


def _status_text(value: Any, fallback: str = "UNKNOWN") -> str:
    text_value = str(value or fallback).strip().upper()
    return text_value or fallback


def build_surplus_payload(
    grid: dict[str, Any],
    battery: dict[str, Any],
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the external surplus snapshot used by downstream surplus consumers.

    Positive surplus is export/available power.  ``surplus_w`` is the remaining
    grid export after Minyad's battery steering; ``gross_surplus_w`` adds the
    measured battery charge power so a consumer can see that surplus exists even
    while Minyad is still feeding it into the battery.
    """
    settings = settings or {}
    timestamp = now or datetime.now(timezone.utc)
    grid_net_w = _numeric_w(grid, "grid_net_power_w")
    grid_import_w = _numeric_w(grid, "grid_delivered_w")
    grid_export_w = _numeric_w(grid, "grid_returned_w")
    if grid_import_w is None:
        grid_import_w = max(0, grid_net_w or 0)
    if grid_export_w is None:
        grid_export_w = max(0, -(grid_net_w or 0))

    battery_power_w = battery_curve_power_w(battery)
    battery_charge_w = max(0, -(battery_power_w or 0))
    battery_discharge_w = max(0, battery_power_w or 0)
    remaining_surplus_w = max(0, grid_export_w)
    gross_surplus_w = remaining_surplus_w + battery_charge_w
    control_state = _status_text(battery.get("control_state") or battery.get("state"), "IDLE")
    activity_state = _status_text(battery.get("state") or derive_battery_state(battery), control_state)
    if control_state == "COOLDOWN":
        battery_phase = "cooldown"
    elif activity_state == "CHARGING" or control_state == "CHARGING" or battery_charge_w > 0:
        battery_phase = "charging"
    elif activity_state == "DISCHARGING" or control_state == "DISCHARGING" or battery_discharge_w > 0:
        battery_phase = "discharging"
    else:
        battery_phase = "idle"

    return {
        "api_version": SURPLUS_API_VERSION,
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "surplus_w": remaining_surplus_w,
        "gross_surplus_w": gross_surplus_w,
        "has_surplus": remaining_surplus_w > 0,
        "has_gross_surplus": gross_surplus_w > 0,
        "grid": {
            "net_power_w": grid_net_w,
            "import_w": grid_import_w,
            "export_w": grid_export_w,
            "status": grid.get("grid_status"),
            "timestamp": grid.get("grid_timestamp"),
        },
        "solar": {
            "power_w": _numeric_w(grid, "solar_power_w"),
            "updated_at": grid.get("solar_updated_at"),
        },
        "battery": {
            "phase": battery_phase,
            "control_state": control_state,
            "activity_state": activity_state,
            "mode": battery.get("mode"),
            "mode_label": battery.get("mode_label"),
            "power_w": battery_power_w,
            "charge_w": battery_charge_w,
            "discharge_w": battery_discharge_w,
            "soc": battery.get("soc"),
            "soc_floor": settings.get("soc_floor"),
            "soc_ceiling": settings.get("soc_ceiling"),
            "available": battery.get("available"),
            "override_mode": battery.get("override_mode", "none"),
            "bridge_status": battery.get("bridge_status"),
            "bridge_last_seen": battery.get("bridge_last_seen"),
            "is_charging": battery_phase == "charging",
            "is_discharging": battery_phase == "discharging",
            "is_idle": battery_phase == "idle",
            "is_cooldown": battery_phase == "cooldown",
        },
        "minyad": {
            "surplus_handling": battery_phase,
            "is_absorbing_surplus": battery_phase == "charging",
            "cooldown_seconds": settings.get("cooldown"),
            "charge_start_threshold_w": settings.get("start_w"),
            "charge_stop_threshold_w": settings.get("stop_w"),
        },
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
    override = await session.execute(text("""
        select mode, coalesce(override_soc_limits, false) as override_soc_limits
        from battery_override
        where id = 1
    """))
    override_row = override.mappings().first()
    control_state = str(payload.get("state") or "IDLE")
    payload["control_state"] = control_state
    payload["state"] = control_state
    payload["override_mode"] = override_row["mode"] if override_row else "none"
    payload["override_soc_limits"] = bool(override_row["override_soc_limits"]) if override_row else False
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


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.month - 1) + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month)


def dashboard_window_bounds(
    window: str,
    duration: timedelta,
    now: datetime | None = None,
    period_offset: int | None = None,
) -> tuple[datetime, datetime, datetime]:
    now_ = now or datetime.now(timezone.utc)
    if now_.tzinfo is None:
        now_ = now_.replace(tzinfo=timezone.utc)
    now_ = now_.astimezone(timezone.utc)
    dashboard_tz = ZoneInfo(os.getenv("MINYAD_TIMEZONE", "Europe/Amsterdam"))
    local_now = now_.astimezone(dashboard_tz)

    if period_offset is not None and window in {"day", "week", "month", "year"}:
        if window == "day":
            local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=period_offset)
            local_next = local_start + timedelta(days=1)
        elif window == "week":
            local_week = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local_now.weekday())
            local_start = local_week + timedelta(weeks=period_offset)
            local_next = local_start + timedelta(weeks=1)
        elif window == "month":
            local_month = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            local_start = _add_months(local_month, period_offset)
            local_next = _add_months(local_start, 1)
        else:
            local_year = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            local_start = _add_months(local_year, period_offset * 12)
            local_next = _add_months(local_start, 12)
        local_end = local_next - timedelta(seconds=1)
        start = local_start.astimezone(timezone.utc)
        end = local_end.astimezone(timezone.utc)
        query_until = min(now_, end)
        return start, end, query_until

    if window != "day":
        return now_ - duration, now_, now_

    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc), now_


def _bucket_expr(column: str, seconds: int) -> str:
    return f"to_timestamp(floor(extract(epoch from {column}) / {seconds}) * {seconds})"


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


async def latest_slot_plan(session: AsyncSession, *, include_fallback: bool = True) -> dict[str, Any] | None:
    row = (await session.execute(text("""
        select generated_at, valid_from, slot_seconds, payload, solver_status
        from slot_plans
        where (:include_fallback or solver_status != 'FALLBACK')
        order by generated_at desc
        limit 1
    """), {"include_fallback": include_fallback})).mappings().first()
    return dict(row) if row else None


def _slot_battery_w(prev_soc_pct: float, soc_target_pct: float, capacity_wh: float, slot_seconds: int) -> int:
    """Net terminal battery power implied by the SoC-target trajectory (dashboard_forecast_v1 spec 3.3).

    Derived from the SoC delta rather than the LP's gross charge_w/discharge_w: round-trip
    efficiency losses are already priced into the plan, so this is the planned net klemvermogen
    without further correction. Positive = discharge, negative = charge (GoodWe convention).
    """
    if slot_seconds <= 0:
        return 0
    delta_fraction = (soc_target_pct - prev_soc_pct) / 100.0
    slot_hours = slot_seconds / 3600.0
    return round(-delta_fraction * capacity_wh / slot_hours)


def _classify_cloud_cover(cloud_cover_pct: float) -> str:
    """Mirrors minyad.strategy.v3.pv_uncertainty.classify_cloud_cover (kept duplicated rather
    than importing the strategy package here, matching this service's existing DB/MQTT-only
    boundary with strategy internals)."""
    if cloud_cover_pct < 25.0:
        return "clear"
    if cloud_cover_pct < 75.0:
        return "partly"
    return "cloudy"


def build_plan_curves(
    payload: dict[str, Any],
    capacity_wh: float,
    fallback_soc_pct: float,
    now_: datetime,
    window_end: datetime,
    uncertainty_bands: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Derive the four forecast curves + curtailment from one plan payload (spec 3.2/3.3),
    plus a PV P10-P90 uncertainty band where the slot's cloud-cover class has enough history
    (spec 4.4) — slots without a usable band are simply omitted, never a fabricated one.

    Slots that have already fully elapsed relative to ``now_`` are dropped, so the forecast
    curves start at "now" — matching the measured series, which stops at "now" (spec 3.5).
    """
    slot_seconds = int(payload["slot_seconds"])
    prev_soc = float(payload.get("soc_start_pct", fallback_soc_pct))
    pv: list[dict[str, Any]] = []
    load: list[dict[str, Any]] = []
    battery: list[dict[str, Any]] = []
    grid: list[dict[str, Any]] = []
    curtailment: list[dict[str, Any]] = []
    price_source: list[dict[str, Any]] = []
    pv_p10: list[dict[str, Any]] = []
    pv_p90: list[dict[str, Any]] = []
    for slot in payload.get("slots", []):
        slot_start = datetime.fromisoformat(slot["start"])
        slot_end = slot_start + timedelta(seconds=slot_seconds)
        soc_target = float(slot.get("soc_target_pct", prev_soc))
        battery_w = _slot_battery_w(prev_soc, soc_target, capacity_wh, slot_seconds)
        prev_soc = soc_target
        if slot_end <= now_ or slot_start > window_end:
            continue
        ts = slot_start.isoformat()
        pv_w = round(float(slot.get("pv_forecast_w") or 0))
        load_w = round(float(slot.get("load_forecast_w") or 0))
        grid_w = round(load_w - pv_w - battery_w)
        curtail_w = round(float(slot.get("curtailment_w") or 0))
        pv.append({"timestamp": ts, "power_w": pv_w})
        load.append({"timestamp": ts, "power_w": load_w})
        battery.append({"timestamp": ts, "power_w": battery_w})
        grid.append({"timestamp": ts, "power_w": grid_w})
        curtailment.append({"timestamp": ts, "power_w": curtail_w})
        price_source.append({"timestamp": ts, "source": slot.get("price_source", "fallback")})
        cloud_cover_pct = slot.get("cloud_cover_pct")
        if uncertainty_bands and cloud_cover_pct is not None:
            band = uncertainty_bands.get(_classify_cloud_cover(float(cloud_cover_pct)))
            if band is not None:
                pv_p10.append({"timestamp": ts, "power_w": round(pv_w * band["p10_multiplier"])})
                pv_p90.append({"timestamp": ts, "power_w": round(pv_w * band["p90_multiplier"])})
    curves = {
        "forecast": pv,
        "load_forecast": load,
        "battery_forecast": battery,
        "grid_forecast": grid,
        "curtailment_forecast": curtailment,
        "pv_p10_forecast": pv_p10,
        "pv_p90_forecast": pv_p90,
    }
    return curves, price_source


async def latest_pv_uncertainty_bands(session: AsyncSession) -> dict[str, dict[str, float]]:
    latest_date = (await session.execute(text("select max(calibration_date) from pv_uncertainty_bands"))).scalar_one_or_none()
    if latest_date is None:
        return {}
    rows = (await session.execute(
        text("select cloud_class, p10_multiplier, p90_multiplier from pv_uncertainty_bands where calibration_date = :d"),
        {"d": latest_date},
    )).all()
    return {row.cloud_class: {"p10_multiplier": float(row.p10_multiplier), "p90_multiplier": float(row.p90_multiplier)} for row in rows}


@app.get("/dashboard/curves")
async def dashboard_curves(
    window: Literal["5m", "hour", "day", "week", "month", "year"] = "day",
    offset: int | None = Query(default=None, ge=-120, le=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    duration, step_seconds, table_name = WINDOWS[window]
    start, end, now_ = dashboard_window_bounds(window, duration, period_offset=offset)
    if table_name == "power_curve_points":
        bucket = _bucket_expr("bucket_start", step_seconds)
        source_filter = "bucket_start >= :start and bucket_start <= :now_"
        power_expr = "avg(power_w)"
        delivered_expr = "avg(delivered_w)"
        returned_expr = "avg(returned_w)"
        net_expr = "avg(net_w)"
    else:
        bucket = "bucket_start"
        source_filter = "granularity_seconds = :step_seconds and bucket_start >= :start and bucket_start <= :now_"
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
    """), {"start": start, "end": end, "now_": now_, "step_seconds": step_seconds})).mappings().all()
    series = {"solar": [], "battery": [], "grid": [], "household": []}
    for row in rows:
        series[row["source"]].append({
            "timestamp": row["ts"].replace(tzinfo=timezone.utc).isoformat(),
            "power_w": round(float(row["power_w"] or 0)),
            "delivered_w": round(float(row["delivered_w"])) if row["delivered_w"] is not None else None,
            "returned_w": round(float(row["returned_w"])) if row["returned_w"] is not None else None,
            "net_w": round(float(row["net_w"])) if row["net_w"] is not None else round(float(row["power_w"] or 0)),
        })

    plan_row = await latest_slot_plan(session)
    latest_plan_status = plan_row.get("solver_status") if plan_row is not None else None
    if plan_row is not None and latest_plan_status == "FALLBACK":
        plan_row = await latest_slot_plan(session, include_fallback=False)
    plan_status = "missing"
    plan_generated_at: str | None = None
    curves: dict[str, list[dict[str, Any]]] = {
        "forecast": [],
        "load_forecast": [],
        "battery_forecast": [],
        "grid_forecast": [],
        "curtailment_forecast": [],
        "pv_p10_forecast": [],
        "pv_p90_forecast": [],
    }
    price_source_points: list[dict[str, Any]] = []
    if plan_row is not None:
        generated_at = plan_row["generated_at"]
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        plan_generated_at = generated_at.isoformat()
        is_fresh = generated_at > datetime.now(timezone.utc) - timedelta(minutes=PLAN_STALE_MINUTES)
        # A FALLBACK plan (solver couldn't produce a real solution, e.g. Open-Meteo was
        # unreachable) is a flat pv_forecast_w=0/load_forecast_w=0 hold — persisted with a fresh
        # generated_at like any other plan, so freshness alone can't tell it apart from a real
        # forecast. Treat it the same as "no plan": never show a fabricated flat-zero line.
        is_real_plan = plan_row.get("solver_status") != "FALLBACK"
        if is_fresh and is_real_plan:
            plan_status = "ok"
            battery_conf = await battery_settings(session)
            capacity_wh = float(battery_conf.get("capacity_wh", 10240))
            mqtt_payload = latest_mqtt_status()
            soc_now = (
                coerce_float_status_value("soc", mqtt_payload.get("soc", 50))
                if mqtt_payload.get("soc") not in (None, "")
                else 50.0
            )
            uncertainty_bands = await latest_pv_uncertainty_bands(session)
            curves, price_source_points = build_plan_curves(plan_row["payload"], capacity_wh, soc_now, now_, end, uncertainty_bands)
            curves = {key: interpolate_points(points, step_seconds) for key, points in curves.items()}
        elif not is_fresh:
            plan_status = "stale"
        else:
            plan_status = "fallback"
    elif latest_plan_status == "FALLBACK":
        plan_status = "fallback"

    return {
        "window": window,
        "period_offset": offset,
        "granularity_seconds": step_seconds,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "plan_status": plan_status,
        "plan_generated_at": plan_generated_at,
        "forecast": curves["forecast"],
        "pv_p10_forecast": curves["pv_p10_forecast"],
        "pv_p90_forecast": curves["pv_p90_forecast"],
        "load_forecast": curves["load_forecast"],
        "battery_forecast": curves["battery_forecast"],
        "grid_forecast": curves["grid_forecast"],
        "curtailment_forecast": curves["curtailment_forecast"],
        "price_source": price_source_points,
        "series": series,
    }


@app.get("/dashboard/forecast-quality")
async def dashboard_forecast_quality(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Small quality block for the dashboard (spec 5.3): yesterday's MAE/bias per curve/horizon."""
    latest_date = (await session.execute(text("select max(for_date) from forecast_accuracy_daily"))).scalar_one_or_none()
    if latest_date is None:
        return {"for_date": None, "curves": {}}
    rows = (await session.execute(
        text("select curve, horizon, mae, bias, sample_count from forecast_accuracy_daily where for_date = :d"),
        {"d": latest_date},
    )).mappings().all()
    curves: dict[str, dict[str, Any]] = {}
    for row in rows:
        curves.setdefault(row["curve"], {})[row["horizon"]] = {
            "mae": round(float(row["mae"]), 1),
            "bias": round(float(row["bias"]), 1),
            "sample_count": row["sample_count"],
        }
    return {"for_date": latest_date.isoformat(), "curves": curves}


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


@app.get("/api/v1/surplus")
async def api_v1_surplus(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    battery = await battery_status(session)
    grid = await grid_status(session)
    settings = await battery_settings(session)
    return build_surplus_payload(grid, battery, settings)


@app.get("/api/surplus")
async def api_surplus(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await api_v1_surplus(session)


@app.get("/api/forecast")
async def api_forecast(hours_ahead: int = 12, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    hours = max(1, min(48, hours_ahead))
    now_ = datetime.now(timezone.utc)
    end = now_ + timedelta(hours=hours)
    plan_row = await latest_slot_plan(session)
    latest_plan_status = plan_row.get("solver_status") if plan_row is not None else None
    if plan_row is not None and latest_plan_status == "FALLBACK":
        plan_row = await latest_slot_plan(session, include_fallback=False)
    plan_generated_at = plan_row["generated_at"] if plan_row is not None else None
    if plan_generated_at is not None and plan_generated_at.tzinfo is None:
        plan_generated_at = plan_generated_at.replace(tzinfo=timezone.utc)
    if plan_generated_at is None or plan_generated_at <= now_ - timedelta(minutes=PLAN_STALE_MINUTES):
        status = "fallback" if plan_row is None and latest_plan_status == "FALLBACK" else "missing" if plan_row is None else "stale"
        return {"hours_ahead": hours, "plan_status": status, "points": []}
    if plan_row.get("solver_status") == "FALLBACK":
        # See dashboard_curves: a FALLBACK plan is a flat pv_forecast_w=0 hold, not a real
        # forecast — treat it the same as no plan rather than returning fabricated zeros.
        return {"hours_ahead": hours, "plan_status": "fallback", "points": []}
    battery_conf = await battery_settings(session)
    capacity_wh = float(battery_conf.get("capacity_wh", 10240))
    mqtt_payload = latest_mqtt_status()
    soc_now = (
        coerce_float_status_value("soc", mqtt_payload.get("soc", 50))
        if mqtt_payload.get("soc") not in (None, "")
        else 50.0
    )
    curves, _ = build_plan_curves(plan_row["payload"], capacity_wh, soc_now, now_, end)
    return {"hours_ahead": hours, "plan_status": "ok", "points": interpolate_points(curves["forecast"], 60)}


@app.post("/api/control/battery", dependencies=MUTATION_AUTH)
async def api_control_battery(request: AgentBatteryControlRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if request.setpoint_w > 0:
        override = BatteryOverrideRequest(mode="force_charge", watts=request.setpoint_w, duration_seconds=request.duration_minutes * 60)
        action = "charge"
    elif request.setpoint_w < 0:
        override = BatteryOverrideRequest(mode="force_discharge", watts=abs(request.setpoint_w), duration_seconds=request.duration_minutes * 60)
        action = "discharge"
    else:
        active_override = await current_battery_override(session)
        if active_override is not None:
            return {"status": "ok", "action": "hold", "setpoint_w": request.setpoint_w, "duration_minutes": request.duration_minutes, "override": active_override}
        override = BatteryOverrideRequest(mode="none", watts=None, duration_seconds=None)
        action = "hold"
    result = await set_battery_override(override, session)
    return {"status": "ok", "action": action, "setpoint_w": request.setpoint_w, "duration_minutes": request.duration_minutes, "override": result}


@app.post("/api/agent/decisions", status_code=201, dependencies=MUTATION_AUTH)
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


def _normalize_battery_override_mode(mode: str | None) -> str:
    if mode == "force_on":
        return "force_charge"
    if mode == "force_off":
        return "force_idle"
    return mode or "none"


async def current_battery_override(session: AsyncSession) -> dict[str, Any] | None:
    row = (await session.execute(text("""
        select mode, watts, duration_seconds, expires_at,
               coalesce(override_soc_limits, false) as override_soc_limits
        from battery_override
        where id = 1
    """))).mappings().first()
    if row is None or row["mode"] in (None, "none"):
        return None
    expires_at = row["expires_at"]
    if expires_at is not None:
        expires_at_utc = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at_utc:
            return None
    return {
        "status": "ok",
        "mode": row["mode"],
        "watts": row["watts"],
        "duration_seconds": row["duration_seconds"],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "override_soc_limits": bool(row["override_soc_limits"]),
        "preserved": True,
    }


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


@app.post("/api/messages", status_code=201, dependencies=MUTATION_AUTH)
async def create_agent_message(request: AgentMessageCreate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_messages (sender, category, subject, body, related_decision_id, thread_id, severity, operator_ack_at, agent_ack_at)
        values (:sender, :category, :subject, :body, :related_decision_id, :thread_id, :severity, case when :sender = 'operator' then now() else null end, case when :sender = 'agent' then now() else null end)
        returning id, created_at
    """), request.model_dump())).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=timezone.utc).isoformat()}


@app.patch("/api/messages/{message_id}/read", dependencies=MUTATION_AUTH)
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


@app.patch("/api/messages/{message_id}/archive", dependencies=MUTATION_AUTH)
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


@app.patch("/api/messages/{message_id}/ack", dependencies=MUTATION_AUTH)
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


@app.delete("/api/messages/{message_id}", dependencies=MUTATION_AUTH)
async def delete_agent_message(message_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (await session.execute(text("delete from agent_messages where id = :id returning id"), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    await session.commit()
    return {"status": "ok", "id": row["id"]}


@app.post("/battery/override", dependencies=MUTATION_AUTH)
async def set_battery_override(request: BatteryOverrideRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    mode = _normalize_battery_override_mode(request.mode)
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
    if not request.override_soc_limits and mode == "force_discharge" and soc_value is not None and soc_value <= soc_floor:
        raise HTTPException(status_code=422, detail=f"discharge blocked because SoC {soc_value:g}% is at or below configured floor {soc_floor}%")
    if not request.override_soc_limits and mode == "force_charge" and soc_value is not None and soc_value >= soc_ceiling:
        raise HTTPException(status_code=422, detail=f"charge blocked because SoC {soc_value:g}% is at or above configured ceiling {soc_ceiling}%")
    configured_max_w = int(settings.get("max_charge_w", 0))
    hardware_max_w = int(settings.get("max_charge_a", 30)) * int(settings.get("nominal_v", 48))
    max_charge_w = min(configured_max_w, hardware_max_w)
    max_discharge_w = int(settings.get("max_discharge_w", 5000))
    max_allowed_w = max_discharge_w if mode == "force_discharge" else max_charge_w
    if request.watts is not None and request.watts > max_allowed_w:
        limit_name = "MAX_DISCHARGE_W" if mode == "force_discharge" else "MAX_CHARGE_W"
        raise HTTPException(status_code=422, detail=f"watts must not exceed {limit_name} ({max_allowed_w})")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.duration_seconds) if request.duration_seconds else None
    await session.execute(
        text("""
            insert into battery_override (id, mode, watts, duration_seconds, expires_at, override_soc_limits, updated_at)
            values (1, :mode, :watts, :duration_seconds, :expires_at, :override_soc_limits, now())
            on conflict (id) do update set mode=:mode, watts=:watts, duration_seconds=:duration_seconds,
                expires_at=:expires_at, override_soc_limits=:override_soc_limits, updated_at=now()
        """),
        {
            "mode": mode,
            "watts": request.watts,
            "duration_seconds": request.duration_seconds,
            "expires_at": expires_at,
            "override_soc_limits": request.override_soc_limits,
        },
    )
    await session.commit()
    payload = request.model_dump()
    payload["mode"] = mode
    mqtt.client.publish("minyad/control/override", json.dumps(payload), qos=0, retain=False)
    return {"status": "ok", **payload}


@app.delete("/battery/override", dependencies=MUTATION_AUTH)
async def clear_battery_override(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("update battery_override set mode='none', watts=null, duration_seconds=null, expires_at=null, override_soc_limits=false, updated_at=now() where id=1"))
    await session.commit()
    mqtt.client.publish("minyad/control/override", json.dumps({"mode": "none"}), qos=0, retain=False)
    return {"status": "ok", "mode": "none"}


@app.get("/api/battery/settings")
@app.get("/battery/settings")
async def get_battery_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await battery_settings(session)


@app.put("/api/battery/settings", dependencies=MUTATION_AUTH)
@app.put("/battery/settings", dependencies=MUTATION_AUTH)
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
    merged_after_validation = {**current, **data}
    await session.execute(
        text("""
            insert into settings (key, value, encrypted, updated_at) values ('strategy.bridge_stale_seconds', :value, false, now())
            on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
        """),
        {"value": str(derived_bridge_stale_seconds(merged_after_validation))},
    )
    await session.commit()
    settings = await battery_settings(session)
    await publish_battery_mqtt_settings(settings)
    mqtt.client.publish("minyad/control/override", json.dumps({"mode": "reload_settings"}), qos=0, retain=False)
    return settings
