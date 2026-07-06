"""Baseline/flex household load split for strategy v3 (dashboard_forecast_v1 spec 4.1).

Vesper's own dispatch (surplus-triggered appliance switching) shows up in the measured household
load. Left in, the load forecast partly learns Vesper's own behaviour and oscillates: a dispatch
raises the profile -> the planner reserves less surplus next time -> less dispatch -> the profile
falls again. This subtracts Vesper's own footprint (fetched from its dispatch ledger endpoint)
before building the profile, so the forecast represents baseline consumption Vesper doesn't
control. Kairos-planned loads are out of scope here (spec 4.1.2) — v1 only nets out Vesper.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from minyad.strategy.v2.consumption_profile import AMSTERDAM, ConsumptionProfile, build_profile_from_rows
from . import forecast_client

LOGGER = logging.getLogger(__name__)
SLOT_SECONDS = 900
DAYPARTS = ("night", "morning", "afternoon", "evening")
MIN_DAYTYPE_DAYS = 5
WEEKEND_LOOKBACK_DAYS = 28
DEFAULT_TEMP_REF_C = 22.0


async def fetch_flex_load_wh(
    vesper_api_url: str,
    api_key: str | None,
    start: datetime,
    end: datetime,
    *,
    timeout: float = 10.0,
) -> dict[datetime, float]:
    """Fetch Vesper's own dispatched Wh per 15-minute slot for ``[start, end)``.

    Returns an empty mapping on any failure (network, auth, bad response) — a Vesper outage
    should degrade to "don't split" rather than break the planner cycle.
    """
    headers = {"X-API-Key": api_key} if api_key else {}
    params = {"start": start.isoformat(), "end": end.isoformat(), "slot_seconds": SLOT_SECONDS}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{vesper_api_url}/api/minyad/dispatch-ledger", params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception:
        LOGGER.warning("Unable to fetch Vesper dispatch ledger; treating flex load as zero", exc_info=True)
        return {}
    result: dict[datetime, float] = {}
    for slot in data.get("slots", []):
        try:
            ts = datetime.fromisoformat(slot["start"])
        except (KeyError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        result[ts.astimezone(timezone.utc)] = float(slot.get("flex_load_wh", 0.0))
    return result


def split_baseline_rows(
    rows: list[tuple[datetime, float]],
    flex_load_wh_by_slot: dict[datetime, float],
    *,
    slot_seconds: int = SLOT_SECONDS,
) -> list[tuple[datetime, float]]:
    """Subtract Vesper's own dispatched load from measured rows, per slot (spec 4.1.3).

    Negative results clip to 0 (measurement noise or double-counting) and are logged in
    aggregate so a persistently-clipping slot is visible rather than silently absorbed.
    """
    slot_hours = slot_seconds / 3600.0
    baseline: list[tuple[datetime, float]] = []
    clipped = 0
    for bucket_start, power_w in rows:
        ts = bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc)
        flex_wh = flex_load_wh_by_slot.get(ts.astimezone(timezone.utc), 0.0)
        flex_w = flex_wh / slot_hours if slot_hours else 0.0
        net_w = power_w - flex_w
        if net_w < 0:
            clipped += 1
            net_w = 0.0
        baseline.append((bucket_start, net_w))
    if clipped:
        total = len(rows) or 1
        LOGGER.info(
            "consumption_profile: clipped %d/%d baseline slots to 0 (%.1f%%) after subtracting Vesper dispatch",
            clipped,
            total,
            100.0 * clipped / total,
        )
    return baseline


def _is_weekend(moment: datetime, tz: ZoneInfo) -> bool:
    return moment.astimezone(tz).weekday() >= 5  # Saturday=5, Sunday=6


def _daypart_of(moment: datetime, tz: ZoneInfo) -> str:
    hour = moment.astimezone(tz).hour
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def split_rows_by_daytype(
    rows: list[tuple[datetime, float]], tz: ZoneInfo, *, min_days: int = MIN_DAYTYPE_DAYS
) -> tuple[list[tuple[datetime, float]], list[tuple[datetime, float]], bool, bool]:
    """Split rows into weekday/weekend, each flagged for whether it has enough distinct
    calendar days to stand on its own (spec 4.2.1/4.2.3 — otherwise the caller should fall
    back to the combined profile for that day-type)."""
    weekday_rows: list[tuple[datetime, float]] = []
    weekend_rows: list[tuple[datetime, float]] = []
    weekday_dates: set[Any] = set()
    weekend_dates: set[Any] = set()
    for bucket_start, power_w in rows:
        local_date = bucket_start.astimezone(tz).date()
        if _is_weekend(bucket_start, tz):
            weekend_rows.append((bucket_start, power_w))
            weekend_dates.add(local_date)
        else:
            weekday_rows.append((bucket_start, power_w))
            weekday_dates.add(local_date)
    return weekday_rows, weekend_rows, len(weekday_dates) >= min_days, len(weekend_dates) >= min_days


def fit_temperature_betas(
    rows: list[tuple[datetime, float]],
    temp_points: list[tuple[datetime, float]],
    profile_for_row: Callable[[datetime], float],
    tz: ZoneInfo,
    *,
    t_ref_c: float = DEFAULT_TEMP_REF_C,
) -> dict[str, float]:
    """Least-squares cooling-response beta (W per degC above ``t_ref_c``) per daypart (spec 4.2.2).

    Fit through the origin (no intercept): the baseline profile already captures average
    behaviour, so beta only needs to explain the *excess* once it gets hot — ``residual =
    actual_w - profile_for_row(ts)`` regressed against ``heat_excess = max(0, temp_c - t_ref_c)``.
    A daypart with no heat-excess samples (Sigma x^2 == 0) gets beta 0 rather than a division by
    zero. The heating-side response (T below a low threshold) is left at beta=0 in v1, per spec.
    """
    sums_xy: dict[str, float] = defaultdict(float)
    sums_xx: dict[str, float] = defaultdict(float)
    for bucket_start, power_w in rows:
        temp_c = forecast_client.interpolate_ghi(temp_points, bucket_start)
        heat_excess = max(0.0, temp_c - t_ref_c)
        if heat_excess <= 0:
            continue
        daypart = _daypart_of(bucket_start, tz)
        residual = power_w - profile_for_row(bucket_start)
        sums_xy[daypart] += heat_excess * residual
        sums_xx[daypart] += heat_excess * heat_excess
    return {daypart: (sums_xy[daypart] / sums_xx[daypart] if sums_xx.get(daypart, 0.0) > 0 else 0.0) for daypart in DAYPARTS}


@dataclass(frozen=True)
class HouseholdLoadProfile:
    """Weekday/weekend-aware consumption profile with an optional temperature correction
    (dashboard_forecast_v1 spec 4.2)."""

    weekday: ConsumptionProfile
    weekend: ConsumptionProfile
    temp_betas: dict[str, float] = field(default_factory=dict)
    t_ref_c: float = DEFAULT_TEMP_REF_C
    tz: ZoneInfo = AMSTERDAM

    def expected_w(self, moment: datetime, temperature_c: float | None = None) -> float:
        profile = self.weekend if _is_weekend(moment, self.tz) else self.weekday
        base = profile.expected_w(moment)
        if temperature_c is None:
            return base
        beta = self.temp_betas.get(_daypart_of(moment, self.tz), 0.0)
        return base + beta * max(0.0, temperature_c - self.t_ref_c)

    @property
    def has_history(self) -> bool:
        return self.weekday.has_history or self.weekend.has_history


async def load_baseline_consumption_profile(
    session_factory: Any,
    *,
    vesper_api_url: str | None,
    vesper_api_key: str | None = None,
    tz: ZoneInfo = AMSTERDAM,
    lookback_days: int = 14,
    fallback_w: float = 300.0,
    now: datetime | None = None,
    temperature_fetcher: Callable[..., Any] | None = None,
) -> HouseholdLoadProfile:
    """Baseline (Vesper-split) household load, weekday/weekend split, with a temperature
    correction (dashboard_forecast_v1 spec 4.1 + 4.2).

    If ``vesper_api_url`` is falsy (not configured), the baseline/flex split is simply skipped —
    it's opt-in via configuration, not a hard dependency on Vesper.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    weekend_start = now - timedelta(days=max(lookback_days, WEEKEND_LOOKBACK_DAYS))
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select bucket_start, power_w
                from power_curve_rollups
                where source = 'household'
                  and granularity_seconds = 900
                  and bucket_start >= :start
                """
            ),
            {"start": weekend_start},
        )
        all_rows = [(row.bucket_start, float(row.power_w)) for row in result if row.power_w is not None]
    rows = [row for row in all_rows if row[0] >= start]

    if vesper_api_url:
        flex_load_wh_by_slot = await fetch_flex_load_wh(vesper_api_url, vesper_api_key, weekend_start, now)
        if flex_load_wh_by_slot:
            all_rows = split_baseline_rows(all_rows, flex_load_wh_by_slot)
            rows = [row for row in all_rows if row[0] >= start]

    combined_profile = build_profile_from_rows(all_rows, tz=tz, fallback_w=fallback_w)
    # Weekday uses the normal lookback window; weekend uses the wider one (spec 4.2.1) since
    # weekends are ~2/7 as frequent and need more calendar days to reach the same sample count.
    weekday_rows, _, weekday_ok, _ = split_rows_by_daytype(rows, tz)
    _, weekend_rows, _, weekend_ok = split_rows_by_daytype(all_rows, tz)

    if weekday_ok:
        weekday_profile = build_profile_from_rows(weekday_rows, tz=tz, fallback_w=fallback_w)
    else:
        LOGGER.info("consumption_profile: fewer than %d weekday-days of history, using combined profile", MIN_DAYTYPE_DAYS)
        weekday_profile = combined_profile

    if weekend_ok:
        weekend_profile = build_profile_from_rows(weekend_rows, tz=tz, fallback_w=fallback_w)
    else:
        LOGGER.info(
            "consumption_profile: fewer than %d weekend-days of history (even over %d days), using combined profile",
            MIN_DAYTYPE_DAYS,
            WEEKEND_LOOKBACK_DAYS,
        )
        weekend_profile = combined_profile

    temp_betas: dict[str, float] = {}
    fetch_temperature = temperature_fetcher or forecast_client.fetch_temperature_hourly
    try:
        temp_points = await fetch_temperature(past_days=max(lookback_days, WEEKEND_LOOKBACK_DAYS), forecast_days=0)
    except Exception:
        LOGGER.warning("Unable to fetch historical temperature; skipping temperature correction", exc_info=True)
        temp_points = []
    if temp_points:
        temp_betas = fit_temperature_betas(
            all_rows,
            temp_points,
            lambda ts: (weekend_profile if _is_weekend(ts, tz) else weekday_profile).expected_w(ts),
            tz,
        )

    return HouseholdLoadProfile(weekday=weekday_profile, weekend=weekend_profile, temp_betas=temp_betas, tz=tz)

    return build_profile_from_rows(rows, tz=tz, fallback_w=fallback_w)
