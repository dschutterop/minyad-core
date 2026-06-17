from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from minyad.common.config import get_config
from minyad.common.db import (
    connect,
    get_settings,
    json_safe,
    latest,
    latest_forecast,
    recent_control_log,
)
from minyad.integrations.goodwe import build_goodwe_client

app = FastAPI(title="Minyad API", version="0.1.0")


class SettingUpdate(BaseModel):
    value: str
    description: str | None = None


def _value(data: dict[str, Any], key: str, default: Any = None) -> Any:
    value = data.get(key, default)
    return default if value == "" else value


def _goodwe_setup_status(data: dict[str, Any]) -> dict[str, Any]:
    battery_soc = _value(data, "battery_soc")
    battery_errors = int(_value(data, "battery_error", 0) or 0)
    battery_warnings = int(_value(data, "battery_warning", 0) or 0)
    meter_status = int(_value(data, "meter_status", 0) or 0)
    grid_mode = int(_value(data, "grid_mode", 0) or 0)
    issues: list[str] = []
    if battery_soc in (None, 0):
        issues.append("Batterij-SOC is 0 of onbekend")
    if battery_errors:
        issues.append(f"Batterijfout actief ({battery_errors})")
    if battery_warnings:
        issues.append(f"Batterijwaarschuwing actief ({battery_warnings})")
    if meter_status != 1:
        issues.append("Meterstatus is niet verbonden/ok")
    if grid_mode != 1:
        issues.append("Omvormer is niet on-grid")

    return {
        "overall": "ok" if not issues else "warning",
        "issues": issues,
        "battery": {
            "soc_pct": battery_soc,
            "soh_pct": _value(data, "battery_soh"),
            "voltage_v": _value(data, "vbattery1"),
            "current_a": _value(data, "ibattery1"),
            "power_w": _value(data, "pbattery1"),
            "temperature_c": _value(data, "battery_temperature"),
            "mode": _value(data, "battery_mode_label", _value(data, "battery_mode")),
            "charge_limit_w": _value(data, "battery_charge_limit"),
            "discharge_limit_w": _value(data, "battery_discharge_limit"),
            "error": battery_errors,
            "warning": battery_warnings,
        },
        "grid": {
            "voltage_v": _value(data, "vgrid"),
            "current_a": _value(data, "igrid"),
            "power_w": _value(data, "pgrid"),
            "frequency_hz": _value(data, "fgrid"),
            "mode": _value(data, "grid_mode_label", _value(data, "grid_mode")),
            "direction": _value(data, "grid_in_out_label", _value(data, "grid_in_out")),
        },
        "load": {
            "voltage_v": _value(data, "vload"),
            "current_a": _value(data, "iload"),
            "power_w": _value(data, "pload"),
            "house_consumption_w": _value(data, "house_consumption"),
        },
        "inverter": {
            "work_mode": _value(data, "work_mode_label", _value(data, "work_mode")),
            "temperature_c": _value(data, "temperature"),
            "diagnose": _value(data, "diagnose_result_label", _value(data, "diagnose_result")),
            "pv_power_w": _value(data, "ppv"),
            "total_power_w": _value(data, "total_power"),
        },
        "raw": data,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM service_status ORDER BY service")
            services = cur.fetchall()
        grid = latest(conn, "grid_readings")
        solar = latest(conn, "solar_readings")
        battery = latest(conn, "battery_readings")
        control = recent_control_log(conn, 1)
        forecast = latest_forecast(conn, 24)
        settings = get_settings(conn)
    return json_safe(
        {
            "settings": settings,
            "grid": grid,
            "solar": solar,
            "battery": battery,
            "last_control": control[0] if control else None,
            "forecast": forecast,
            "services": services,
        }
    )


@app.get("/api/goodwe/status")
def goodwe_status() -> dict[str, Any]:
    try:
        data = build_goodwe_client(get_config()).read_runtime_data()
    except Exception as exc:  # noqa: BLE001 - API boundary returns diagnostics
        raise HTTPException(status_code=502, detail=f"Could not read GoodWe runtime data: {exc}") from exc
    return json_safe(_goodwe_setup_status(data))


@app.get("/api/settings")
def settings() -> dict[str, str]:
    with connect() as conn:
        return get_settings(conn)


@app.put("/api/settings/{key}")
def update_setting(key: str, update: SettingUpdate) -> dict[str, str]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO settings (key, value, description, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    description = COALESCE(NULLIF(EXCLUDED.description, ''), settings.description),
                    updated_at = now()
                RETURNING key, value
                """,
                (key, update.value, update.description or ""),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Could not update setting")
            return row


@app.get("/api/control-log")
def control_log(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        return json_safe(recent_control_log(conn, min(max(limit, 1), 200)))
