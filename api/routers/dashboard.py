"""Dashboard/forecast/surplus/dryad routes."""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import RowMapping, text
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
        TELEMETRY_EXPECTED_INTERVAL_SECONDS,
        _bucket_expr,
        battery_direction_label,
        battery_soc_alert,
        build_energy_center_alerts,
        build_plan_curves,
        build_surplus_payload,
        canonical_self_sufficiency_pct,
        coerce_float_status_value,
        connection_state,
        dashboard_window_bounds,
        freshness_state,
        grid_direction_label,
        integrate_day_kwh_checked,
        interpolate_points,
        reading_age_seconds,
        sun_times,
        supply_mix,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        PLAN_STALE_MINUTES,
        TELEMETRY_EXPECTED_INTERVAL_SECONDS,
        _bucket_expr,
        battery_direction_label,
        battery_soc_alert,
        build_energy_center_alerts,
        build_plan_curves,
        build_surplus_payload,
        canonical_self_sufficiency_pct,
        coerce_float_status_value,
        connection_state,
        dashboard_window_bounds,
        freshness_state,
        grid_direction_label,
        integrate_day_kwh_checked,
        interpolate_points,
        reading_age_seconds,
        sun_times,
        supply_mix,
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
try:
    from api.routers.health import health_status
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.health import health_status
try:
    from api.routers.settings import asset_steering_status
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.settings import asset_steering_status

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


async def _curve_rows(
    session: SessionDep, table_name: str, step_seconds: int, start: datetime, until: datetime
) -> Sequence[RowMapping]:
    if table_name == "power_curve_points":
        bucket = _bucket_expr("bucket_start", step_seconds)
        source_filter = "bucket_start >= :start and bucket_start <= :now_"
    else:
        bucket = "bucket_start"
        source_filter = "granularity_seconds = :step_seconds and bucket_start >= :start and bucket_start <= :now_"
    return (await session.execute(text(f"""
        select {bucket} as ts, source, avg(power_w) as power_w,
               avg(delivered_w) as delivered_w, avg(returned_w) as returned_w, avg(net_w) as net_w
        from {table_name}
        where {source_filter}
        group by ts, source order by ts
    """), {"start": start, "now_": until, "step_seconds": step_seconds})).mappings().all()


