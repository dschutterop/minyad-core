"""Health/debug/system-settings routes."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

try:
    from api.payload_helpers import (
        PRIVATE_MODULES_AVAILABLE,
        cached_status_is_incomplete,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import PRIVATE_MODULES_AVAILABLE, cached_status_is_incomplete
try:
    from api.mqtt_handlers import build_health_status
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import build_health_status
try:
    from api.state import (
        DEBUG_LOGGING_SETTING_QUERY,
        LAST_RETAINED_FETCH,
        MQTT_EVENTS,
        MQTT_STATUS,
        MQTT_STATUS_LOCK,
        MUTATION_AUTH,
        STARTUP_AT,
        SessionDep,
        _apply_log_level,
        mqtt,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        DEBUG_LOGGING_SETTING_QUERY,
        LAST_RETAINED_FETCH,
        MQTT_EVENTS,
        MQTT_STATUS,
        MQTT_STATUS_LOCK,
        MUTATION_AUTH,
        STARTUP_AT,
        SessionDep,
        _apply_log_level,
        mqtt,
    )
try:
    from api.routers.settings import claude_agent_settings
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.settings import claude_agent_settings

router = APIRouter()


class SystemSettingsUpdate(BaseModel):
    debug_logging: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None
    language: Literal["en", "nl"] | None = None


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "private_modules": PRIVATE_MODULES_AVAILABLE}


@router.get("/health/status")
async def health_status(session: SessionDep) -> dict[str, Any]:
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


@router.get("/debug/status")
async def debug_status(session: SessionDep) -> dict[str, Any]:
    result = await session.execute(text(DEBUG_LOGGING_SETTING_QUERY))
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


@router.get("/system-settings")
async def get_system_settings(session: SessionDep) -> dict[str, Any]:
    result = await session.execute(text("select key, value from settings where key in ('system.debug_logging', 'system.theme', 'system.language')"))
    settings = {row.key: row.value for row in result}
    return {
        "debug_logging": settings.get("system.debug_logging", "false") == "true",
        "theme": settings.get("system.theme", "system"),
        "language": settings.get("system.language", "en"),
    }


@router.put("/system-settings", dependencies=MUTATION_AUTH)
async def update_system_settings(update: SystemSettingsUpdate, session: SessionDep) -> dict[str, Any]:
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
