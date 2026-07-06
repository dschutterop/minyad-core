"""P10-P90 PV forecast uncertainty band, keyed by cloud-cover class (dashboard_forecast_v1 spec 4.4).

Built from the same historical window used for per-hour PV calibration: for each measured slot,
compares actual solar production against what the *current* per-hour calibration factor would
have predicted from that slot's GHI (an approximation — a full history of what was forecast at
each past moment isn't kept, so this asks "what would today's calibration say back then" instead),
and buckets the actual/predicted ratio by that slot's cloud-cover class. The empirical 10th/90th
percentile of each class's ratio distribution becomes a multiplier applied to a fresh forecast in
that same class.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import forecast_client

CLOUD_COVER_CLEAR_MAX_PCT = 25.0
CLOUD_COVER_PARTLY_MAX_PCT = 75.0
MIN_SAMPLES_PER_CLASS = 14 * 4  # spec 4.4.4: >= 14 days of history per class


def classify_cloud_cover(cloud_cover_pct: float) -> str:
    if cloud_cover_pct < CLOUD_COVER_CLEAR_MAX_PCT:
        return "clear"
    if cloud_cover_pct < CLOUD_COVER_PARTLY_MAX_PCT:
        return "partly"
    return "cloudy"


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (0-100), matching numpy's default ('linear') method."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def collect_pv_ratio_samples(
    rows: list[tuple[datetime, float]],
    ghi_points: list[tuple[datetime, float]],
    cloud_cover_points: list[tuple[datetime, float]],
    pv_calibration_factors: list[float],
    tz: ZoneInfo,
    *,
    ghi_threshold_w_m2: float = 50.0,
) -> dict[str, list[float]]:
    """actual/predicted PV ratio samples from measured rows, classified by cloud-cover class.

    ``rows`` are ``(bucket_start, actual_w)`` measured PV rollup rows. Slots at/below
    ``ghi_threshold_w_m2`` are excluded — same dawn/dusk noise guard as the calibration fit,
    since a tiny GHI denominator turns small measurement error into a huge ratio swing.
    """
    ratios_by_class: dict[str, list[float]] = {"clear": [], "partly": [], "cloudy": []}
    for bucket_start, actual_w in rows:
        ghi = forecast_client.interpolate_ghi(ghi_points, bucket_start)
        if ghi <= ghi_threshold_w_m2:
            continue
        hour_local = bucket_start.astimezone(tz).hour
        predicted_w = ghi * pv_calibration_factors[hour_local]
        if predicted_w <= 0:
            continue
        cloud_cover_pct = forecast_client.interpolate_ghi(cloud_cover_points, bucket_start)
        cloud_class = classify_cloud_cover(cloud_cover_pct)
        ratios_by_class[cloud_class].append(max(0.0, actual_w) / predicted_w)
    return ratios_by_class


def compute_uncertainty_bands(
    ratios_by_class: dict[str, list[float]],
    *,
    min_samples: int = MIN_SAMPLES_PER_CLASS,
) -> dict[str, dict[str, Any]]:
    """P10/P90 multipliers per cloud class; a class with too few samples is omitted entirely
    (spec 4.4.4: never fabricate a percentile from too little history)."""
    bands: dict[str, dict[str, Any]] = {}
    for cloud_class, ratios in ratios_by_class.items():
        if len(ratios) < min_samples:
            continue
        bands[cloud_class] = {
            "p10_multiplier": percentile(ratios, 10.0),
            "p90_multiplier": percentile(ratios, 90.0),
            "sample_count": len(ratios),
        }
    return bands
