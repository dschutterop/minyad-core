"""Minyad REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from api.dryad import (
        DRYAD_CACHE_SECONDS,
        build_dryad_payload,
        load_dryad_history,
        load_dryad_inputs,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from dryad import (
        DRYAD_CACHE_SECONDS,
        build_dryad_payload,
        load_dryad_history,
        load_dryad_inputs,
    )
try:
    from api.payload_helpers import (
        BATTERY_DEFAULTS,
        GRID_STATUS_KEYS,
        MINYAD_FORECAST_MODEL_VERSION,
        MINYAD_FORECAST_SCENARIO_COUNT,
        MQTT_STATUS_KEYS,
        PLAN_STALE_MINUTES,
        PRIVATE_MODULES_AVAILABLE,
        SOLAR_STATUS_KEYS,
        SURPLUS_API_VERSION,
        UTC_OFFSET_SUFFIX,
        _add_months,
        _battery_phase,
        _bucket_expr,
        _classify_cloud_cover,
        _normalize_battery_override_mode,
        _numeric_w,
        _parse_log_datetime,
        _serialize_log_row,
        _slot_battery_w,
        _status_text,
        _strategy_module_unavailable_outcome,
        _validate_battery_override_limits,
        active_battery_setpoint_w,
        battery_curve_power_w,
        battery_health_component,
        battery_status_payload,
        build_plan_curves,
        build_surplus_payload,
        cached_status_is_incomplete,
        coerce_float_status_value,
        coerce_grid_status,
        coerce_int_status_value,
        component_status,
        compute_household_load,
        dashboard_window_bounds,
        derive_battery_state,
        derived_bridge_stale_seconds,
        enrich_bridge_health,
        grid_health_component,
        grid_status_payload,
        interpolate_points,
        mqtt_status_key,
        parse_bridge_last_seen,
        parse_status_timestamp,
        serialize_agent_decision,
        serialize_agent_message,
        serialize_control_decision,
        setpoint_log_select_list,
        solar_dynamic_status_key,
        solar_health_component,
        solar_status_payload,
        value_is_fresh_iso,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        BATTERY_DEFAULTS,
        GRID_STATUS_KEYS,
        MINYAD_FORECAST_MODEL_VERSION,
        MINYAD_FORECAST_SCENARIO_COUNT,
        MQTT_STATUS_KEYS,
        PLAN_STALE_MINUTES,
        PRIVATE_MODULES_AVAILABLE,
        SOLAR_STATUS_KEYS,
        SURPLUS_API_VERSION,
        UTC_OFFSET_SUFFIX,
        _add_months,
        _battery_phase,
        _bucket_expr,
        _classify_cloud_cover,
        _normalize_battery_override_mode,
        _numeric_w,
        _parse_log_datetime,
        _serialize_log_row,
        _slot_battery_w,
        _status_text,
        _strategy_module_unavailable_outcome,
        _validate_battery_override_limits,
        active_battery_setpoint_w,
        battery_curve_power_w,
        battery_health_component,
        battery_status_payload,
        build_plan_curves,
        build_surplus_payload,
        cached_status_is_incomplete,
        coerce_float_status_value,
        coerce_grid_status,
        coerce_int_status_value,
        component_status,
        compute_household_load,
        dashboard_window_bounds,
        derive_battery_state,
        derived_bridge_stale_seconds,
        enrich_bridge_health,
        grid_health_component,
        grid_status_payload,
        interpolate_points,
        mqtt_status_key,
        parse_bridge_last_seen,
        parse_status_timestamp,
        serialize_agent_decision,
        serialize_agent_message,
        serialize_control_decision,
        setpoint_log_select_list,
        solar_dynamic_status_key,
        solar_health_component,
        solar_status_payload,
        value_is_fresh_iso,
    )
try:
    from api.mqtt_handlers import (
        build_health_status,
        collect_retained_mqtt_status,
        handle_status_mqtt,
        handle_trade_price_mqtt,
        latest_mqtt_status,
        latest_trade_prices,
        publish_battery_mqtt_settings,
        publish_trade_mqtt_settings,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import (
        collect_retained_mqtt_status,
        handle_status_mqtt,
        handle_trade_price_mqtt,
        latest_mqtt_status,
        latest_trade_prices,
        publish_battery_mqtt_settings,
        publish_trade_mqtt_settings,
    )
try:
    from api.state import (
        DEBUG_LOGGING_SETTING_QUERY,
        DRYAD_CACHE,
        DRYAD_CACHE_LOCK,
        MESSAGE_NOT_FOUND_DETAIL,
        MUTATION_AUTH,
        SETTING_UPSERT_QUERY,
        TOPIC_CONTROL_OVERRIDE,
        TRADE_PRICE_CACHE,
        SessionDep,
        _apply_log_level,
        _refresh_debug_setting,
        app,
        mqtt,
        require_api_key,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        DEBUG_LOGGING_SETTING_QUERY,
        DRYAD_CACHE,
        DRYAD_CACHE_LOCK,
        MESSAGE_NOT_FOUND_DETAIL,
        MUTATION_AUTH,
        SETTING_UPSERT_QUERY,
        TOPIC_CONTROL_OVERRIDE,
        TRADE_PRICE_CACHE,
        SessionDep,
        _apply_log_level,
        _refresh_debug_setting,
        app,
        mqtt,
        require_api_key,
    )
try:
    from api.routers import health as health_router
    from api.routers import settings as settings_router
    from api.routers.health import (
        SystemSettingsUpdate,
        get_system_settings,
        health,
        update_system_settings,
    )
    from api.routers.settings import (
        ALLOWED_TRADE_PRICE_HOST,
        CLAUDE_AGENT_DEFAULTS,
        STRATEGY3_DEFAULTS,
        STRATEGY_DEFAULTS,
        STRATEGY_NUMERIC_LIMITS,
        TRADE_DEFAULTS,
        TRADE_NUMERIC_LIMITS,
        ApiKeyCreate,
        AssetSteeringSettingsUpdate,
        ClaudeAgentSettingsUpdate,
        TradeSettingsUpdate,
        asset_steering_settings,
        asset_steering_status,
        claude_agent_settings,
        get_asset_steering_settings,
        get_claude_agent_settings,
        get_trade_prices,
        get_trade_settings,
        list_settings,
        reporting_decisions,
        scaffold_api_key,
        setpoint_log_columns,
        trade_settings,
        update_asset_steering_settings,
        update_claude_agent_settings,
        update_trade_settings,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers import health as health_router
    from routers import settings as settings_router
    from routers.health import (
        SystemSettingsUpdate,
        get_system_settings,
        health,
        update_system_settings,
    )
    from routers.settings import (
        ALLOWED_TRADE_PRICE_HOST,
        CLAUDE_AGENT_DEFAULTS,
        STRATEGY3_DEFAULTS,
        STRATEGY_DEFAULTS,
        STRATEGY_NUMERIC_LIMITS,
        TRADE_DEFAULTS,
        TRADE_NUMERIC_LIMITS,
        ApiKeyCreate,
        AssetSteeringSettingsUpdate,
        ClaudeAgentSettingsUpdate,
        TradeSettingsUpdate,
        asset_steering_settings,
        asset_steering_status,
        claude_agent_settings,
        get_asset_steering_settings,
        get_claude_agent_settings,
        get_trade_prices,
        get_trade_settings,
        list_settings,
        reporting_decisions,
        scaffold_api_key,
        setpoint_log_columns,
        trade_settings,
        update_asset_steering_settings,
        update_claude_agent_settings,
        update_trade_settings,
    )
from shared.db import AsyncSessionLocal

app.include_router(settings_router.router)
app.include_router(health_router.router)

LOGGER = logging.getLogger(__name__)

# Re-exported from api.payload_helpers/api.state for backward compatibility: several tests
# import these names directly via `from api.main import ...` rather than from their new homes.
__all__ = [
    "ALLOWED_TRADE_PRICE_HOST",
    "BATTERY_DEFAULTS",
    "CLAUDE_AGENT_DEFAULTS",
    "GRID_STATUS_KEYS",
    "MINYAD_FORECAST_MODEL_VERSION",
    "MINYAD_FORECAST_SCENARIO_COUNT",
    "MQTT_STATUS_KEYS",
    "PLAN_STALE_MINUTES",
    "PRIVATE_MODULES_AVAILABLE",
    "SOLAR_STATUS_KEYS",
    "STRATEGY3_DEFAULTS",
    "STRATEGY_DEFAULTS",
    "STRATEGY_NUMERIC_LIMITS",
    "SURPLUS_API_VERSION",
    "TRADE_DEFAULTS",
    "TRADE_NUMERIC_LIMITS",
    "TRADE_PRICE_CACHE",
    "UTC_OFFSET_SUFFIX",
    "ApiKeyCreate",
    "AssetSteeringSettingsUpdate",
    "ClaudeAgentSettingsUpdate",
    "SystemSettingsUpdate",
    "TradeSettingsUpdate",
    "_add_months",
    "_battery_phase",
    "_bucket_expr",
    "_classify_cloud_cover",
    "_normalize_battery_override_mode",
    "_numeric_w",
    "_parse_log_datetime",
    "_serialize_log_row",
    "_slot_battery_w",
    "_status_text",
    "_strategy_module_unavailable_outcome",
    "_validate_battery_override_limits",
    "active_battery_setpoint_w",
    "app",
    "asset_steering_settings",
    "asset_steering_status",
    "battery_curve_power_w",
    "battery_health_component",
    "battery_status_payload",
    "build_health_status",
    "build_plan_curves",
    "build_surplus_payload",
    "cached_status_is_incomplete",
    "claude_agent_settings",
    "coerce_float_status_value",
    "coerce_grid_status",
    "coerce_int_status_value",
    "component_status",
    "compute_household_load",
    "dashboard_window_bounds",
    "derive_battery_state",
    "derived_bridge_stale_seconds",
    "enrich_bridge_health",
    "get_asset_steering_settings",
    "get_claude_agent_settings",
    "get_system_settings",
    "get_trade_prices",
    "get_trade_settings",
    "grid_health_component",
    "grid_status_payload",
    "health",
    "interpolate_points",
    "list_settings",
    "mqtt_status_key",
    "parse_bridge_last_seen",
    "parse_status_timestamp",
    "reporting_decisions",
    "scaffold_api_key",
    "serialize_agent_decision",
    "serialize_agent_message",
    "serialize_control_decision",
    "setpoint_log_columns",
    "setpoint_log_select_list",
    "solar_dynamic_status_key",
    "solar_health_component",
    "solar_status_payload",
    "trade_settings",
    "update_asset_steering_settings",
    "update_claude_agent_settings",
    "update_system_settings",
    "update_trade_settings",
    "value_is_fresh_iso",
]

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
# with the strategy package (mirrors _classify_cloud_cover further below).
BATTERY_LP_META_DEFAULTS = {
    "battery.capacity_wh": 10240.0,
    "strategy3.one_way_efficiency": 0.95,
    "battery.max_charge_w": 1440.0,
    "battery.max_charge_a": 30.0,
    "battery.nominal_v": 48.0,
    "battery.max_discharge_w": 5000.0,
}


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


_debug_refresh_task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def startup() -> None:
    global _debug_refresh_task
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(DEBUG_LOGGING_SETTING_QUERY))
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
    async with AsyncSessionLocal() as session:
        await publish_battery_mqtt_settings(await battery_settings(session))
        await publish_trade_mqtt_settings(await trade_settings(session))
    _debug_refresh_task = asyncio.create_task(_refresh_debug_setting())


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


@app.get("/battery/status")
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


@app.get("/grid/status")
async def grid_status(session: SessionDep) -> dict[str, Any]:
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
async def dsmr_status(session: SessionDep) -> dict[str, Any]:
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
async def household_status(session: SessionDep) -> dict[str, Any]:
    return await household_status_payload(session)


WINDOWS = {
    "5m": (timedelta(minutes=5), 60, "power_curve_points"),
    "hour": (timedelta(hours=1), 60, "power_curve_points"),
    "day": (timedelta(days=1), 60, "power_curve_points"),
    "week": (timedelta(weeks=1), 900, "power_curve_rollups"),
    "month": (timedelta(days=31), 3600, "power_curve_rollups"),
    "year": (timedelta(days=366), 3600, "power_curve_rollups"),
}


async def latest_slot_plan(session: AsyncSession, *, include_fallback: bool = True) -> dict[str, Any] | None:
    row = (await session.execute(text("""
        select generated_at, valid_from, slot_seconds, payload, solver_status
        from slot_plans
        where (:include_fallback or solver_status != 'FALLBACK')
        order by generated_at desc
        limit 1
    """), {"include_fallback": include_fallback})).mappings().first()
    return dict(row) if row else None


async def latest_pv_uncertainty_bands(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """P10-P90 multipliers (dashboard) plus, where the daily calibration run has produced one,
    the quantile_grid used by minyad.strategy.v3.scenario_forecast to draw PV scenarios for
    minyad_forecast. A class without a persisted grid yet is still returned (dashboard still
    wants its p10/p90), just without scenario-generation support until the next calibration."""
    latest_date = (await session.execute(text("select max(calibration_date) from pv_uncertainty_bands"))).scalar_one_or_none()
    if latest_date is None:
        return {}
    rows = (await session.execute(
        text(
            "select cloud_class, p10_multiplier, p90_multiplier, p25_multiplier, p50_multiplier, quantile_grid "
            "from pv_uncertainty_bands where calibration_date = :d"
        ),
        {"d": latest_date},
    )).all()
    bands: dict[str, dict[str, Any]] = {}
    for row in rows:
        band: dict[str, Any] = {"p10_multiplier": float(row.p10_multiplier), "p90_multiplier": float(row.p90_multiplier)}
        if row.p25_multiplier is not None:
            band["p25_multiplier"] = float(row.p25_multiplier)
        if row.p50_multiplier is not None:
            band["p50_multiplier"] = float(row.p50_multiplier)
        if row.quantile_grid:
            band["quantile_grid"] = row.quantile_grid
        bands[row.cloud_class] = band
    return bands


async def _dashboard_forecast_curves(
    session: SessionDep, now_: datetime, end: datetime, step_seconds: int
) -> tuple[str, str | None, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    empty_curves: dict[str, list[dict[str, Any]]] = {
        "forecast": [],
        "load_forecast": [],
        "battery_forecast": [],
        "grid_forecast": [],
        "curtailment_forecast": [],
        "pv_p10_forecast": [],
        "pv_p90_forecast": [],
    }
    plan_row, latest_plan_status = await _current_forecast_plan(session)
    if plan_row is None:
        plan_status = "fallback" if latest_plan_status == "FALLBACK" else "missing"
        return plan_status, None, empty_curves, []

    generated_at = plan_row["generated_at"]
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    plan_generated_at = generated_at.isoformat()
    is_fresh = generated_at > datetime.now(UTC) - timedelta(minutes=PLAN_STALE_MINUTES)
    # A FALLBACK plan (solver couldn't produce a real solution, e.g. Open-Meteo was
    # unreachable) is a flat pv_forecast_w=0/load_forecast_w=0 hold — persisted with a fresh
    # generated_at like any other plan, so freshness alone can't tell it apart from a real
    # forecast. Treat it the same as "no plan": never show a fabricated flat-zero line.
    is_real_plan = plan_row.get("solver_status") != "FALLBACK"
    if not is_fresh:
        return "stale", plan_generated_at, empty_curves, []
    if not is_real_plan:
        return "fallback", plan_generated_at, empty_curves, []

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
    return "ok", plan_generated_at, curves, price_source_points


@app.get("/dashboard/curves")
async def dashboard_curves(
    session: SessionDep,
    window: Literal["5m", "hour", "day", "week", "month", "year"] = "day",
    offset: Annotated[int | None, Query(ge=-120, le=0)] = None,
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
            "timestamp": row["ts"].replace(tzinfo=UTC).isoformat(),
            "power_w": round(float(row["power_w"] or 0)),
            "delivered_w": round(float(row["delivered_w"])) if row["delivered_w"] is not None else None,
            "returned_w": round(float(row["returned_w"])) if row["returned_w"] is not None else None,
            "net_w": round(float(row["net_w"])) if row["net_w"] is not None else round(float(row["power_w"] or 0)),
        })

    plan_status, plan_generated_at, curves, price_source_points = await _dashboard_forecast_curves(session, now_, end, step_seconds)

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
async def dashboard_forecast_quality(session: SessionDep) -> dict[str, Any]:
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
async def api_state(session: SessionDep) -> dict[str, Any]:
    battery = await battery_status(session)
    grid = await grid_status(session)
    household = await household_status_payload(session, store=False)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "battery": battery,
        "grid": grid,
        "household": household,
    }


@app.get("/api/v1/surplus")
async def api_v1_surplus(session: SessionDep) -> dict[str, Any]:
    battery = await battery_status(session)
    grid = await grid_status(session)
    settings = await battery_settings(session)
    battery_meta = await battery_lp_meta(session)
    plan_row, latest_plan_status = await _current_forecast_plan(session)
    uncertainty_bands = await latest_pv_uncertainty_bands(session)
    return build_surplus_payload(
        grid,
        battery,
        settings,
        battery_meta=battery_meta,
        attempt_forecast=True,
        plan_payload=plan_row["payload"] if plan_row is not None else None,
        plan_generated_at=plan_row["generated_at"] if plan_row is not None else None,
        plan_solver_status=(plan_row.get("solver_status") if plan_row is not None else latest_plan_status),
        uncertainty_bands=uncertainty_bands,
    )


@app.get("/api/v1/dryad")
async def api_v1_dryad(session: SessionDep) -> dict[str, Any]:
    now_ = datetime.now(UTC)
    with DRYAD_CACHE_LOCK:
        cached_at = DRYAD_CACHE.get("computed_at")
        cached_payload = DRYAD_CACHE.get("payload")
        if (
            isinstance(cached_at, datetime)
            and cached_payload is not None
            and (now_ - cached_at).total_seconds() < DRYAD_CACHE_SECONDS
        ):
            return cached_payload

    inputs = await load_dryad_inputs(session, now_)
    payload = build_dryad_payload(
        now=now_,
        mqtt_status=latest_mqtt_status(),
        inputs=inputs,
        prices=latest_trade_prices(),
    )
    with DRYAD_CACHE_LOCK:
        DRYAD_CACHE["computed_at"] = now_
        DRYAD_CACHE["payload"] = payload
    return payload


@app.get("/api/v1/dryad/history")
async def api_v1_dryad_history(
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=400)] = 30,
) -> dict[str, Any]:
    timezone_name = os.getenv("MINYAD_TIMEZONE", "Europe/Amsterdam")
    return {
        "days": days,
        "timezone": timezone_name,
        "series": await load_dryad_history(session, days=days, timezone_name=timezone_name),
    }


@app.get("/api/surplus")
async def api_surplus(session: SessionDep) -> dict[str, Any]:
    return await api_v1_surplus(session)


@app.get("/api/forecast")
async def api_forecast(session: SessionDep, hours_ahead: int = 12) -> dict[str, Any]:
    hours = max(1, min(48, hours_ahead))
    now_ = datetime.now(UTC)
    end = now_ + timedelta(hours=hours)
    plan_row, latest_plan_status = await _current_forecast_plan(session)
    stale_status = _forecast_stale_status(plan_row, latest_plan_status, now_)
    if stale_status is not None:
        return {"hours_ahead": hours, "plan_status": stale_status, "points": []}
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


async def _current_forecast_plan(session: SessionDep) -> tuple[dict[str, Any] | None, str | None]:
    plan_row = await latest_slot_plan(session)
    latest_plan_status = plan_row.get("solver_status") if plan_row is not None else None
    if plan_row is not None and latest_plan_status == "FALLBACK":
        plan_row = await latest_slot_plan(session, include_fallback=False)
    return plan_row, latest_plan_status


def _forecast_stale_status(plan_row: dict[str, Any] | None, latest_plan_status: str | None, now_: datetime) -> str | None:
    plan_generated_at = plan_row["generated_at"] if plan_row is not None else None
    if plan_generated_at is not None and plan_generated_at.tzinfo is None:
        plan_generated_at = plan_generated_at.replace(tzinfo=UTC)
    if plan_generated_at is None or plan_generated_at <= now_ - timedelta(minutes=PLAN_STALE_MINUTES):
        if plan_row is None and latest_plan_status == "FALLBACK":
            return "fallback"
        return "missing" if plan_row is None else "stale"
    return None


@app.post("/api/control/battery", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
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


@app.post("/api/agent/decisions", status_code=201, dependencies=MUTATION_AUTH)
async def create_agent_decision(request: AgentDecisionRequest, session: SessionDep) -> dict[str, Any]:
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
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=UTC).isoformat()}


@app.get("/api/agent/decisions")
async def list_agent_decisions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    rows = (await session.execute(text("""
        select id, created_at, action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model
        from agent_decisions
        order by created_at desc
        limit :limit
    """), {"limit": limit})).mappings().all()
    return [serialize_agent_decision(row) for row in rows]


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    return bool((await session.execute(text("select to_regclass(:table_name) is not null"), {"table_name": table_name})).scalar_one())


async def _table_columns(session: AsyncSession, table_name: str) -> set[str]:
    rows = (await session.execute(
        text("""
            select column_name
            from information_schema.columns
            where table_name = :table_name
        """),
        {"table_name": table_name},
    )).scalars().all()
    return set(rows)


async def _fetch_log_rows(session: AsyncSession, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (await session.execute(text(query), params)).mappings().all()
    return [_serialize_log_row(row) for row in rows]


async def _collect_log(
    session: AsyncSession,
    logs: dict[str, Any],
    unavailable: list[str],
    table: str,
    query: str,
    params: dict[str, Any],
) -> None:
    if await _table_exists(session, table):
        logs[table] = await _fetch_log_rows(session, query, params)
    else:
        unavailable.append(table)


@app.get("/api/agent/logs", dependencies=[Depends(require_api_key)], responses={400: {"description": "Bad request"}})
async def agent_operational_logs(
    session: SessionDep,
    hours_lookback: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    since: Annotated[str | None, Query()] = None,
    until: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    until_dt = _parse_log_datetime(until) or datetime.now(UTC)
    since_dt = _parse_log_datetime(since) or (until_dt - timedelta(hours=hours_lookback))
    if since_dt > until_dt:
        raise HTTPException(status_code=400, detail="since must be before until")
    params = {"since": since_dt, "until": until_dt, "limit": limit}
    logs: dict[str, Any] = {}
    unavailable: list[str] = []

    await _collect_log(session, logs, unavailable, "agent_decisions", """
        select id, created_at, action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model
        from agent_decisions
        where created_at >= :since and created_at <= :until
        order by created_at desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "setpoint_log"):
        columns = await setpoint_log_columns(session)
        select_list = setpoint_log_select_list(columns)
        rows = (await session.execute(text(f"""
            select {select_list}
            from setpoint_log
            where timestamp >= :since and timestamp <= :until
            order by timestamp desc, id desc
            limit :limit
        """), params)).mappings().all()
        logs["setpoint_log"] = [serialize_control_decision(row) for row in rows]
    else:
        unavailable.append("setpoint_log")

    await _collect_log(session, logs, unavailable, "strategy_decisions", """
        select id, timestamp, mode, soc_floor, soc_ceiling, forecast_ghi, trigger_reason, applied_at
        from strategy_decisions
        where timestamp >= :since and timestamp <= :until
        order by timestamp desc, id desc
        limit :limit
    """, params)

    await _collect_log(session, logs, unavailable, "day_plans", """
        select id, plan_date, solar_mode, forecast_ghi_kwh_m2, effective_soc_floor,
               effective_soc_ceiling, grid_charge_windows, price_discharge_windows,
               planned_soc_at_sunset, valid_until, reason, created_at
        from day_plans
        where created_at <= :until and valid_until >= :since
        order by created_at desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "slot_plans"):
        columns = await _table_columns(session, "slot_plans")
        strategy_version_select = "strategy_version" if "strategy_version" in columns else "null as strategy_version"
        logs["slot_plans"] = await _fetch_log_rows(session, f"""
            select id, generated_at, valid_from, slot_seconds, solver_status, {strategy_version_select}, payload, created_at
            from slot_plans
            where generated_at >= :since and generated_at <= :until
            order by generated_at desc, id desc
            limit :limit
        """, params)
    else:
        unavailable.append("slot_plans")

    await _collect_log(session, logs, unavailable, "strategy_shadow_log", """
        select id, ts, v2_setpoint_w, v3_setpoint_w, soc, net_grid_w, v3_reason, created_at
        from strategy_shadow_log
        where ts >= :since and ts <= :until
        order by ts desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "agent_messages"):
        columns = await _table_columns(session, "agent_messages")
        optional_columns = [
            name for name in ("archived_at", "operator_ack_at", "agent_ack_at")
            if name in columns
        ]
        select_columns = [
            "id", "created_at", "sender", "category", "subject", "body",
            "related_decision_id", "read_at", "thread_id", "severity", *optional_columns,
        ]
        logs["agent_messages"] = await _fetch_log_rows(session, f"""
            select {", ".join(select_columns)}
            from agent_messages
            where created_at >= :since and created_at <= :until
            order by created_at desc, id desc
            limit :limit
        """, params)
    else:
        unavailable.append("agent_messages")

    await _collect_log(session, logs, unavailable, "telemetry_log", """
        select id, timestamp, topic, payload
        from telemetry_log
        where timestamp >= :since and timestamp <= :until
        order by timestamp desc, id desc
        limit :limit
    """, params)

    await _collect_log(session, logs, unavailable, "battery_override", """
        select *
        from battery_override
        order by id
        limit :limit
    """, params)

    settings_rows = (await session.execute(text("""
        select key, value, updated_at
        from settings
        where key like 'battery.%' or key like 'strategy.%' or key like 'strategy3.%'
        order by key
    """))).mappings().all()
    logs["settings"] = [_serialize_log_row(row) for row in settings_rows]

    return {
        "window": {
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "hours_lookback": hours_lookback,
            "limit_per_log": limit,
        },
        "logs": logs,
        "unavailable": unavailable,
    }


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


