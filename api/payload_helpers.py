"""Pure payload-shaping/computation helpers for the Minyad API.

Everything here takes plain data in and returns plain data out -- no
`AsyncSession`, no MQTT client, no module-level mutable caches. That's the
boundary: anything that touches the database, the MQTT client, or api.main's
shared state (locks/caches) stays in api/main.py, where that coupling
genuinely lives.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Literal
from zoneinfo import ZoneInfo

try:
    # minyad.strategy.v3 is Minyad's private forecasting/planning core and is not part of
    # this public repository (see README's "Not included" section). It's only importable
    # when deployed alongside the private package. Standalone Minyad Core always reports
    # minyad_forecast as unavailable rather than fabricating a trajectory.
    from minyad.strategy.v3 import forecast_contract
except ImportError:
    forecast_contract = None

LOGGER = logging.getLogger(__name__)

UTC_OFFSET_SUFFIX = "+00:00"

# Whether the private strategy-v3 package (and therefore the rest of the private deployment --
# minyad-agent, minyad-trade) is present alongside this public repo. Exposed via /health so the
# frontend can label itself "Minyad Core" vs "Minyad Plus" without importing strategy internals.
PRIVATE_MODULES_AVAILABLE = forecast_contract is not None

MQTT_STATUS_KEYS = {
    "minyad/battery/soc": "soc",
    "minyad/battery/soh": "soh",
    "minyad/battery/power_w": "power_w",
    "minyad/battery/voltage": "voltage",
    "minyad/battery/voltage_v": "voltage",
    "minyad/battery/mode": "mode",
    "minyad/battery/mode_label": "mode_label",
    "minyad/battery/charge_i": "charge_i",
    "minyad/bridge/status": "bridge_status",
    "minyad/bridge/last_seen": "bridge_last_seen",
    "minyad/inverter/grid_power_w": "grid_power_w",
    "minyad/control/state": "state",
    "minyad/control/override_mode": "override_mode",
    "minyad/control/setpoint_w": "setpoint_w",
    "minyad/control/discharge_w": "discharge_w",
}

GRID_STATUS_KEYS = {
    "minyad/grid/delivered_w": "grid_delivered_w",
    "minyad/grid/returned_w": "grid_returned_w",
    "minyad/grid/net_power_w": "grid_net_power_w",
    "minyad/grid/phase_delivered_l1_w": "grid_phase_delivered_l1_w",
    "minyad/grid/phase_delivered_l2_w": "grid_phase_delivered_l2_w",
    "minyad/grid/phase_delivered_l3_w": "grid_phase_delivered_l3_w",
    "minyad/grid/phase_returned_l1_w": "grid_phase_returned_l1_w",
    "minyad/grid/phase_returned_l2_w": "grid_phase_returned_l2_w",
    "minyad/grid/phase_returned_l3_w": "grid_phase_returned_l3_w",
    "minyad/grid/voltage_l1_v": "grid_voltage_l1_v",
    "minyad/grid/voltage_l2_v": "grid_voltage_l2_v",
    "minyad/grid/voltage_l3_v": "grid_voltage_l3_v",
    "minyad/grid/timestamp": "grid_timestamp",
    "minyad/grid/status": "grid_status",
}
SOLAR_STATUS_KEYS = {
    "minyad/solar/production_w": "solar_power_w",
    "minyad/solar/production_updated_at": "solar_updated_at",
    "minyad/solar/bridge/status": "solar_bridge_status",
    "minyad/solar/bridge/last_seen": "solar_bridge_last_seen",
}
MQTT_STATUS_KEYS.update(GRID_STATUS_KEYS)
MQTT_STATUS_KEYS.update(SOLAR_STATUS_KEYS)

BATTERY_DEFAULTS = {
    "inverter_poll_interval_s": 120,
    "goodwe_poll_interval_grace_s": 60,
}

SURPLUS_API_VERSION = "v1"
MINYAD_FORECAST_SCENARIO_COUNT = 100
MINYAD_FORECAST_MODEL_VERSION = "strategy-v3-lp"
PLAN_STALE_MINUTES = 30


def solar_dynamic_status_key(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) == 5 and parts[:3] == ["minyad", "solar", "inverter"] and parts[4] in {"power_w", "last_report_at"}:
        return f"solar_inverter_{parts[3]}_{parts[4]}"
    if len(parts) == 5 and parts[:3] == ["minyad", "solar", "array"] and parts[4] == "power_w":
        return f"solar_array_{parts[3]}_power_w"
    return None


def mqtt_status_key(topic: str) -> str | None:
    return MQTT_STATUS_KEYS.get(topic) or solar_dynamic_status_key(topic)


def cached_status_is_incomplete(payload: dict[str, Any]) -> bool:
    required_keys = (
        "soc",
        "soh",
        "power_w",
        "voltage",
        "mode",
        "bridge_status",
        "bridge_last_seen",
    )
    return any(key not in payload or payload[key] in (None, "") for key in required_keys)


def coerce_int_status_value(key: str, value: Any) -> int | Any:
    if value in (None, ""):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-integer status value for %s: %r", key, value)
        return value


def coerce_float_status_value(key: str, value: Any) -> float | Any:
    if value in (None, ""):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-float status value for %s: %r", key, value)
        return value


def grid_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key.startswith(("grid_", "solar_"))
    }


def battery_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if not key.startswith("grid_") or key == "grid_power_w"
    }


def _numeric_w(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring non-numeric watt value for %s: %r", key, value)
        return None


def derive_battery_state(payload: dict[str, Any], fallback: str = "IDLE") -> str:
    """Derive actual battery activity from bridge telemetry.

    The control state describes what Minyad asked the inverter to do, but the
    bridge telemetry is the source of truth for what the battery is doing.  A
    small deadband avoids reporting activity from inverter measurement noise.
    """
    deadband_w = 25
    power_w = _numeric_w(payload, "power_w")
    mode_text = " ".join(
        str(payload.get(key, "")).strip().lower()
        for key in ("mode", "mode_label")
        if payload.get(key) not in (None, "")
    )

    if power_w is not None and abs(power_w) > deadband_w:
        if "discharge" in mode_text:
            return "DISCHARGING"
        if "charge" in mode_text:
            return "CHARGING"
        return "DISCHARGING" if power_w > 0 else "CHARGING"

    if "discharge" in mode_text:
        return "DISCHARGING"
    if "charge" in mode_text:
        return "CHARGING"
    return fallback or "IDLE"


def solar_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    inverters: dict[str, dict[str, Any]] = {}
    arrays: dict[str, int | str] = {}
    for key, value in payload.items():
        if key.startswith("solar_inverter_") and key.endswith("_power_w"):
            serial = key.removeprefix("solar_inverter_").removesuffix("_power_w")
            inverters.setdefault(serial, {"serial": serial})["power_w"] = coerce_int_status_value(key, value)
        elif key.startswith("solar_inverter_") and key.endswith("_last_report_at"):
            serial = key.removeprefix("solar_inverter_").removesuffix("_last_report_at")
            inverters.setdefault(serial, {"serial": serial})["last_report_at"] = value
        elif key.startswith("solar_array_") and key.endswith("_power_w"):
            array = key.removeprefix("solar_array_").removesuffix("_power_w")
            arrays[array] = coerce_int_status_value(key, value)
    inverter_list = sorted(inverters.values(), key=lambda item: str(item.get("serial", "")))
    total = payload.get("solar_power_w")
    if total is None:
        numeric = [item.get("power_w") for item in inverter_list]
        total = sum(value for value in numeric if isinstance(value, int))
    else:
        total = coerce_int_status_value("solar_power_w", total)
    return {
        "power_w": total,
        "updated_at": payload.get("solar_updated_at"),
        "bridge_status": payload.get("solar_bridge_status"),
        "bridge_last_seen": payload.get("solar_bridge_last_seen"),
        "inverters": inverter_list,
        "arrays": arrays,
    }


def coerce_grid_status(payload: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(payload)
    int_keys = {
        "solar_power_w",
        "grid_delivered_w",
        "grid_returned_w",
        "grid_net_power_w",
        "grid_phase_delivered_l1_w",
        "grid_phase_delivered_l2_w",
        "grid_phase_delivered_l3_w",
        "grid_phase_returned_l1_w",
        "grid_phase_returned_l2_w",
        "grid_phase_returned_l3_w",
    }
    float_keys = {"grid_voltage_l1_v", "grid_voltage_l2_v", "grid_voltage_l3_v"}
    for key in int_keys:
        if key in coerced:
            coerced[key] = coerce_int_status_value(key, coerced[key])
    for key in float_keys:
        if key in coerced:
            coerced[key] = coerce_float_status_value(key, coerced[key])
    return coerced


def parse_bridge_last_seen(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", UTC_OFFSET_SUFFIX))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def enrich_bridge_health(payload: dict[str, Any]) -> None:
    last_seen_value = payload.get("bridge_last_seen")
    last_seen = parse_bridge_last_seen(last_seen_value if isinstance(last_seen_value, str) else None)
    payload["bridge_last_seen_valid"] = False
    if last_seen is None:
        payload["bridge_last_seen_error"] = "missing or invalid bridge last_seen"
        if payload.get("bridge_status") == "online":
            payload["available"] = False
        return

    age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
    payload["bridge_last_seen_age_seconds"] = max(0, round(age_seconds))
    payload["bridge_last_seen_valid"] = age_seconds <= 60
    if age_seconds > 60:
        payload["bridge_last_seen_error"] = "bridge last_seen is older than 60 seconds"
        payload["available"] = False


def component_status(name: str, status: Literal["ok", "warning", "error"], detail: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    payload.update(extra)
    return payload


def value_is_fresh_iso(value: Any, max_age_seconds: int = 120) -> tuple[bool, int | None]:
    if not isinstance(value, str) or not value:
        return False, None
    parsed = parse_bridge_last_seen(value)
    if parsed is None:
        return False, None
    age = max(0, round((datetime.now(timezone.utc) - parsed).total_seconds()))
    return age <= max_age_seconds, age


def battery_health_component(cache: dict[str, Any]) -> dict[str, Any]:
    battery_required = ("soc", "power_w", "voltage", "mode", "bridge_status", "bridge_last_seen")
    battery_missing = [key for key in battery_required if not cache.get(key)]
    bridge_fresh, bridge_age = value_is_fresh_iso(cache.get("bridge_last_seen"), 90)
    battery_ok = not battery_missing and str(cache.get("bridge_status", "")).lower() == "online" and bridge_fresh
    return component_status(
        "Battery / GoodWe bridge",
        "ok" if battery_ok else "warning",
        "GoodWe bridge telemetry is current" if battery_ok else "Missing, stale, or offline GoodWe telemetry",
        endpoint="/battery/status",
        missing_keys=battery_missing,
        bridge_status=cache.get("bridge_status"),
        last_seen=cache.get("bridge_last_seen"),
        age_seconds=bridge_age,
    )


def grid_health_component(cache: dict[str, Any]) -> dict[str, Any]:
    grid_required = ("grid_net_power_w", "grid_timestamp", "grid_status")
    grid_missing = [key for key in grid_required if not cache.get(key)]
    grid_fresh, grid_age = value_is_fresh_iso(cache.get("grid_timestamp"), 120)
    grid_ok = not grid_missing and grid_fresh
    return component_status(
        "DSMR / grid meter",
        "ok" if grid_ok else "warning",
        "Grid meter telemetry is current" if grid_ok else "Missing or stale DSMR grid telemetry",
        endpoint="/dsmr/status",
        missing_keys=grid_missing,
        grid_status=cache.get("grid_status"),
        last_seen=cache.get("grid_timestamp"),
        age_seconds=grid_age,
    )


def solar_health_component(cache: dict[str, Any]) -> dict[str, Any]:
    solar_fresh, solar_age = value_is_fresh_iso(cache.get("solar_updated_at") or cache.get("solar_bridge_last_seen"), 180)
    inverter_keys = [key for key in cache if key.startswith("solar_inverter_") and key.endswith("_power_w")]
    solar_ok = bool(cache.get("solar_power_w") is not None or inverter_keys) and solar_fresh
    return component_status(
        "Solar / Enphase bridge",
        "ok" if solar_ok else "warning",
        "Solar production telemetry is current" if solar_ok else "Missing or stale solar telemetry",
        endpoint="/solar/status",
        bridge_status=cache.get("solar_bridge_status"),
        last_seen=cache.get("solar_updated_at") or cache.get("solar_bridge_last_seen"),
        age_seconds=solar_age,
        inverter_count=len(inverter_keys),
    )


def serialize_control_decision(row: Any) -> dict[str, Any]:
    data = dict(row)
    timestamp = data.get("timestamp")
    if timestamp is not None:
        data["timestamp"] = timestamp.replace(tzinfo=timezone.utc).isoformat()
    setpoint = data.get("setpoint_w") or 0
    source = data.get("source") or ""
    discharge_allowed = bool(data.get("discharge_allowed"))
    if setpoint == 0:
        action = "discharge" if discharge_allowed else "hold"
    elif source in {"strategy_v2", "strategy_v3", "goodwe_bridge"}:
        action = "charge" if setpoint > 0 else "discharge"
    else:
        action = "discharge" if setpoint > 0 else "charge"
    data["action"] = action
    return data


def setpoint_log_select_list(columns: set[str]) -> str:
    def col(name: str, fallback: str | None = None, alias: str | None = None) -> str:
        target = alias or name
        if name in columns:
            return name if target == name else f"{name} as {target}"
        if fallback and fallback in columns:
            return f"{fallback} as {target}"
        return f"null as {target}"

    return ", ".join(
        [
            col("id"),
            col("timestamp"),
            col("source"),
            col("soc_floor"),
            col("soc_ceiling"),
            col("setpoint_w", "charge_rate_w"),
            col("discharge_allowed"),
            col("battery_soc_at_time"),
            col("grid_power_at_time"),
            col("battery_power_at_time"),
            col("apparent_load_at_time", "home_load_at_time"),
            col("setpoint_delta"),
            col("trigger_reason"),
            col("ack_received"),
            col("ack_latency_ms"),
        ]
    )


def derived_bridge_stale_seconds(settings: dict[str, Any]) -> int:
    return int(settings.get("inverter_poll_interval_s", BATTERY_DEFAULTS["inverter_poll_interval_s"])) + int(
        settings.get("goodwe_poll_interval_grace_s", BATTERY_DEFAULTS["goodwe_poll_interval_grace_s"])
    )


def parse_status_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", UTC_OFFSET_SUFFIX))
    except ValueError:
        LOGGER.warning("Ignoring invalid status timestamp: %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def active_battery_setpoint_w(payload: dict[str, Any]) -> int | None:
    discharge_w = coerce_int_status_value("discharge_w", payload["discharge_w"]) if payload.get("discharge_w") not in (None, "") else 0
    setpoint_w = coerce_int_status_value("setpoint_w", payload["setpoint_w"]) if payload.get("setpoint_w") not in (None, "") else 0
    if discharge_w:
        return abs(discharge_w)
    if setpoint_w:
        return -abs(setpoint_w)
    return None


def battery_curve_power_w(payload: dict[str, Any]) -> int | None:
    """Return the measured battery power for charts, falling back to setpoints.

    The dashboard graph should reflect what the inverter reports the battery is
    actually doing.  Setpoints are only useful when no measured power telemetry
    is available; otherwise stale discharge/charge commands can make an idle
    battery look active in the graph while the status card correctly shows
    standby.
    """
    actual_power_w = _numeric_w(payload, "power_w")
    if actual_power_w is not None:
        return actual_power_w
    return active_battery_setpoint_w(payload)


def compute_household_load(payload: dict[str, Any]) -> dict[str, Any]:
    solar_w = max(0, _numeric_w(payload, "solar_power_w") or 0)
    battery_power_w = battery_curve_power_w(payload) or 0
    battery_discharge_w = max(0, battery_power_w)
    battery_charge_w = max(0, -battery_power_w)
    grid_import_w = _numeric_w(payload, "grid_delivered_w")
    grid_export_w = _numeric_w(payload, "grid_returned_w")
    grid_net_w = _numeric_w(payload, "grid_net_power_w")
    has_dsmr = grid_import_w is not None or grid_export_w is not None or grid_net_w is not None
    if grid_import_w is None:
        grid_import_w = max(0, grid_net_w or 0)
    if grid_export_w is None:
        grid_export_w = max(0, -(grid_net_w or 0))

    method_a_raw = solar_w + battery_discharge_w - battery_charge_w - grid_export_w
    method_b_raw = solar_w + battery_discharge_w - battery_charge_w + grid_import_w - grid_export_w
    using_method = "B" if has_dsmr else "A"
    raw = method_b_raw if has_dsmr else method_a_raw
    load_w = round(raw)
    if load_w < 0:
        LOGGER.warning("Clamping negative household load to zero: raw=%s method=%s payload_keys=%s", raw, using_method, sorted(payload.keys()))
        load_w = 0
    method_a_w = max(0, round(method_a_raw))
    method_b_w = max(0, round(method_b_raw))
    comparable_method_b_w = max(0, round(method_b_raw - grid_import_w))
    reference = max(abs(comparable_method_b_w), 1)
    deviation_pct = abs(method_a_w - comparable_method_b_w) / reference * 100
    mismatch = has_dsmr and deviation_pct > 15
    if mismatch:
        LOGGER.debug(
            "Household load sanity-check mismatch: method_a=%sW method_b=%sW deviation=%.1f%% solar=%sW battery_charge=%sW battery_discharge=%sW grid_import=%sW grid_export=%sW",
            method_a_w, comparable_method_b_w, deviation_pct, solar_w, battery_charge_w, battery_discharge_w, grid_import_w, grid_export_w,
        )
    return {
        "power_w": load_w,
        "method": using_method,
        "approx": not has_dsmr,
        "mismatch": mismatch,
        "deviation_pct": round(deviation_pct, 1),
        "method_a_w": method_a_w,
        "method_b_w": method_b_w,
        "solar_power_w": solar_w,
        "battery_charge_w": battery_charge_w,
        "battery_discharge_w": battery_discharge_w,
        "grid_import_w": grid_import_w,
        "grid_export_w": grid_export_w,
    }


def _status_text(value: Any, fallback: str = "UNKNOWN") -> str:
    text_value = str(value or fallback).strip().upper()
    return text_value or fallback


def _battery_phase(control_state: str, activity_state: str, battery_charge_w: int, battery_discharge_w: int) -> str:
    if control_state == "COOLDOWN":
        return "cooldown"
    if activity_state == "CHARGING" or control_state == "CHARGING" or battery_charge_w > 0:
        return "charging"
    if activity_state == "DISCHARGING" or control_state == "DISCHARGING" or battery_discharge_w > 0:
        return "discharging"
    return "idle"


def _strategy_module_unavailable_outcome() -> SimpleNamespace:
    """The documented ``minyad_forecast`` "unavailable" shape (docs/minyad_forecast_contract.md)
    for standalone Minyad Core deployments that don't have the private strategy-v3 package.
    """
    return SimpleNamespace(
        validation_status="invalid",
        validation_reason="strategy_module_unavailable",
        forecast={
            "source": "minyad_lp",
            "quality": "unavailable",
            "validation": {
                "status": "invalid",
                "reason": "strategy_module_unavailable",
                "age_s": None,
                "scenario_count": None,
            },
        },
        soc_trajectory_pct=None,
    )


def build_surplus_payload(
    grid: dict[str, Any],
    battery: dict[str, Any],
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    *,
    battery_meta: dict[str, Any] | None = None,
    attempt_forecast: bool = False,
    plan_payload: dict[str, Any] | None = None,
    plan_generated_at: datetime | None = None,
    plan_solver_status: str | None = None,
    uncertainty_bands: dict[str, Any] | None = None,
    scenario_count: int = MINYAD_FORECAST_SCENARIO_COUNT,
    stale_minutes: int = PLAN_STALE_MINUTES,
    model_version: str = MINYAD_FORECAST_MODEL_VERSION,
    forecast_seed: int | None = None,
) -> dict[str, Any]:
    """Build the external surplus snapshot used by downstream surplus consumers.

    Positive surplus is export/available power.  ``surplus_w`` is the remaining
    grid export after Minyad's battery steering; ``gross_surplus_w`` adds the
    measured battery charge power so a consumer can see that surplus exists even
    while Minyad is still feeding it into the battery.

    ``battery_meta``/``plan_payload``/``uncertainty_bands`` are optional and additive: callers
    that don't pass ``attempt_forecast=True`` (e.g. existing tests and any surplus consumer
    written before the minyad_forecast contract existed) get exactly the legacy response shape
    back, with no ``minyad_forecast`` key and no new ``battery`` fields. ``attempt_forecast=True``
    opts into the forecast contract — Minyad's authoritative budget/SoC trajectory, or an
    explicit "unavailable" marker (with a failure reason) if the LP plan isn't fit to publish
    right now, including when there's no plan at all yet (see
    minyad.strategy.v3.forecast_contract). It never fabricates a trajectory or quantiles.
    """
    settings = settings or {}
    timestamp = now or datetime.now(timezone.utc)
    grid_net_w = _numeric_w(grid, "grid_net_power_w")
    grid_import_w = _numeric_w(grid, "grid_delivered_w")
    grid_export_w = _numeric_w(grid, "grid_returned_w")
    if grid_import_w is None:
        grid_import_w = max(0, grid_net_w or 0)
    if grid_export_w is None:
        grid_export_w = max(0, -(grid_net_w or 0))

    battery_power_w = battery_curve_power_w(battery)
    battery_charge_w = max(0, -(battery_power_w or 0))
    battery_discharge_w = max(0, battery_power_w or 0)
    remaining_surplus_w = max(0, grid_export_w)
    gross_surplus_w = remaining_surplus_w + battery_charge_w
    control_state = _status_text(battery.get("control_state") or battery.get("state"), "IDLE")
    activity_state = _status_text(battery.get("state") or derive_battery_state(battery), control_state)
    battery_phase = _battery_phase(control_state, activity_state, battery_charge_w, battery_discharge_w)

    forecast_outcome: Any = None
    if attempt_forecast:
        if forecast_contract is not None:
            forecast_outcome = forecast_contract.build_minyad_forecast(
                plan_payload=plan_payload,
                plan_generated_at=plan_generated_at,
                plan_solver_status=plan_solver_status,
                uncertainty_bands=uncertainty_bands,
                now=timestamp,
                stale_minutes=stale_minutes,
                scenario_count=scenario_count,
                model_version=model_version,
                seed=forecast_seed,
            )
        else:
            forecast_outcome = _strategy_module_unavailable_outcome()
        if forecast_outcome.validation_status == "invalid":
            LOGGER.warning(
                "minyad_forecast unavailable: reason=%s model_version=%s now=%s",
                forecast_outcome.validation_reason, model_version, timestamp.astimezone(timezone.utc).isoformat(),
            )

    payload = {
        "api_version": SURPLUS_API_VERSION,
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "surplus_w": remaining_surplus_w,
        "gross_surplus_w": gross_surplus_w,
        "has_surplus": remaining_surplus_w > 0,
        "has_gross_surplus": gross_surplus_w > 0,
        "grid": {
            "net_power_w": grid_net_w,
            "import_w": grid_import_w,
            "export_w": grid_export_w,
            "status": grid.get("grid_status"),
            "timestamp": grid.get("grid_timestamp"),
        },
        "solar": {
            "power_w": _numeric_w(grid, "solar_power_w"),
            "updated_at": grid.get("solar_updated_at"),
        },
        "battery": {
            "phase": battery_phase,
            "control_state": control_state,
            "activity_state": activity_state,
            "mode": battery.get("mode"),
            "mode_label": battery.get("mode_label"),
            "power_w": battery_power_w,
            "charge_w": battery_charge_w,
            "discharge_w": battery_discharge_w,
            "soc": battery.get("soc"),
            "soc_floor": settings.get("soc_floor"),
            "soc_ceiling": settings.get("soc_ceiling"),
            "available": battery.get("available"),
            "override_mode": battery.get("override_mode", "none"),
            "bridge_status": battery.get("bridge_status"),
            "bridge_last_seen": battery.get("bridge_last_seen"),
            "is_charging": battery_phase == "charging",
            "is_discharging": battery_phase == "discharging",
            "is_idle": battery_phase == "idle",
            "is_cooldown": battery_phase == "cooldown",
        },
        "minyad": {
            "surplus_handling": battery_phase,
            "is_absorbing_surplus": battery_phase == "charging",
            "cooldown_seconds": settings.get("cooldown"),
            "charge_start_threshold_w": settings.get("start_w"),
            "charge_stop_threshold_w": settings.get("stop_w"),
        },
    }

    if battery_meta is not None:
        payload["battery"].update(battery_meta)

    if forecast_outcome is not None:
        payload["minyad_forecast"] = forecast_outcome.forecast
        # Compatibility period (see docs/minyad_forecast_contract.md): downstream consumers
        # currently read battery.soc_trajectory_pct for slot-level SoC; populate it alongside
        # minyad_forecast.soc_pct rather than only in the new block. Omitted entirely (not a
        # copied current SoC) when the forecast itself is unavailable.
        if forecast_outcome.soc_trajectory_pct is not None:
            payload["battery"]["soc_trajectory_pct"] = forecast_outcome.soc_trajectory_pct

    return payload


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.month - 1) + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month)


def dashboard_window_bounds(
    window: str,
    duration: timedelta,
    now: datetime | None = None,
    period_offset: int | None = None,
) -> tuple[datetime, datetime, datetime]:
    now_ = now or datetime.now(timezone.utc)
    if now_.tzinfo is None:
        now_ = now_.replace(tzinfo=timezone.utc)
    now_ = now_.astimezone(timezone.utc)
    dashboard_tz = ZoneInfo(os.getenv("MINYAD_TIMEZONE", "Europe/Amsterdam"))
    local_now = now_.astimezone(dashboard_tz)

    if period_offset is not None and window in {"day", "week", "month", "year"}:
        if window == "day":
            local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=period_offset)
            local_next = local_start + timedelta(days=1)
        elif window == "week":
            local_week = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local_now.weekday())
            local_start = local_week + timedelta(weeks=period_offset)
            local_next = local_start + timedelta(weeks=1)
        elif window == "month":
            local_month = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            local_start = _add_months(local_month, period_offset)
            local_next = _add_months(local_start, 1)
        else:
            local_year = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            local_start = _add_months(local_year, period_offset * 12)
            local_next = _add_months(local_start, 12)
        local_end = local_next - timedelta(seconds=1)
        start = local_start.astimezone(timezone.utc)
        end = local_end.astimezone(timezone.utc)
        query_until = min(now_, end)
        return start, end, query_until

    if window != "day":
        return now_ - duration, now_, now_

    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc), now_


def _bucket_expr(column: str, seconds: int) -> str:
    return f"to_timestamp(floor(extract(epoch from {column}) / {seconds}) * {seconds})"


def interpolate_points(points: list[dict[str, Any]], step_seconds: int) -> list[dict[str, Any]]:
    if len(points) < 2 or step_seconds >= 900:
        return points
    parsed = [(datetime.fromisoformat(p["timestamp"].replace("Z", UTC_OFFSET_SUFFIX)), p["power_w"]) for p in points]
    output = []
    for (left_ts, left_w), (right_ts, right_w) in zip(parsed, parsed[1:]):
        span = max(1, (right_ts - left_ts).total_seconds())
        cursor = left_ts
        while cursor < right_ts:
            ratio = (cursor - left_ts).total_seconds() / span
            output.append({"timestamp": cursor.isoformat(), "power_w": round(left_w + ((right_w - left_w) * ratio))})
            cursor += timedelta(seconds=step_seconds)
    output.append({"timestamp": parsed[-1][0].isoformat(), "power_w": parsed[-1][1]})
    return output


def _slot_battery_w(prev_soc_pct: float, soc_target_pct: float, capacity_wh: float, slot_seconds: int) -> int:
    """Net terminal battery power implied by the SoC-target trajectory (dashboard_forecast_v1 spec 3.3).

    Derived from the SoC delta rather than the LP's gross charge_w/discharge_w: round-trip
    efficiency losses are already priced into the plan, so this is the planned net klemvermogen
    without further correction. Positive = discharge, negative = charge (GoodWe convention).
    """
    if slot_seconds <= 0:
        return 0
    delta_fraction = (soc_target_pct - prev_soc_pct) / 100.0
    slot_hours = slot_seconds / 3600.0
    return round(-delta_fraction * capacity_wh / slot_hours)


def _classify_cloud_cover(cloud_cover_pct: float) -> str:
    """Mirrors minyad.strategy.v3.pv_uncertainty.classify_cloud_cover (kept duplicated rather
    than importing the strategy package here, matching this service's existing DB/MQTT-only
    boundary with strategy internals)."""
    if cloud_cover_pct < 25.0:
        return "clear"
    if cloud_cover_pct < 75.0:
        return "partly"
    return "cloudy"


def build_plan_curves(
    payload: dict[str, Any],
    capacity_wh: float,
    fallback_soc_pct: float,
    now_: datetime,
    window_end: datetime,
    uncertainty_bands: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Derive the four forecast curves + curtailment from one plan payload (spec 3.2/3.3),
    plus a PV P10-P90 uncertainty band where the slot's cloud-cover class has enough history
    (spec 4.4) — slots without a usable band are simply omitted, never a fabricated one.

    Slots that have already fully elapsed relative to ``now_`` are dropped, so the forecast
    curves start at "now" — matching the measured series, which stops at "now" (spec 3.5).
    """
    slot_seconds = int(payload["slot_seconds"])
    prev_soc = float(payload.get("soc_start_pct", fallback_soc_pct))
    pv: list[dict[str, Any]] = []
    load: list[dict[str, Any]] = []
    battery: list[dict[str, Any]] = []
    grid: list[dict[str, Any]] = []
    curtailment: list[dict[str, Any]] = []
    price_source: list[dict[str, Any]] = []
    pv_p10: list[dict[str, Any]] = []
    pv_p90: list[dict[str, Any]] = []
    for slot in payload.get("slots", []):
        slot_start = datetime.fromisoformat(slot["start"])
        slot_end = slot_start + timedelta(seconds=slot_seconds)
        soc_target = float(slot.get("soc_target_pct", prev_soc))
        battery_w = _slot_battery_w(prev_soc, soc_target, capacity_wh, slot_seconds)
        prev_soc = soc_target
        if slot_end <= now_ or slot_start > window_end:
            continue
        ts = slot_start.isoformat()
        pv_w = round(float(slot.get("pv_forecast_w") or 0))
        load_w = round(float(slot.get("load_forecast_w") or 0))
        grid_w = round(load_w - pv_w - battery_w)
        curtail_w = round(float(slot.get("curtailment_w") or 0))
        pv.append({"timestamp": ts, "power_w": pv_w})
        load.append({"timestamp": ts, "power_w": load_w})
        battery.append({"timestamp": ts, "power_w": battery_w})
        grid.append({"timestamp": ts, "power_w": grid_w})
        curtailment.append({"timestamp": ts, "power_w": curtail_w})
        price_source.append({"timestamp": ts, "source": slot.get("price_source", "fallback")})
        cloud_cover_pct = slot.get("cloud_cover_pct")
        if uncertainty_bands and cloud_cover_pct is not None:
            band = uncertainty_bands.get(_classify_cloud_cover(float(cloud_cover_pct)))
            if band is not None:
                pv_p10.append({"timestamp": ts, "power_w": round(pv_w * band["p10_multiplier"])})
                pv_p90.append({"timestamp": ts, "power_w": round(pv_w * band["p90_multiplier"])})
    curves = {
        "forecast": pv,
        "load_forecast": load,
        "battery_forecast": battery,
        "grid_forecast": grid,
        "curtailment_forecast": curtailment,
        "pv_p10_forecast": pv_p10,
        "pv_p90_forecast": pv_p90,
    }
    return curves, price_source


