"""Minyad REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
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
MQTT_STATUS_KEYS.update(GRID_STATUS_KEYS)
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
        "mode_label",
        "charge_i",
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
            for topic in ("minyad/battery/+", "minyad/bridge/+", "minyad/control/+", "minyad/grid/+"):
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



def coerce_grid_status(payload: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(payload)
    int_keys = {
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
        if coerced.get(key) not in (None, ""):
            coerced[key] = int(coerced[key])
    for key in float_keys:
        if coerced.get(key) not in (None, ""):
            coerced[key] = float(coerced[key])
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
    missing_keys = [k for k in ("soc", "soh", "power_w", "voltage", "mode", "mode_label", "charge_i", "bridge_status", "bridge_last_seen") if not cache.get(k)]
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
        select id, timestamp, source, soc_floor, soc_ceiling, charge_rate_w, discharge_allowed,
               battery_soc_at_time, grid_power_at_time, trigger_reason, ack_received, ack_latency_ms
        from setpoint_log order by timestamp desc limit 1
    """))).mappings().first()
    recent_setpoints = (await session.execute(text("""
        select id, timestamp, source, charge_rate_w, discharge_allowed, trigger_reason, ack_received
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


@app.get("/battery/status")
async def battery_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    status = await session.execute(text("select key, value from settings where key like 'battery.status.%'"))
    payload: dict[str, Any] = {row.key.removeprefix("battery.status."): row.value for row in status}
    LOGGER.debug("battery_status: db keys=%s", sorted(payload.keys()))
    mqtt_cache = latest_mqtt_status()
    LOGGER.debug("battery_status: mqtt cache keys=%s", sorted(mqtt_cache.keys()))
    payload.update(coerce_grid_status(mqtt_cache))
    if cached_status_is_incomplete(payload):
        missing = [k for k in ("soc", "soh", "power_w", "voltage", "mode", "mode_label", "charge_i", "bridge_status", "bridge_last_seen") if not payload.get(k)]
        LOGGER.debug("battery_status: incomplete, missing=%s — attempting retained fetch", missing)
        try:
            retained = collect_retained_mqtt_status()
            LOGGER.debug("battery_status: retained fetch returned keys=%s", sorted(retained.keys()))
            payload.update(coerce_grid_status(retained))
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT status snapshot")
    else:
        LOGGER.debug("battery_status: cache complete, skipping retained fetch")
    override = await session.execute(text("select mode from battery_override where id = 1"))
    payload.setdefault("state", "IDLE")
    payload["override_mode"] = override.scalar_one_or_none() or "none"
    for key in ("soc", "soh", "power_w", "charge_i"):
        if key in payload and payload[key] is not None:
            payload[key] = int(payload[key])
    if "voltage" in payload and payload["voltage"] is not None:
        payload["voltage"] = float(payload["voltage"])
    if "mode" in payload and payload["mode"] is not None:
        payload["mode"] = int(payload["mode"])
    if "available" in payload and payload["available"] is not None:
        payload["available"] = str(payload["available"]).lower() == "true"
    enrich_bridge_health(payload)
    LOGGER.debug("battery_status: final keys=%s", sorted(payload.keys()))
    return payload



@app.get("/dsmr/status")
async def dsmr_status() -> dict[str, Any]:
    grid_payload = {key: value for key, value in latest_mqtt_status().items() if key.startswith("grid_")}
    if not grid_payload:
        try:
            grid_payload.update(collect_retained_mqtt_status())
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT grid snapshot")
    return coerce_grid_status({key: value for key, value in grid_payload.items() if key.startswith("grid_")})


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
