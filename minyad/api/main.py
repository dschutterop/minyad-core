from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from minyad.common.db import (
    connect,
    get_settings,
    json_safe,
    latest,
    latest_forecast,
    recent_control_log,
)

app = FastAPI(title="Minyad API", version="0.1.0")


class SettingUpdate(BaseModel):
    value: str
    description: str | None = None


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