def _normalize_battery_override_mode(mode: str | None) -> str:
    if mode == "force_on":
        return "force_charge"
    if mode == "force_off":
        return "force_idle"
    return mode or "none"


def serialize_agent_message(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("created_at", "read_at", "archived_at", "operator_ack_at", "agent_ack_at"):
        value = data.get(key)
        if value is not None:
            data[key] = value.replace(tzinfo=timezone.utc).isoformat()
    return data


def serialize_agent_decision(row: Any) -> dict[str, Any]:
    data = dict(row)
    value = data.get("created_at")
    if value is not None:
        data["created_at"] = value.replace(tzinfo=timezone.utc).isoformat()
    snapshot = data.get("input_snapshot")
    if isinstance(snapshot, str):
        try:
            data["input_snapshot"] = json.loads(snapshot)
        except json.JSONDecodeError:
            data["input_snapshot"] = {"raw": snapshot}
    return data


def _parse_log_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", UTC_OFFSET_SUFFIX)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_log_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.replace(tzinfo=timezone.utc).isoformat()
        elif isinstance(value, date):
            data[key] = value.isoformat()
    return data


def _validate_battery_override_limits(
    request: Any,
    mode: str,
    soc_value: float | None,
    soc_floor: int,
    soc_ceiling: int,
    max_allowed_w: int,
) -> str | None:
    if not request.override_soc_limits and mode == "force_discharge" and soc_value is not None and soc_value <= soc_floor:
        return f"discharge blocked because SoC {soc_value:g}% is at or below configured floor {soc_floor}%"
    if not request.override_soc_limits and mode == "force_charge" and soc_value is not None and soc_value >= soc_ceiling:
        return f"charge blocked because SoC {soc_value:g}% is at or above configured ceiling {soc_ceiling}%"
    if request.watts is not None and request.watts > max_allowed_w:
        limit_name = "MAX_DISCHARGE_W" if mode == "force_discharge" else "MAX_CHARGE_W"
        return f"watts must not exceed {limit_name} ({max_allowed_w})"
    return None