async def _window_series(
    session: SessionDep,
    table_name: str,
    step_seconds: int,
    start: datetime,
    until: datetime,
    *,
    window: str,
    offset: int | None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    rows = await _curve_rows(session, table_name, step_seconds, start, until)
    if not rows and window == "day" and offset is not None and offset < 0:
        # Raw 1-minute points are not kept for old days; fall back to the 15-minute rollups.
        rows = await _curve_rows(session, "power_curve_rollups", 900, start, until)
        if rows:
            step_seconds = 900
    series: dict[str, list[dict[str, Any]]] = {"solar": [], "battery": [], "grid": [], "household": []}
    for row in rows:
        series[row["source"]].append({
            "timestamp": row["ts"].replace(tzinfo=UTC).isoformat(),
            "power_w": round(float(row["power_w"] or 0)),
            "delivered_w": round(float(row["delivered_w"])) if row["delivered_w"] is not None else None,
            "returned_w": round(float(row["returned_w"])) if row["returned_w"] is not None else None,
            "net_w": round(float(row["net_w"])) if row["net_w"] is not None else round(float(row["power_w"] or 0)),
        })
    return series, step_seconds


@router.get("/dashboard/curves")
async def dashboard_curves(
    session: SessionDep,
    window: Literal["5m", "hour", "day", "week", "month", "year"] = "day",
    offset: Annotated[int | None, Query(ge=-120, le=0)] = None,
) -> dict[str, Any]:
    duration, step_seconds, table_name = WINDOWS[window]
    start, end, now_ = dashboard_window_bounds(window, duration, period_offset=offset)
    series, step_seconds = await _window_series(session, table_name, step_seconds, start, now_, window=window, offset=offset)

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


def _reading(value: float | None, unit: str, *, observed_at: str | None, source: str, quality: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "observedAt": observed_at, "source": source, "quality": quality}


# Same location the forecast service uses (FORECAST_LATITUDE/LONGITUDE, same defaults), so
# sunrise and sunset describe the place the solar forecast is made for.
SITE_LATITUDE = float(os.getenv("FORECAST_LATITUDE", "51.9788"))
SITE_LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", "4.3158"))
SITE_TIMEZONE = ZoneInfo(os.getenv("MINYAD_TIMEZONE", "Europe/Amsterdam"))
CO2_KG_PER_KWH = 0.39  # same factor the classic dashboard uses for "CO2 saved"


def _goal(env_name: str, default: float) -> float:
    try:
        return float(os.getenv(env_name, default))
    except ValueError:
        return default


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _day_total(points: list[dict[str, Any]], value_w: Any) -> tuple[float | None, dict[str, Any]]:
    """A day total as (kwh, reading). No integrable data is "missing", never 0 kWh;
    skipped gaps make the total "estimated" with a note, never silently "good"."""
    kwh, skipped_hours = integrate_day_kwh_checked(points, value_w)
    source = "/api/dashboard/curves"
    if kwh is None:
        return None, _reading(None, "kWh", observed_at=None, source=source, quality="missing")
    reading = _reading(
        round(kwh, 2), "kWh", observed_at=points[-1].get("timestamp") if points else None, source=source,
        quality="estimated" if skipped_hours > 0 else "good",
    )
    if skipped_hours > 0:
        reading["note"] = f"Onvolledig: {round(skipped_hours * 60)} min zonder metingen is niet meegeteld."
    return kwh, reading


def _telemetry_quality(base_quality: str, age_seconds: float | None) -> str:
    """A reading that is otherwise good but no longer live is stale."""
    if base_quality == "good" and freshness_state(age_seconds, TELEMETRY_EXPECTED_INTERVAL_SECONDS) != "live":
        return "stale"
    return base_quality


def _component_quality(components: list[dict[str, Any]], name: str) -> tuple[str, str | None]:
    """Map a /health/status component's ok/warning/error into good/stale/missing, plus its last-seen."""
    for component in components:
        if component.get("name") == name:
            status = component.get("status")
            quality = "good" if status == "ok" else "stale" if status == "warning" else "missing"
            return quality, component.get("last_seen")
    return "missing", None


@router.get("/api/dashboard/energy-center")
async def energy_center_overview(session: SessionDep) -> dict[str, Any]:
    """Normalized view model for the Energy Command Center (frontend/views.py
    energy_center_body). Assembles already-existing status/settings/health
    endpoints into one response so every card on that page reads the same
    numbers -- it does not read any telemetry this API didn't already expose
    elsewhere, and introduces no new control behavior."""
    battery, grid, household, settings, battery_meta, health, steering = await _energy_center_sources(session)

    duration, step_seconds, table_name = WINDOWS["day"]
    start, end, now_ = dashboard_window_bounds("day", duration)
    series, _ = await _window_series(session, table_name, step_seconds, start, now_, window="day", offset=None)

    pv_kwh, pv_total = _day_total(series["solar"], lambda p: max(0, p["power_w"]))
    _, home_total = _day_total(series["household"], lambda p: max(0, p["power_w"]))
    grid_import_kwh, grid_import_total = _day_total(series["grid"], lambda p: max(0, p["net_w"]))
    grid_export_kwh, grid_export_total = _day_total(series["grid"], lambda p: max(0, -p["net_w"]))
    charge_kwh, battery_charge_total = _day_total(series["battery"], lambda p: max(0, -p["power_w"]))
    discharge_kwh, battery_discharge_total = _day_total(series["battery"], lambda p: max(0, p["power_w"]))
    self_sufficiency_pct = canonical_self_sufficiency_pct(pv_kwh, grid_export_kwh, grid_import_kwh)
    self_inputs = (pv_total, grid_export_total, grid_import_total)
    self_quality = (
        "missing" if self_sufficiency_pct is None
        else "estimated" if any(r["quality"] == "estimated" for r in self_inputs)
        else "good"
    )

    components = health.get("components", [])
    pv_quality, pv_seen = _component_quality(components, "Solar / Enphase bridge")
    battery_quality, battery_seen = _component_quality(components, "Battery / GoodWe bridge")
    grid_quality, grid_seen = _component_quality(components, "DSMR / grid meter")

    pv_seen = pv_seen or grid.get("solar_updated_at")
    battery_seen = battery_seen or battery.get("bridge_last_seen")
    grid_seen = grid_seen or grid.get("grid_timestamp")

    pv_kw = (grid.get("solar_power_w") or 0) / 1000 if grid.get("solar_power_w") is not None else None
    battery_kw = battery.get("power_w") / 1000 if battery.get("power_w") is not None else None
    grid_kw = grid.get("grid_net_power_w") / 1000 if grid.get("grid_net_power_w") is not None else None
    home_kw = household.get("power_w") / 1000 if household.get("power_w") is not None else None

    min_soc = settings.get("soc_floor")
    max_soc = settings.get("soc_ceiling")
    soc_pct = battery.get("soc")
    soc_alert = battery_soc_alert(soc_pct, min_soc, max_soc)

    plan_status, _plan_generated_at, _curves, _price_source = await _dashboard_forecast_curves(session, now_, end, step_seconds)

    clock = _utcnow()
    source_ages = {
        "pv": reading_age_seconds(pv_seen, clock),
        "battery": reading_age_seconds(battery_seen, clock),
        "grid": reading_age_seconds(grid_seen, clock),
    }
    pv_quality = _telemetry_quality(pv_quality, source_ages["pv"])
    battery_quality = _telemetry_quality(battery_quality, source_ages["battery"])
    grid_quality = _telemetry_quality(grid_quality, source_ages["grid"])
    known_ages = [age for age in source_ages.values() if age is not None]
    newest_age = min(known_ages) if known_ages else None
    newest_seen = None
    if newest_age is not None:
        newest_seen = next(
            seen for seen, key in ((pv_seen, "pv"), (battery_seen, "battery"), (grid_seen, "grid")) if source_ages[key] == newest_age
        )

    alerts = build_energy_center_alerts(
        soc_alert=soc_alert,
        household=household,
        health_components=components,
        plan_status=plan_status,
    )
    top_severity = alerts[0]["severity"] if alerts else None

    connection = connection_state(list(source_ages.values()), health.get("status"))

    latest_decision = steering.get("latest_decision")
    latest_setpoint = steering.get("latest_setpoint")
    reason_text = (latest_decision or latest_setpoint or {}).get("trigger_reason")
    decided_at = (latest_decision or latest_setpoint or {}).get("timestamp") if (latest_decision or latest_setpoint) else None

    return {
        "connection": connection,
        "updatedAt": newest_seen,
        "telemetryAgeSeconds": round(newest_age, 1) if newest_age is not None else None,
        "instantaneous": {
            "pvKw": _reading(pv_kw, "kW", observed_at=pv_seen, source="/api/grid/status", quality=pv_quality),
            "homeKw": _reading(home_kw, "kW", observed_at=None, source="/api/household/status", quality="estimated" if household.get("approx") else grid_quality),
            "gridKw": _reading(grid_kw, "kW", observed_at=grid_seen, source="/api/grid/status", quality=grid_quality),
            "batteryKw": _reading(battery_kw, "kW", observed_at=battery_seen, source="/api/battery/status", quality=battery_quality),
            "gridDirection": grid_direction_label(grid_kw),
            "batteryDirection": battery_direction_label(battery_kw),
        },
        "today": {
            "pvKwh": pv_total,
            "homeKwh": home_total,
            "gridImportKwh": grid_import_total,
            "gridExportKwh": grid_export_total,
            "batteryChargeKwh": battery_charge_total,
            "batteryDischargeKwh": battery_discharge_total,
            "selfSufficiencyPct": _reading(
                round(self_sufficiency_pct, 1) if self_sufficiency_pct is not None else None,
                "%",
                observed_at=None,
                source="/api/dashboard/energy-center",
                quality=self_quality,
            ),
            "supplyMix": supply_mix(pv_kwh, grid_export_kwh, charge_kwh, grid_import_kwh, discharge_kwh),
            "selfSufficiencyMethod": (
                "100 x max(0, pv_kwh - grid_export_kwh) / (max(0, pv_kwh - grid_export_kwh) + grid_import_kwh) "
                "-- share of today's solar+import supply covered by solar kept on-site; same definition the classic dashboard uses."
            ),
        },
        "battery": {
            "socPct": _reading(soc_pct, "%", observed_at=battery_seen, source="/api/battery/status", quality=battery_quality),
            "minSocPct": min_soc,
            "maxSocPct": max_soc,
            "capacityKwh": _reading(battery_meta.get("capacity_kwh"), "kWh", observed_at=None, source="/api/battery/settings", quality="good"),
            "healthPct": _reading(battery.get("soh"), "%", observed_at=battery_seen, source="/api/battery/status", quality=battery_quality if battery.get("soh") is not None else "missing"),
            "temperatureC": None,
            "operationalState": battery.get("state"),
            "socAlert": soc_alert,
        },
        "agent": {
            "enabled": bool(latest_decision or latest_setpoint) or None,
            "mode": battery.get("state"),
            "reasonCode": reason_text,
            "reasonText": reason_text,
            "decidedAt": decided_at,
            "nextActionAt": None,
            "nextActionText": "Geen geplande actie beschikbaar",
            "constraints": {
                "socFloorPct": (latest_decision or {}).get("soc_floor", min_soc),
                "socCeilingPct": (latest_decision or {}).get("soc_ceiling", max_soc),
                "cooldownSeconds": settings.get("cooldown"),
                "dischargeAllowed": (latest_setpoint or {}).get("discharge_allowed"),
                "overrideMode": battery.get("override_mode", "none"),
                "overrideSocLimits": battery.get("override_soc_limits", False),
            },
        },
        "alerts": alerts,
        "topAlertSeverity": top_severity,
        "co2SavedKg": (
            _reading(round(pv_kwh * CO2_KG_PER_KWH, 2), "kg", observed_at=None, source="pv_kwh x 0.39 kg/kWh", quality=pv_total["quality"])
            if pv_kwh is not None
            else _reading(None, "kg", observed_at=None, source="pv_kwh x 0.39 kg/kWh", quality="missing")
        ),
        "sun": _sun_block(clock),
        "weather": None,  # no weather provider is configured; the UI shows it as unavailable
        "goals": {
            "selfSufficiencyPct": _goal("MINYAD_GOAL_SELF_SUFFICIENCY_PCT", 70.0),
            "consumptionKwh": _goal("MINYAD_GOAL_DAILY_CONSUMPTION_KWH", 8.0),
        },
    }


def _sun_block(clock: datetime) -> dict[str, Any]:
    local_day = clock.astimezone(SITE_TIMEZONE).date()
    rise, set_ = sun_times(SITE_LATITUDE, SITE_LONGITUDE, local_day, SITE_TIMEZONE)
    return {
        "sunrise": rise.isoformat() if rise else None,
        "sunset": set_.isoformat() if set_ else None,
        "source": "astronomical calculation for the forecast location",
    }


async def _energy_center_sources(session: SessionDep) -> tuple[dict[str, Any], ...]:
    battery = await battery_status(session)
    grid = await grid_status(session)
    household = await household_status_payload(session, store=False)
    settings = await battery_settings(session)
    battery_meta = await battery_lp_meta(session)
    health = await health_status(session)
    steering = await asset_steering_status(session)
    return battery, grid, household, settings, battery_meta, health, steering


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
    # _forecast_stale_status only returns None when plan_row is not None (see its
    # own plan_generated_at is None <=> plan_row is None check).
    assert plan_row is not None
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
