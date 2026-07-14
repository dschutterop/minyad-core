"""Grid/DSMR/solar/household status routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

try:
    from api.payload_helpers import (
        coerce_grid_status,
        grid_status_payload,
        parse_status_timestamp,
        solar_status_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        coerce_grid_status,
        grid_status_payload,
        parse_status_timestamp,
        solar_status_payload,
    )
try:
    from api.mqtt_handlers import collect_retained_mqtt_status, latest_mqtt_status
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import collect_retained_mqtt_status, latest_mqtt_status
try:
    from api.state import SessionDep
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import SessionDep
try:
    from api.routers.battery import household_status_payload, store_power_curve_point
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.battery import household_status_payload, store_power_curve_point

router = APIRouter()
LOGGER = logging.getLogger(__name__)


@router.get("/grid/status")
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


@router.get("/dsmr/status")
async def dsmr_status(session: SessionDep) -> dict[str, Any]:
    return await grid_status(session)


@router.get("/solar/status")
async def solar_status() -> dict[str, Any]:
    payload = latest_mqtt_status()
    if not any(key.startswith("solar_") for key in payload):
        try:
            payload.update(collect_retained_mqtt_status())
        except OSError:
            LOGGER.exception("Unable to fetch retained MQTT solar snapshot")
    return solar_status_payload(payload)


@router.get("/household/status")
async def household_status(session: SessionDep) -> dict[str, Any]:
    return await household_status_payload(session)
