"""Minyad REST API."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

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
        handle_status_mqtt,
        handle_trade_price_mqtt,
        latest_trade_prices,
        publish_battery_mqtt_settings,
        publish_trade_mqtt_settings,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import (
        build_health_status,
        handle_status_mqtt,
        handle_trade_price_mqtt,
        latest_trade_prices,
        publish_battery_mqtt_settings,
        publish_trade_mqtt_settings,
    )
try:
    from api.state import (
        DEBUG_LOGGING_SETTING_QUERY,
        TRADE_PRICE_CACHE,
        _apply_log_level,
        _refresh_debug_setting,
        app,
        mqtt,
        require_api_key,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        DEBUG_LOGGING_SETTING_QUERY,
        TRADE_PRICE_CACHE,
        _apply_log_level,
        _refresh_debug_setting,
        app,
        mqtt,
        require_api_key,
    )
try:
    from api.routers import agent as agent_router
    from api.routers import battery as battery_router
    from api.routers import dashboard as dashboard_router
    from api.routers import grid as grid_router
    from api.routers import health as health_router
    from api.routers import settings as settings_router
    from api.routers.battery import (
        BATTERY_KEYS,
        AgentBatteryControlRequest,
        BatteryOverrideRequest,
        BatterySettingsUpdate,
        api_control_battery,
        battery_settings,
        battery_status,
        current_battery_override,
    )
    from api.routers.dashboard import api_forecast, api_v1_surplus
    from api.routers.grid import grid_status
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
    from routers import agent as agent_router
    from routers import battery as battery_router
    from routers import dashboard as dashboard_router
    from routers import grid as grid_router
    from routers import health as health_router
    from routers import settings as settings_router
    from routers.battery import (
        BATTERY_KEYS,
        AgentBatteryControlRequest,
        BatteryOverrideRequest,
        BatterySettingsUpdate,
        api_control_battery,
        battery_settings,
        battery_status,
        current_battery_override,
    )
    from routers.dashboard import api_forecast, api_v1_surplus
    from routers.grid import grid_status
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
app.include_router(battery_router.router)
app.include_router(grid_router.router)
app.include_router(dashboard_router.router)
app.include_router(agent_router.router)

LOGGER = logging.getLogger(__name__)

# Re-exported from api.payload_helpers/api.state for backward compatibility: several tests
# import these names directly via `from api.main import ...` rather than from their new homes.
__all__ = [
    "ALLOWED_TRADE_PRICE_HOST",
    "BATTERY_DEFAULTS",
    "BATTERY_KEYS",
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
    "AgentBatteryControlRequest",
    "ApiKeyCreate",
    "AssetSteeringSettingsUpdate",
    "BatteryOverrideRequest",
    "BatterySettingsUpdate",
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
    "api_control_battery",
    "api_forecast",
    "api_v1_surplus",
    "app",
    "asset_steering_settings",
    "asset_steering_status",
    "battery_curve_power_w",
    "battery_health_component",
    "battery_status",
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
    "current_battery_override",
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
    "grid_status",
    "grid_status_payload",
    "health",
    "interpolate_points",
    "latest_trade_prices",
    "list_settings",
    "mqtt_status_key",
    "parse_bridge_last_seen",
    "parse_status_timestamp",
    "reporting_decisions",
    "require_api_key",
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
