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
from zoneinfo import ZoneInfo
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
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

BATTERY_KEYS = {
    "start_w": (100, 5000),
    "stop_w": (0, 5000),
    "start_duration": (10, 3600),
    "stop_duration": (10, 3600),
    "cooldown": (60, 7200),
    "max_charge_w": (100, 5000),
    "max_discharge_w": (0, 5000),
    "nominal_v": (40, 60),
    "inverter_retries": (1, 10),
    "inverter_delay": (1, 30),
}
TEXT_KEYS = {"inverter_ip"}

STRATEGY_DEFAULTS = {
    "ghi_solar_rich_threshold": "4.5",
    "ghi_solar_poor_threshold": "1.5",
    "dynamic_tariff_ceiling_eur_kwh": "0.10",
    "daily_recalculate_local_time": "22:00",
}
STRATEGY_NUMERIC_LIMITS = {
    "ghi_solar_rich_threshold": (0.0, 20.0),
    "ghi_solar_poor_threshold": (0.0, 20.0),
    "dynamic_tariff_ceiling_eur_kwh": (-1.0, 5.0),
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


def handle_status_mqtt(topic: str, payload: bytes) -> None:
    key = MQTT_STATUS_KEYS.get(topic)
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
        key = MQTT_STATUS_KEYS.get(message.topic)
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
                "minyad/solar/+",
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
    return {key: value for key, value in payload.items() if not key.startswith("grid_")}


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


class ApiKeyCreate(BaseModel):
    name: str


class SystemSettingsUpdate(BaseModel):
    debug_logging: bool | None = None


class AssetSteeringSettingsUpdate(BaseModel):
    ghi_solar_rich_threshold: float | None = None
    ghi_solar_poor_threshold: float | None = None
    dynamic_tariff_ceiling_eur_kwh: float | None = None
    daily_recalculate_local_time: str | None = None

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


class BatterySettingsUpdate(BaseModel):
    start_w: int | None = None
    stop_w: int | None = None
    start_duration: int | None = None
    stop_duration: int | None = None
    cooldown: int | None = None
    max_charge_w: int | None = None
    max_discharge_w: int | None = None
    inverter_ip: str | None = None
    inverter_retries: int | None = None
    inverter_delay: int | None = None

    @field_validator("inverter_ip")
    @classmethod
    def validate_ip(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split(".")
        if len(parts) != 4 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            raise ValueError("inverter_ip must be a valid IPv4 address")
        return value


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
    mqtt.subscribe("minyad/solar/+", handle_status_mqtt)
    asyncio.create_task(_refresh_debug_setting())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    }


@app.get("/system-settings")
async def get_system_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(text("select value from settings where key = 'system.debug_logging'"))
    val = result.scalar_one_or_none() or "false"
    return {"debug_logging": val == "true"}


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
        await session.commit()
        _apply_log_level(update.debug_logging)
    return await get_system_settings(session)


async def asset_steering_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'strategy.%'"))
    values = {row.key.removeprefix("strategy."): row.value for row in result}
    merged = {**STRATEGY_DEFAULTS, **values}
    return {
        "ghi_solar_rich_threshold": float(merged["ghi_solar_rich_threshold"]),
        "ghi_solar_poor_threshold": float(merged["ghi_solar_poor_threshold"]),
        "dynamic_tariff_ceiling_eur_kwh": float(merged["dynamic_tariff_ceiling_eur_kwh"]),
        "daily_recalculate_local_time": merged["daily_recalculate_local_time"],
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
    payload.setdefault("state", "IDLE")
    payload["override_mode"] = override.scalar_one_or_none() or "none"
    for key in ("soc", "soh", "power_w", "charge_i"):
        if key in payload:
            payload[key] = coerce_int_status_value(key, payload[key])
    if "voltage" in payload:
        payload["voltage"] = coerce_float_status_value("voltage", payload["voltage"])
    if "available" in payload and payload["available"] is not None:
        payload["available"] = str(payload["available"]).lower() == "true"
    enrich_bridge_health(payload)
    setpoint_power_w = active_battery_setpoint_w(payload)
    if setpoint_power_w is not None or "power_w" in payload:
        battery_power_w = setpoint_power_w if setpoint_power_w is not None else int(payload["power_w"])
        await store_power_curve_point(session, "battery", battery_power_w, metadata={"soc": payload.get("soc"), "mode": payload.get("mode"), "setpoint_delta_w": battery_power_w})
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



WINDOWS = {
    "5m": (timedelta(minutes=5), 60, "power_curve_points"),
    "hour": (timedelta(hours=1), 60, "power_curve_points"),
    "day": (timedelta(days=1), 60, "power_curve_points"),
    "week": (timedelta(weeks=1), 900, "power_curve_rollups"),
    "month": (timedelta(days=31), 3600, "power_curve_rollups"),
    "year": (timedelta(days=366), 3600, "power_curve_rollups"),
}


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
    end = datetime.now(timezone.utc)
    start = end - duration
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
    series = {"solar": [], "battery": [], "grid": []}
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


@app.post("/battery/override")
async def set_battery_override(request: BatteryOverrideRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = await battery_settings(session)
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


@app.get("/battery/settings")
async def get_battery_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await battery_settings(session)


@app.put("/battery/settings")
async def update_battery_settings(update: BatterySettingsUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    current = await battery_settings(session)
    merged = {**current, **data}
    if "stop_w" in merged and "start_w" in merged and int(merged["stop_w"]) > int(merged["start_w"]):
        raise HTTPException(status_code=422, detail="stop_w must be less than or equal to start_w")
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
    mqtt.client.publish("minyad/control/override", json.dumps({"mode": "reload_settings"}), qos=0, retain=False)
    return await battery_settings(session)
