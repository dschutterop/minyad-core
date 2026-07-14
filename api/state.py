"""Shared FastAPI app instance, MQTT client, locks/caches, and auth dependency.

No dependency on api.main or api.routers.* — every router module imports shared
state from here, so main.py can import the routers without a circular import.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from prometheus_client import CollectorRegistry, Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from api.payload_helpers import (
        GRID_STATUS_KEYS,
        MQTT_STATUS_KEYS,
        SOLAR_STATUS_KEYS,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import GRID_STATUS_KEYS, MQTT_STATUS_KEYS, SOLAR_STATUS_KEYS
from shared.db import AsyncSessionLocal, get_session
from shared.mqtt_client import MinyadMqttClient

SessionDep = Annotated[AsyncSession, Depends(get_session)]

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
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))
PROMETHEUS_REGISTRY = CollectorRegistry()
API_BUILD_INFO = Gauge(
    "minyad_api_build_info",
    "Build and version information for minyad-api.",
    ["version"],
    registry=PROMETHEUS_REGISTRY,
)
API_ERRORS_TOTAL = Counter(
    "minyad_api_errors_total",
    "Errors observed by minyad-api.",
    ["type"],
    registry=PROMETHEUS_REGISTRY,
)
API_BUILD_INFO.labels(version=VERSION).set(1)
Instrumentator(registry=PROMETHEUS_REGISTRY).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
mqtt = MinyadMqttClient("minyad-api")
LOGGER = logging.getLogger(__name__)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(API_KEY_HEADER)) -> None:
    expected = os.getenv("MINYAD_API_SECRET", "")
    if not expected or not key or not secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


MUTATION_AUTH = [Depends(require_api_key)]
DEBUG_LOGGING_SETTING_QUERY = "select value from settings where key = 'system.debug_logging'"
SETTING_UPSERT_QUERY = """
                insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                on conflict (key) do update set value=:value, encrypted=false, updated_at=now()
            """
MESSAGE_NOT_FOUND_DETAIL = "message not found"
TOPIC_CONTROL_OVERRIDE = "minyad/control/override"

STARTUP_AT = datetime.now(UTC)
MQTT_EVENTS: deque[dict[str, str]] = deque(maxlen=100)
LAST_RETAINED_FETCH: dict[str, Any] = {}
TRADE_PRICE_CACHE_LOCK = Lock()
TRADE_PRICE_CACHE: dict[str, list[dict[str, Any]]] = {}
DRYAD_CACHE_LOCK = Lock()
DRYAD_CACHE: dict[str, Any] = {"computed_at": None, "payload": None}
_debug_enabled = False


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
                result = await session.execute(text(DEBUG_LOGGING_SETTING_QUERY))
                val = result.scalar_one_or_none() or "false"
                new_debug = val == "true"
                if new_debug != _debug_enabled:
                    _apply_log_level(new_debug)
        except Exception:
            LOGGER.debug("Could not refresh debug setting from DB")
