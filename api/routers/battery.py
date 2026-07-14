"""Battery status/override/settings/control routes, plus the shared power-curve-point
writer and household-load helper that grid.py and dashboard.py also depend on."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from api.payload_helpers import (
        BATTERY_DEFAULTS,
        _normalize_battery_override_mode,
        _validate_battery_override_limits,
        active_battery_setpoint_w,
        battery_curve_power_w,
        battery_status_payload,
        cached_status_is_incomplete,
        coerce_float_status_value,
        coerce_int_status_value,
        compute_household_load,
        derive_battery_state,
        derived_bridge_stale_seconds,
        enrich_bridge_health,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        BATTERY_DEFAULTS,
        _normalize_battery_override_mode,
        _validate_battery_override_limits,
        active_battery_setpoint_w,
        battery_curve_power_w,
        battery_status_payload,
        cached_status_is_incomplete,
        coerce_float_status_value,
        coerce_int_status_value,
        compute_household_load,
        derive_battery_state,
        derived_bridge_stale_seconds,
        enrich_bridge_health,
    )
try:
    from api.mqtt_handlers import (
        collect_retained_mqtt_status,
        latest_mqtt_status,
        publish_battery_mqtt_settings,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import (
        collect_retained_mqtt_status,
        latest_mqtt_status,
        publish_battery_mqtt_settings,
    )
try:
    from api.state import (
        MUTATION_AUTH,
        SETTING_UPSERT_QUERY,
        TOPIC_CONTROL_OVERRIDE,
        SessionDep,
        mqtt,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        MUTATION_AUTH,
        SETTING_UPSERT_QUERY,
        TOPIC_CONTROL_OVERRIDE,
        SessionDep,
        mqtt,
    )

router = APIRouter()
LOGGER = logging.getLogger(__name__)

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

# battery.* / strategy3.* keys the LP uses that the surplus endpoint also exposes as metadata,
# duplicated from minyad.strategy.v3.constants.DEFAULTS to keep this service's DB-only boundary
# with the strategy package (mirrors _classify_cloud_cover in payload_helpers).
BATTERY_LP_META_DEFAULTS = {
    "battery.capacity_wh": 10240.0,
    "strategy3.one_way_efficiency": 0.95,
    "battery.max_charge_w": 1440.0,
    "battery.max_charge_a": 30.0,
    "battery.nominal_v": 48.0,
    "battery.max_discharge_w": 5000.0,
}


class AgentBatteryControlRequest(BaseModel):
    setpoint_w: int = Field(ge=-5000, le=5000)
    duration_minutes: int = Field(default=15, ge=1, le=240)


class BatteryOverrideRequest(BaseModel):
    mode: Literal["none", "force_on", "force_charge", "force_off", "force_idle", "force_discharge", "pause"]
    watts: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1)
    override_soc_limits: bool = False

    @model_validator(mode="after")
    def validate_required_fields(self) -> BatteryOverrideRequest:
        if self.mode in {"force_on", "force_charge", "force_discharge"} and self.watts is None:
            raise ValueError("watts is required for force_charge and force_discharge")
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


async def battery_settings(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key like 'battery.%'"))
    settings: dict[str, Any] = dict(BATTERY_DEFAULTS)
    for row in result:
        name = row.key.removeprefix("battery.")
        if name.startswith("status."):
            continue
        settings[name] = row.value if name in TEXT_KEYS else int(row.value)
    return settings


async def battery_lp_meta(session: AsyncSession) -> dict[str, Any]:
    """Battery assumptions actually used by the strategy-v3 LP (capacity, round-trip
    efficiency, effective power limits) for the minyad_forecast battery-metadata block. Real
    configured values only — never a substitute default presented as if it were configured."""
    rows = (await session.execute(
        text("select key, value from settings where key = any(:keys)"),
        {"keys": list(BATTERY_LP_META_DEFAULTS)},
    )).all()
    values = {row.key: row.value for row in rows}

    def _f(key: str) -> float:
        raw = values.get(key)
        try:
            return float(raw) if raw not in (None, "") else float(BATTERY_LP_META_DEFAULTS[key])
        except (TypeError, ValueError):
            return float(BATTERY_LP_META_DEFAULTS[key])

    capacity_wh = _f("battery.capacity_wh")
    max_charge_w = _f("battery.max_charge_w")
    max_charge_a = _f("battery.max_charge_a")
    nominal_v = _f("battery.nominal_v")
    return {
        "capacity_kwh": round(capacity_wh / 1000.0, 3),
        "charge_efficiency": _f("strategy3.one_way_efficiency"),
        "max_charge_w": int(min(max_charge_w, max_charge_a * nominal_v)),
        "max_discharge_w": int(_f("battery.max_discharge_w")),
    }


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
    timestamp = timestamp or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
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


@router.get("/battery/status")
async def battery_status(session: SessionDep) -> dict[str, Any]:
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


@router.post("/api/control/battery", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
async def api_control_battery(request: AgentBatteryControlRequest, session: SessionDep) -> Any:
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
    if isinstance(result, JSONResponse):
        return result
    return {"status": "ok", "action": action, "setpoint_w": request.setpoint_w, "duration_minutes": request.duration_minutes, "override": result}


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
        expires_at_utc = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at_utc:
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


@router.post("/battery/override", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
async def set_battery_override(request: BatteryOverrideRequest, session: SessionDep) -> Any:
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
    configured_max_w = int(settings.get("max_charge_w", 0))
    hardware_max_w = int(settings.get("max_charge_a", 30)) * int(settings.get("nominal_v", 48))
    max_charge_w = min(configured_max_w, hardware_max_w)
    max_discharge_w = int(settings.get("max_discharge_w", 5000))
    max_allowed_w = max_discharge_w if mode == "force_discharge" else max_charge_w
    validation_error = _validate_battery_override_limits(request, mode, soc_value, soc_floor, soc_ceiling, max_allowed_w)
    if validation_error is not None:
        return JSONResponse(status_code=422, content={"detail": validation_error})
    expires_at = datetime.now(UTC) + timedelta(seconds=request.duration_seconds) if request.duration_seconds else None
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
    mqtt.client.publish(TOPIC_CONTROL_OVERRIDE, json.dumps(payload), qos=0, retain=False)
    return {"status": "ok", **payload}


@router.delete("/battery/override", dependencies=MUTATION_AUTH)
async def clear_battery_override(session: SessionDep) -> dict[str, str]:
    await session.execute(text("update battery_override set mode='none', watts=null, duration_seconds=null, expires_at=null, override_soc_limits=false, updated_at=now() where id=1"))
    await session.commit()
    mqtt.client.publish(TOPIC_CONTROL_OVERRIDE, json.dumps({"mode": "none"}), qos=0, retain=False)
    return {"status": "ok", "mode": "none"}


@router.get("/api/battery/settings")
@router.get("/battery/settings")
async def get_battery_settings(session: SessionDep) -> dict[str, Any]:
    return await battery_settings(session)


@router.put("/api/battery/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
@router.put("/battery/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
async def update_battery_settings(update: BatterySettingsUpdate, session: SessionDep) -> dict[str, Any]:
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
            text(SETTING_UPSERT_QUERY),
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
    mqtt.client.publish(TOPIC_CONTROL_OVERRIDE, json.dumps({"mode": "reload_settings"}), qos=0, retain=False)
    return settings
