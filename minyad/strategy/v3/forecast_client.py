"""Open-Meteo client for strategy v3: irradiance forecast/history and sunset times."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SCHIPLUIDEN_LAT = 51.97
SCHIPLUIDEN_LON = 4.31
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
FALLBACK_SUNSET_LOCAL_HOUR = 21


async def fetch_ghi_hourly(
    *,
    lat: float = SCHIPLUIDEN_LAT,
    lon: float = SCHIPLUIDEN_LON,
    past_days: int = 14,
    forecast_days: int = 2,
) -> list[tuple[datetime, float]]:
    """Fetch hourly shortwave_radiation (W/m2) covering ``past_days`` history and ``forecast_days`` ahead.

    A single call to Open-Meteo's ``past_days``/``forecast_days`` parameters serves both the
    daily PV calibration (needs recent history) and the rolling planner (needs the forecast) —
    callers slice the returned series by timestamp relative to ``now``.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "shortwave_radiation",
        "timezone": "Europe/Amsterdam",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    times = data.get("hourly", {}).get("time", [])
    values = data.get("hourly", {}).get("shortwave_radiation", [])
    points: list[tuple[datetime, float]] = []
    for t, v in zip(times, values):
        ts = datetime.fromisoformat(t)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=AMSTERDAM)
        points.append((ts, float(v) if v is not None else 0.0))
    return points


def interpolate_ghi(points: list[tuple[datetime, float]], moment: datetime) -> float:
    """Linearly interpolate hourly GHI ``points`` to an arbitrary ``moment``."""
    if not points:
        return 0.0
    if moment <= points[0][0]:
        return points[0][1]
    if moment >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= moment <= t1:
            span = (t1 - t0).total_seconds()
            if span <= 0:
                return v0
            fraction = (moment - t0).total_seconds() / span
            return v0 + (v1 - v0) * fraction
    return points[-1][1]


async def fetch_sunset(
    target_date: date,
    *,
    lat: float = SCHIPLUIDEN_LAT,
    lon: float = SCHIPLUIDEN_LON,
) -> datetime:
    """Fetch the local sunset moment for ``target_date``. Raises on any failure; callers fall back."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "sunset",
        "timezone": "Europe/Amsterdam",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    values = data.get("daily", {}).get("sunset", [])
    if not values:
        raise RuntimeError("Open-Meteo returned no sunset value")
    parsed = datetime.fromisoformat(values[0])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=AMSTERDAM)
    return parsed


def fallback_sunset(target_date: date) -> datetime:
    return datetime.combine(target_date, datetime.min.time(), AMSTERDAM).replace(hour=FALLBACK_SUNSET_LOCAL_HOUR)


def calibrate_pv_factor(actual_pv_wh_total: float, ghi_wh_per_m2_total: float, prev_factor: float) -> float:
    """Self-learning PV calibration factor per spec 3.3: clamp(actual/ghi, 0.5x, 2x) of the previous factor."""
    if ghi_wh_per_m2_total <= 0:
        return prev_factor
    factor = actual_pv_wh_total / ghi_wh_per_m2_total
    return max(0.5 * prev_factor, min(2.0 * prev_factor, factor))