@app.get("/api/messages")
async def list_agent_messages(
    session: SessionDep,
    unread: bool | None = None,
    category: Literal["anomaly", "suggestion", "info", "reply"] | None = None,
    sender: Literal["agent", "operator"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    archived: bool | None = False,
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
    session: SessionDep,
    sender: Literal["agent", "operator"] | None = "agent",
) -> dict[str, int]:
    clause = "read_at is null and archived_at is null"
    params: dict[str, Any] = {}
    if sender is not None:
        clause += " and sender = :sender"
        params["sender"] = sender
    count = (await session.execute(text(f"select count(*) from agent_messages where {clause}"), params)).scalar_one()
    return {"unread_count": int(count)}


@app.get("/api/messages/{message_id}", responses={404: {"description": "Not found"}})
async def get_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :id
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    root_id = row["thread_id"] or row["id"]
    thread_rows = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :root_id or thread_id = :root_id
        order by created_at asc
    """), {"root_id": root_id})).mappings().all()
    return {"message": serialize_agent_message(row), "thread": [serialize_agent_message(thread_row) for thread_row in thread_rows]}


@app.post("/api/messages", status_code=201, dependencies=MUTATION_AUTH)
async def create_agent_message(request: AgentMessageCreate, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_messages (sender, category, subject, body, related_decision_id, thread_id, severity, operator_ack_at, agent_ack_at)
        values (:sender, :category, :subject, :body, :related_decision_id, :thread_id, :severity, case when :sender = 'operator' then now() else null end, case when :sender = 'agent' then now() else null end)
        returning id, created_at
    """), request.model_dump())).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=UTC).isoformat()}


