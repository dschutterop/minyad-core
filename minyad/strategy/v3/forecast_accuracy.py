"""Daily forecast-accuracy job (dashboard_forecast_v1 spec 5.3).

Compares each measured 15-minute slot of a day against the plan *vintage* that was live
T-1h/T-6h/T-24h before that slot, and writes MAE/bias per (curve, horizon) so the dashboard can
show a small "yesterday's forecast was this good" block instead of a self-rewriting rolling plan
that always looks perfect in hindsight.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
HORIZONS: dict[str, timedelta] = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(hours=24)}
CURVES: dict[str, str] = {"pv": "pv_forecast_w", "load": "load_forecast_w", "battery_soc": "soc_target_pct"}


def compute_forecast_accuracy(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """MAE and bias (mean signed error, forecast minus measured) over paired values."""
    if not pairs:
        return {"mae": 0.0, "bias": 0.0, "sample_count": 0}
    errors = [forecast - measured for forecast, measured in pairs]
    return {
        "mae": sum(abs(e) for e in errors) / len(errors),
        "bias": sum(errors) / len(errors),
        "sample_count": len(errors),
    }


def latest_vintage_at_or_before(vintages: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any] | None:
    """Last vintage with generated_at <= cutoff. ``vintages`` must be sorted ascending by generated_at."""
    candidate = None
    for vintage in vintages:
        if vintage["generated_at"] <= cutoff:
            candidate = vintage
        else:
            break
    return candidate


def build_accuracy_pairs(
    measured_by_slot: dict[str, dict[str, float]],
    vintages: list[dict[str, Any]],
    *,
    horizons: dict[str, timedelta] = HORIZONS,
    curves: dict[str, str] = CURVES,
) -> dict[tuple[str, str], list[tuple[float, float]]]:
    """Pair each measured slot's value with the forecast a vintage made for it, per curve/horizon.

    ``measured_by_slot`` maps a slot's ISO start timestamp to ``{"pv": w, "load": w,
    "battery_soc": pct}`` (missing curves for a slot are simply skipped). ``vintages`` are
    ``{"generated_at": datetime, "slots_by_start": {iso: {"pv_forecast_w": ..., ...}}}``, sorted
    ascending by ``generated_at``.
    """
    pairs: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for slot_start_iso, measured in measured_by_slot.items():
        slot_start = datetime.fromisoformat(slot_start_iso)
        for horizon_key, offset in horizons.items():
            vintage = latest_vintage_at_or_before(vintages, slot_start - offset)
            if vintage is None:
                continue
            slot_forecast = vintage["slots_by_start"].get(slot_start_iso)
            if slot_forecast is None:
                continue
            for curve, forecast_key in curves.items():
                if curve not in measured or forecast_key not in slot_forecast:
                    continue
                pairs[(curve, horizon_key)].append((float(slot_forecast[forecast_key]), float(measured[curve])))
    return pairs


async def run_daily_accuracy_job(db_session_factory: Any, for_date: date, *, tz: ZoneInfo = AMSTERDAM) -> None:
    """Compute and persist accuracy for every 15-minute slot of ``for_date`` (local calendar day)."""
    day_start_local = datetime.combine(for_date, datetime.min.time(), tz)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(timezone.utc)
    day_end = day_end_local.astimezone(timezone.utc)
    vintage_window_start = day_start - max(HORIZONS.values()) - timedelta(hours=1)

    async with db_session_factory() as session:
        measured_by_slot = await _load_measured_slots(session, day_start, day_end)
        vintages = await _load_vintages(session, vintage_window_start, day_end)

    if not measured_by_slot:
        return
    pairs = build_accuracy_pairs(measured_by_slot, vintages)

    async with db_session_factory() as session:
        for (curve, horizon_key), curve_pairs in pairs.items():
            stats = compute_forecast_accuracy(curve_pairs)
            await session.execute(
                text(
                    """
                    insert into forecast_accuracy_daily (for_date, curve, horizon, mae, bias, sample_count)
                    values (:for_date, :curve, :horizon, :mae, :bias, :sample_count)
                    on conflict (for_date, curve, horizon) do update set
                      mae = excluded.mae, bias = excluded.bias, sample_count = excluded.sample_count
                    """
                ),
                {
                    "for_date": for_date,
                    "curve": curve,
                    "horizon": horizon_key,
                    "mae": stats["mae"],
                    "bias": stats["bias"],
                    "sample_count": stats["sample_count"],
                },
            )
        await session.execute(text("delete from forecast_accuracy_daily where for_date < :cutoff"), {"cutoff": for_date - timedelta(days=180)})
        await session.commit()


async def _load_measured_slots(session: AsyncSession, day_start: datetime, day_end: datetime) -> dict[str, dict[str, float]]:
    measured: dict[str, dict[str, float]] = defaultdict(dict)

    power_rows = (
        await session.execute(
            text(
                """
                select bucket_start, source, power_w
                from power_curve_rollups
                where granularity_seconds = 900
                  and source in ('solar', 'household')
                  and bucket_start >= :start and bucket_start < :end
                """
            ),
            {"start": day_start, "end": day_end},
        )
    ).all()
    for bucket_start, source, power_w in power_rows:
        if power_w is None:
            continue
        ts = bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc)
        curve = "pv" if source == "solar" else "load"
        measured[ts.isoformat()][curve] = float(power_w)

    soc_rows = (
        await session.execute(
            text(
                """
                select
                  to_timestamp(floor(extract(epoch from timestamp) / 900) * 900) as bucket_start,
                  avg((metadata->>'soc')::real) as soc
                from power_curve_points
                where source = 'battery'
                  and metadata->>'soc' is not null
                  and timestamp >= :start and timestamp < :end
                group by bucket_start
                """
            ),
            {"start": day_start, "end": day_end},
        )
    ).all()
    for bucket_start, soc in soc_rows:
        if soc is None:
            continue
        ts = bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc)
        measured[ts.isoformat()]["battery_soc"] = float(soc)

    return dict(measured)


async def _load_vintages(session: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                select generated_at, payload
                from slot_plans
                where generated_at >= :start and generated_at < :end
                order by generated_at asc
                """
            ),
            {"start": start, "end": end},
        )
    ).all()
    vintages: list[dict[str, Any]] = []
    for generated_at, payload in rows:
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        # Plan slot starts are serialized in local (Amsterdam) offset, while measured bucket_start
        # keys come back from Postgres as UTC — re-key to a common UTC representation so the two
        # sides actually match instead of comparing "+02:00" strings against "+00:00" strings for
        # the same instant.
        slots_by_start = {_normalize_iso_utc(slot["start"]): slot for slot in payload.get("slots", [])}
        vintages.append({"generated_at": generated_at, "slots_by_start": slots_by_start})
    return vintages


def _normalize_iso_utc(iso_timestamp: str) -> str:
    parsed = datetime.fromisoformat(iso_timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
