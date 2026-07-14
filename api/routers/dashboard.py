"""Dashboard/forecast/surplus/dryad routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
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
        PLAN_STALE_MINUTES,
        _bucket_expr,
        build_plan_curves,
        build_surplus_payload,
        coerce_float_status_value,
        dashboard_window_bounds,
        interpolate_points,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        PLAN_STALE_MINUTES,
        _bucket_expr,
        build_plan_curves,
        build_surplus_payload,
        coerce_float_status_value,
        dashboard_window_bounds,
        interpolate_points,
    )
try:
    from api.mqtt_handlers import latest_mqtt_status, latest_trade_prices
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from mqtt_handlers import latest_mqtt_status, latest_trade_prices
try:
    from api.state import DRYAD_CACHE, DRYAD_CACHE_LOCK, SessionDep
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import DRYAD_CACHE, DRYAD_CACHE_LOCK, SessionDep
try:
    from api.routers.battery import (
        battery_lp_meta,
        battery_settings,
        battery_status,
        household_status_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.battery import (
        battery_lp_meta,
        battery_settings,
        battery_status,
        household_status_payload,
    )
try:
    from api.routers.grid import grid_status
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.grid import grid_status

router = APIRouter()

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


@router.get("/dashboard/curves")
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


@router.get("/dashboard/forecast-quality")
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


@router.get("/api/state")
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


@router.get("/api/v1/surplus")
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


@router.get("/api/v1/dryad")
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


@router.get("/api/v1/dryad/history")
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


@router.get("/api/surplus")
async def api_surplus(session: SessionDep) -> dict[str, Any]:
    return await api_v1_surplus(session)


@router.get("/api/forecast")
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
