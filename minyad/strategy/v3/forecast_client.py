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


async def fetch_temperature_hourly(
    *,
    lat: float = SCHIPLUIDEN_LAT,
    lon: float = SCHIPLUIDEN_LON,
    past_days: int = 14,
    forecast_days: int = 2,
) -> list[tuple[datetime, float]]:
    """Fetch hourly temperature_2m (°C), same shape/window as :func:`fetch_ghi_hourly`.

    A separate Open-Meteo call rather than folding into ``fetch_ghi_hourly``'s existing
    ``hourly`` parameter: it keeps that function's well-exercised return contract (and every
    existing caller/test of it) untouched, at the cost of one extra HTTP round trip per plan
    build — a fine trade for a feature that's still fully optional (dashboard_forecast_v1 4.2).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "timezone": "Europe/Amsterdam",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    times = data.get("hourly", {}).get("time", [])
    values = data.get("hourly", {}).get("temperature_2m", [])
    points: list[tuple[datetime, float]] = []
    for t, v in zip(times, values):
        ts = datetime.fromisoformat(t)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=AMSTERDAM)
        points.append((ts, float(v) if v is not None else 0.0))
    return points


async def fetch_cloud_cover_hourly(
    *,
    lat: float = SCHIPLUIDEN_LAT,
    lon: float = SCHIPLUIDEN_LON,
    past_days: int = 14,
    forecast_days: int = 2,
) -> list[tuple[datetime, float]]:
    """Fetch hourly cloud_cover (%), same shape/window as :func:`fetch_ghi_hourly`.

    Used for the PV forecast's P10-P90 uncertainty band (dashboard_forecast_v1 4.4): the same
    GHI-based forecast is far less certain on a partly-cloudy day than a clear or fully overcast
    one, so the empirical error distribution is bucketed by this rather than treated as one blob.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "cloud_cover",
        "timezone": "Europe/Amsterdam",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    times = data.get("hourly", {}).get("time", [])
    values = data.get("hourly", {}).get("cloud_cover", [])
    points: list[tuple[datetime, float]] = []
    for t, v in zip(times, values):
        ts = datetime.fromisoformat(t)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=AMSTERDAM)
        points.append((ts, float(v) if v is not None else 0.0))
    return points


def interpolate_ghi(points: list[tuple[datetime, float]], moment: datetime) -> float:
    """Linearly interpolate hourly GHI ``points`` to an arbitrary ``moment``.

    Generic over any ``(datetime, float)`` hourly series despite the name — also used to
    interpolate hourly temperature and cloud cover (see :func:`fetch_temperature_hourly`,
    :func:`fetch_cloud_cover_hourly`).
    """
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


PV_CALIBRATION_HOURS = 24
PV_CALIBRATION_GHI_THRESHOLD_W_M2 = 50.0
PV_CALIBRATION_MIN_SAMPLES_PER_HOUR = 5


def calibrate_pv_factors(
    samples: list[tuple[int, float, float]],
    prev_factors: list[float],
    *,
    ghi_threshold_w_m2: float = PV_CALIBRATION_GHI_THRESHOLD_W_M2,
    min_samples_per_hour: int = PV_CALIBRATION_MIN_SAMPLES_PER_HOUR,
) -> list[float]:
    """Self-learning per-hour-of-day PV calibration factors (dashboard_forecast_v1 spec 4.3).

    ``samples`` are ``(hour_of_day, actual_w, ghi_w_m2)`` tuples, one per historical measurement.
    Samples at or below ``ghi_threshold_w_m2`` are excluded (dawn/dusk noise: a tiny GHI
    denominator turns small measurement errors into huge ratio swings). For each hour, the
    median ratio is clamped to 0.5x-2x that hour's previous factor, same self-learning bound as
    the old single-factor version. An hour with *some* but fewer than ``min_samples_per_hour``
    samples borrows its immediate neighbours' samples too (spec's "2-hour block" fallback for
    sparse data), rather than switching to a separate coarser schema — simpler to consume as a
    caller always gets back a fixed 24-length vector. An hour with *zero* samples is left at its
    previous factor rather than borrowed: unlike padding out a thin-but-real measurement, pulling
    in a neighbour's data wholesale for an unmeasured hour would let that neighbour's factor
    silently overwrite hours it says nothing about. Finally, a 3-point weighted average (25/50/25)
    smooths adjacent hours to damp noise from low sample counts.
    """
    by_hour: list[list[float]] = [[] for _ in range(PV_CALIBRATION_HOURS)]
    for hour, actual_w, ghi_w_m2 in samples:
        if ghi_w_m2 <= ghi_threshold_w_m2:
            continue
        by_hour[hour % PV_CALIBRATION_HOURS].append(max(0.0, actual_w) / ghi_w_m2)

    raw_factors = list(prev_factors)
    for hour in range(PV_CALIBRATION_HOURS):
        ratios = by_hour[hour]
        if 0 < len(ratios) < min_samples_per_hour:
            prev_hour, next_hour = (hour - 1) % PV_CALIBRATION_HOURS, (hour + 1) % PV_CALIBRATION_HOURS
            ratios = ratios + by_hour[prev_hour] + by_hour[next_hour]
        if not ratios:
            continue
        ratios.sort()
        mid = len(ratios) // 2
        median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2
        raw_factors[hour] = max(0.5 * prev_factors[hour], min(2.0 * prev_factors[hour], median))

    return [
        0.25 * raw_factors[(hour - 1) % PV_CALIBRATION_HOURS]
        + 0.5 * raw_factors[hour]
        + 0.25 * raw_factors[(hour + 1) % PV_CALIBRATION_HOURS]
        for hour in range(PV_CALIBRATION_HOURS)
    ]