@app.patch("/api/messages/{message_id}/read", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def mark_agent_message_read(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set read_at = coalesce(read_at, now()),
            agent_ack_at = case when sender = 'operator' then coalesce(agent_ack_at, now()) else agent_ack_at end
        where id = :id
        returning id, read_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"], "read_at": row["read_at"].replace(tzinfo=UTC).isoformat()}


@app.patch("/api/messages/{message_id}/archive", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def archive_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set archived_at = coalesce(archived_at, now())
        where id = :id
        returning id, archived_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"], "archived_at": row["archived_at"].replace(tzinfo=UTC).isoformat()}


@app.patch("/api/messages/{message_id}/ack", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def acknowledge_agent_message(message_id: int, session: SessionDep, actor: Literal["operator", "agent"] = "operator") -> dict[str, Any]:
    column = "operator_ack_at" if actor == "operator" else "agent_ack_at"
    row = (await session.execute(text(f"""
        update agent_messages
        set {column} = coalesce({column}, now())
        where id = :id
        returning id, operator_ack_at, agent_ack_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", **serialize_agent_message(row)}


@app.delete("/api/messages/{message_id}", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def delete_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("delete from agent_messages where id = :id returning id"), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"]}


@app.post("/battery/override", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
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


@app.delete("/battery/override", dependencies=MUTATION_AUTH)
async def clear_battery_override(session: SessionDep) -> dict[str, str]:
    await session.execute(text("update battery_override set mode='none', watts=null, duration_seconds=null, expires_at=null, override_soc_limits=false, updated_at=now() where id=1"))
    await session.commit()
    mqtt.client.publish(TOPIC_CONTROL_OVERRIDE, json.dumps({"mode": "none"}), qos=0, retain=False)
    return {"status": "ok", "mode": "none"}


@app.get("/api/battery/settings")
@app.get("/battery/settings")
async def get_battery_settings(session: SessionDep) -> dict[str, Any]:
    return await battery_settings(session)


@app.put("/api/battery/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
@app.put("/battery/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
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
