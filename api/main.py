"""Minyad REST API."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
import paho.mqtt.client as paho_mqtt
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_session
from shared.mqtt_client import MinyadMqttClient

app = FastAPI(title="Minyad API")
mqtt = MinyadMqttClient("minyad-api")
LOGGER = logging.getLogger(__name__)

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
}
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
    "nominal_v": (40, 60),
    "inverter_retries": (1, 10),
    "inverter_delay": (1, 30),
}
TEXT_KEYS = {"inverter_ip"}


def handle_status_mqtt(topic: str, payload: bytes) -> None:
    key = MQTT_STATUS_KEYS.get(topic)
    if key is None:
        LOGGER.debug("Ignoring unsupported status MQTT topic %s", topic)
        return
    with MQTT_STATUS_LOCK:
        MQTT_STATUS[key] = payload.decode()


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
    retained_status: dict[str, str] = {}
    received = Event()
    expected_keys = set(MQTT_STATUS_KEYS.values())

    def on_message(_client: paho_mqtt.Client, _userdata: object, message: paho_mqtt.MQTTMessage) -> None:
        key = MQTT_STATUS_KEYS.get(message.topic)
        if key is None:
            return
        retained_status[key] = message.payload.decode()
        if expected_keys.issubset(retained_status):
            received.set()

    client = paho_mqtt.Client(
        paho_mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"minyad-api-retained-status-{uuid4()}",
    )
    client.on_message = on_message
    client.connect(mqtt.config.host, mqtt.config.port, mqtt.config.keepalive)
    client.loop_start()
    try:
        for topic in ("minyad/battery/+", "minyad/bridge/+", "minyad/control/+"):
            client.subscribe(topic)
        received.wait(timeout_seconds)
    finally:
        client.loop_stop()
        client.disconnect()

    if retained_status:
        with MQTT_STATUS_LOCK:
            MQTT_STATUS.update(retained_status)
    return retained_status


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
    mqtt.start()
    mqtt.subscribe("minyad/battery/+", handle_status_mqtt)
    mqtt.subscribe("minyad/bridge/+", handle_status_mqtt)
    mqtt.subscribe("minyad/control/+", handle_status_mqtt)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    payload.update(latest_mqtt_status())
    if cached_status_is_incomplete(payload):
        try:
            payload.update(collect_retained_mqtt_status())
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT status snapshot")
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
    return payload


@app.post("/battery/override")
async def set_battery_override(request: BatteryOverrideRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = await battery_settings(session)
    configured_max_w = int(settings.get("max_charge_w", 0))
    hardware_max_w = int(settings.get("max_charge_a", 30)) * int(settings.get("nominal_v", 48))
    max_charge_w = min(configured_max_w, hardware_max_w)
    if request.watts is not None and request.watts > max_charge_w:
        raise HTTPException(status_code=422, detail=f"watts must not exceed MAX_CHARGE_W ({max_charge_w})")
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
