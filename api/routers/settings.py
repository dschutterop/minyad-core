"""Claude-agent, asset-steering, trade, and generic settings routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from api.payload_helpers import serialize_control_decision, setpoint_log_select_list
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import serialize_control_decision, setpoint_log_select_list
try:
    from api.mqtt_handlers import latest_trade_prices, publish_trade_mqtt_settings
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import latest_trade_prices, publish_trade_mqtt_settings
try:
    from api.state import MUTATION_AUTH, SETTING_UPSERT_QUERY, SessionDep
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import MUTATION_AUTH, SETTING_UPSERT_QUERY, SessionDep

router = APIRouter()

CLAUDE_AGENT_DEFAULTS = {
    "enabled": "false",
    "token_guard_enabled": "true",
    "min_tokens_remaining": "5000",
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
STRATEGY_NUMERIC_LIMITS = {
    "ghi_solar_rich_threshold": (0.0, 20.0),
    "ghi_solar_poor_threshold": (0.0, 20.0),
    "dynamic_tariff_ceiling_eur_kwh": (-1.0, 5.0),
    "ramp_floor_w": (0, 5000),
    "ramp_ceiling_w": (1, 5000),
    "ramp_hold_seconds": (0, 3600),
}

TRADE_DEFAULTS = {
    "bidding_zone": "10YNL----------L",
    "poll_time_local": "13:30",
    "retry_attempts": "3",
    "retry_interval_minutes": "15",
    "entsoe_api_url": "https://web-api.tp.entsoe.eu/api",
}
ALLOWED_TRADE_PRICE_HOST = "web-api.tp.entsoe.eu"
TRADE_NUMERIC_LIMITS = {
    "retry_attempts": (1, 24),
    "retry_interval_minutes": (1, 240),
}


class ApiKeyCreate(BaseModel):
    name: str


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
        if parsed.hostname != ALLOWED_TRADE_PRICE_HOST or parsed.username or parsed.password or parsed.port is not None:
            raise ValueError(f"entsoe_api_url must point to {ALLOWED_TRADE_PRICE_HOST}")
        return url


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


@router.get("/api/claude-agent/settings")
@router.get("/claude-agent/settings")
async def get_claude_agent_settings(session: SessionDep) -> dict[str, Any]:
    return await claude_agent_settings(session)


@router.patch("/api/claude-agent/settings", dependencies=MUTATION_AUTH)
@router.patch("/claude-agent/settings", dependencies=MUTATION_AUTH)
@router.put("/api/claude-agent/settings", dependencies=MUTATION_AUTH)
@router.put("/claude-agent/settings", dependencies=MUTATION_AUTH)
async def update_claude_agent_settings(
    update: ClaudeAgentSettingsUpdate,
    session: SessionDep,
) -> dict[str, Any]:
    data = update.model_dump(exclude_unset=True)
    for key, value in data.items():
        if isinstance(value, bool):
            stored = "true" if value else "false"
        else:
            stored = str(value)
        await session.execute(
            text(SETTING_UPSERT_QUERY),
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


@router.get("/asset-steering/settings")
async def get_asset_steering_settings(session: SessionDep) -> dict[str, Any]:
    return await asset_steering_settings(session)


@router.put("/asset-steering/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
async def update_asset_steering_settings(
    update: AssetSteeringSettingsUpdate,
    session: SessionDep,
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
            text(SETTING_UPSERT_QUERY),
            {"key": f"strategy.{key}", "value": str(value)},
        )
    await session.commit()
    return await asset_steering_settings(session)


@router.get("/asset-steering/status")
async def asset_steering_status(session: SessionDep) -> dict[str, Any]:
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


async def setpoint_log_columns(session: AsyncSession) -> set[str]:
    rows = (await session.execute(
        text("""
            select column_name
            from information_schema.columns
            where table_name = 'setpoint_log'
        """)
    )).scalars().all()
    return set(rows)


@router.get("/reporting/decisions")
async def reporting_decisions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
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


@router.get("/trade/prices")
async def get_trade_prices() -> dict[str, Any]:
    prices = latest_trade_prices()
    return {
        "source": "day-ahead",
        "unit": "EUR/kWh",
        "date": prices[0]["date"] if prices else None,
        "prices": prices,
    }


@router.get("/trade/settings")
async def get_trade_settings(session: SessionDep) -> dict[str, Any]:
    return await trade_settings(session)


@router.put("/trade/settings", dependencies=MUTATION_AUTH, responses={422: {"description": "Unprocessable entity"}})
async def update_trade_settings(update: TradeSettingsUpdate, session: SessionDep) -> dict[str, Any]:
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
            text(SETTING_UPSERT_QUERY),
            {"key": f"trade.{key}", "value": str(value)},
        )
    await session.commit()
    settings = await trade_settings(session)
    await publish_trade_mqtt_settings(settings)
    return settings


@router.get("/settings")
async def list_settings(session: SessionDep) -> list[dict[str, object]]:
    result = await session.execute(text("select key, encrypted, updated_at from settings order by key"))
    return [{"key": row.key, "encrypted": row.encrypted, "updated_at": row.updated_at} for row in result]


@router.post("/api-keys", status_code=202, dependencies=MUTATION_AUTH)
async def scaffold_api_key(request: ApiKeyCreate, session: SessionDep) -> dict[str, str]:
    await session.execute(text("select id from api_keys where name = :name"), {"name": request.name})
    return {"status": "scaffolded", "message": "API key generation is intentionally not implemented yet"}
