import logging
import time
from datetime import datetime
from typing import Any

import httpx

from minyad.common.config import get_config
from minyad.common.db import bulk_insert_forecast, connect, get_settings, setting_int
from minyad.common.logging import configure_logging
from minyad.common.retry import with_backoff
from minyad.common.status import update_status
from minyad.common.time import ensure_utc, utc_now

LOG = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_open_meteo(hours: int) -> dict[str, Any]:
    cfg = get_config()

    def call() -> dict[str, Any]:
        with httpx.Client(timeout=cfg.http_timeout_s) as client:
            response = client.get(
                OPEN_METEO_URL,
                params={
                    "latitude": cfg.latitude,
                    "longitude": cfg.longitude,
                    "hourly": "shortwave_radiation,direct_radiation,cloud_cover",
                    "forecast_days": max(1, min(16, (hours // 24) + 2)),
                    "timezone": "UTC",
                },
            )
            response.raise_for_status()
            return response.json()

    return with_backoff(call, label="open-meteo forecast")


def predicted_power_w(ghi_wm2: float, cloud_cover_pct: float) -> int:
    cfg = get_config()
    cloud_factor = max(0.15, 1 - (cloud_cover_pct / 100) * 0.35)
    return max(
        0, int(ghi_wm2 / 1000 * cfg.pv_peak_kw * 1000 * cfg.pv_performance_ratio * cloud_factor)
    )


def forecast_rows(payload: dict[str, Any], lookahead_h: int) -> list[dict[str, Any]]:
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    ghi = hourly.get("shortwave_radiation", [])
    dni = hourly.get("direct_radiation", [])
    cloud = hourly.get("cloud_cover", [])
    now = utc_now()
    rows: list[dict[str, Any]] = []
    for idx, time_value in enumerate(times[:lookahead_h]):
        target = ensure_utc(datetime.fromisoformat(str(time_value).replace("Z", "+00:00")))
        ghi_value = float(ghi[idx] or 0)
        cloud_value = float(cloud[idx] or 0)
        rows.append(
            {
                "timestamp_forecast": now,
                "timestamp_target": target,
                "ghi_wm2": ghi_value,
                "dni_wm2": float(dni[idx] or 0) if idx < len(dni) else None,
                "cloud_cover_pct": cloud_value,
                "predicted_w": predicted_power_w(ghi_value, cloud_value),
            }
        )
    return rows


def refresh_once() -> int:
    with connect() as conn:
        settings = get_settings(conn)
        lookahead = setting_int(settings, "forecast_lookahead_h", 36)
    payload = fetch_open_meteo(lookahead)
    rows = forecast_rows(payload, lookahead)
    with connect() as conn:
        bulk_insert_forecast(conn, rows)
        update_status(conn, "forecast", "ok", {"rows": len(rows)})
    return len(rows)


def main() -> None:
    configure_logging()
    while True:
        interval = 21600
        try:
            rows = refresh_once()
            LOG.info("Stored %s forecast rows", rows)
            with connect() as conn:
                interval = setting_int(get_settings(conn), "forecast_refresh_interval_s", 21600)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Forecast refresh failed: %s", exc)
            with connect() as conn:
                update_status(conn, "forecast", "error", {"error": str(exc)})
                interval = setting_int(get_settings(conn), "forecast_refresh_interval_s", 21600)
        time.sleep(max(60, interval))


if __name__ == "__main__":
    main()
