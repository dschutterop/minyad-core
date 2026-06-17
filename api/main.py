"""Minyad REST API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_session
from shared.mqtt_client import MinyadMqttClient

app = FastAPI(title="Minyad API")
mqtt = MinyadMqttClient("minyad-api")

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
    override = await session.execute(text("select mode from battery_override where id = 1"))
    payload.setdefault("state", "IDLE")
    payload["override_mode"] = override.scalar_one_or_none() or "none"
    for key in ("soc", "soh", "power_w", "charge_i"):
        if key in payload and payload[key] is not None:
            payload[key] = int(payload[key])
    if "voltage" in payload and payload["voltage"] is not None:
        payload["voltage"] = float(payload["voltage"])
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
