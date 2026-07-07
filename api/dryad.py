"""Read-only aggregation helpers for Dryad."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


DRYAD_CACHE_SECONDS = 30
DEFAULT_IMPORT_PRICE_PENALTY_PCT = 30.0


@dataclass(frozen=True)
class SourceInfo:
    source: str
    age_seconds: int | None
    stale: bool

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "age_seconds": self.age_seconds, "stale": self.stale}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value: Any, now: datetime) -> int | None:
    parsed = parse_dt(value)
    if parsed is None:
        return None
    return max(0, round((now - parsed).total_seconds()))


def source_info(source: str, timestamp: Any, now: datetime, max_age_seconds: int | None) -> dict[str, Any]:
    age = age_seconds(timestamp, now)
    stale = age is None or (max_age_seconds is not None and age > max_age_seconds)
    return SourceInfo(source, age, stale).as_dict()


def numeric(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def soc_fraction(mqtt_status: dict[str, Any]) -> float | None:
    soc_pct = numeric(mqtt_status.get("soc"))
    if soc_pct is None:
        return None
    return clamp01(soc_pct / 100.0)


def compute_autarky(rows: list[dict[str, Any]], *, bucket_seconds: int = 60) -> float | None:
    by_ts: dict[Any, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_ts.setdefault(row["ts"], {})[row["source"]] = row

    import_wh = 0.0
    total_consumption_wh = 0.0
    hours = bucket_seconds / 3600.0
    for sources in by_ts.values():
        grid = sources.get("grid", {})
        household = sources.get("household")
        grid_import_w = max(0.0, numeric(grid.get("delivered_w")) or numeric(grid.get("net_w")) or 0.0)
        grid_export_w = max(0.0, numeric(grid.get("returned_w")) or -(numeric(grid.get("net_w")) or 0.0))
        solar_w = max(0.0, numeric(sources.get("solar", {}).get("power_w")) or 0.0)
        battery_w = numeric(sources.get("battery", {}).get("power_w")) or 0.0
        battery_discharge_w = max(0.0, battery_w)
        battery_charge_w = max(0.0, -battery_w)
        if household is not None:
            total_w = max(0.0, numeric(household.get("power_w")) or 0.0)
        else:
            total_w = max(0.0, grid_import_w + solar_w - grid_export_w - battery_charge_w + battery_discharge_w)
        import_wh += grid_import_w * hours
        total_consumption_wh += total_w * hours
    if total_consumption_wh <= 0:
        return None
    return clamp01(1.0 - (import_wh / total_consumption_wh))


def planned_soc_pct(plan_payload: dict[str, Any], now: datetime) -> float | None:
    try:
        slot_seconds = int(plan_payload["slot_seconds"])
        valid_from = parse_dt(plan_payload["valid_from"]) or parse_dt(plan_payload.get("generated_at"))
        prev_soc = float(plan_payload["soc_start_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if valid_from is None:
        return None
    if now <= valid_from:
        return prev_soc
    prev_t = valid_from
    slots = plan_payload.get("slots") or []
    for slot in slots:
        slot_start = parse_dt(slot.get("start"))
        if slot_start is None:
            continue
        slot_end = slot_start + timedelta(seconds=slot_seconds)
        try:
            target = float(slot.get("soc_target_pct", prev_soc))
        except (TypeError, ValueError):
            target = prev_soc
        if now <= slot_end:
            span = max(1.0, (slot_end - prev_t).total_seconds())
            fraction = (now - prev_t).total_seconds() / span
            return prev_soc + ((target - prev_soc) * fraction)
        prev_soc = target
        prev_t = slot_end
    return prev_soc if slots else None


def compute_trajectory_deviation(actual_soc_fraction: float | None, plan_payload: dict[str, Any] | None, max_deviation_pct: float, now: datetime) -> float | None:
    if actual_soc_fraction is None or plan_payload is None or max_deviation_pct <= 0:
        return None
    planned_pct = planned_soc_pct(plan_payload, now)
    if planned_pct is None:
        return None
    actual_pct = actual_soc_fraction * 100.0
    return clamp01(abs(actual_pct - planned_pct) / max_deviation_pct)


def compute_dispatch_hitrate(rows: list[dict[str, Any]]) -> float:
    planned = len(rows)
    if planned == 0:
        return 1.0
    succeeded = sum(1 for row in rows if bool(row.get("ack_received")))
    return clamp01(succeeded / planned)


def price_points_by_hour(prices: list[dict[str, Any]]) -> dict[datetime, float]:
    by_hour: dict[datetime, float] = {}
    for point in prices:
        starts_at = parse_dt(point.get("starts_at"))
        price = numeric(point.get("price_eur_kwh"))
        if starts_at is None or price is None:
            continue
        by_hour[starts_at.replace(minute=0, second=0, microsecond=0)] = price
    return by_hour


def compute_import_price_penalty(import_rows: list[dict[str, Any]], prices: list[dict[str, Any]], *, threshold_pct: float = DEFAULT_IMPORT_PRICE_PENALTY_PCT) -> float | None:
    price_by_hour = price_points_by_hour(prices)
    if not price_by_hour:
        return None
    total_import_kwh = 0.0
    penalty_import_kwh = 0.0
    threshold_factor = 1.0 + (threshold_pct / 100.0)
    for row in import_rows:
        hour = parse_dt(row.get("ts"))
        if hour is None:
            continue
        hour = hour.replace(minute=0, second=0, microsecond=0)
        import_w = max(0.0, numeric(row.get("delivered_w")) or numeric(row.get("power_w")) or 0.0)
        import_kwh = import_w / 1000.0
        if import_kwh <= 0:
            continue
        current_price = price_by_hour.get(hour)
        future_prices = [
            price
            for starts_at, price in price_by_hour.items()
            if hour <= starts_at < hour + timedelta(hours=6)
        ]
        if current_price is None or not future_prices:
            continue
        total_import_kwh += import_kwh
        cheapest_future = min(future_prices)
        if current_price >= cheapest_future * threshold_factor:
            severity = 1.0 if current_price <= 0 else clamp01((current_price - (cheapest_future * threshold_factor)) / current_price)
            penalty_import_kwh += import_kwh * severity
    if total_import_kwh <= 0:
        return 0.0
    return clamp01(penalty_import_kwh / total_import_kwh)


def history_rows_to_daily(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        generated_wh = numeric(row.get("generated_wh"))
        output.append({
            "date": row["day"].isoformat() if hasattr(row["day"], "isoformat") else str(row["day"]),
            "solar_kwh": round((generated_wh or 0.0) / 1000.0, 3),
        })
    return output


async def load_dryad_inputs(session: AsyncSession, now: datetime) -> dict[str, Any]:
    since_60m = now - timedelta(minutes=60)
    since_24h = now - timedelta(hours=24)
    curve_rows = (await session.execute(text("""
        select bucket_start as ts, source, avg(power_w) as power_w,
               avg(delivered_w) as delivered_w, avg(returned_w) as returned_w, avg(net_w) as net_w
        from power_curve_points
        where bucket_start >= :since_60m
          and source in ('grid', 'solar', 'battery', 'household')
        group by bucket_start, source
        order by bucket_start
    """), {"since_60m": since_60m})).mappings().all()
    latest_curve_ts = (await session.execute(text("""
        select max(bucket_start) from power_curve_points
        where source in ('grid', 'solar', 'battery', 'household')
    """))).scalar_one_or_none()
    plan_row = (await session.execute(text("""
        select generated_at, payload, solver_status
        from slot_plans
        where solver_status != 'FALLBACK'
        order by generated_at desc
        limit 1
    """))).mappings().first()
    setpoint_columns = set((await session.execute(text("""
        select column_name
        from information_schema.columns
        where table_name = 'setpoint_log'
    """))).scalars().all())
    setpoint_column = "setpoint_w" if "setpoint_w" in setpoint_columns else "charge_rate_w"
    setpoint_sql = f"""
        select timestamp, ack_received
        from setpoint_log
        where timestamp >= :since_24h
          and source in ('strategy_v3', 'strategy_v2', 'kairos', 'vesper')
          and coalesce({setpoint_column}, 0) != 0
    """
    setpoint_rows = (await session.execute(text(setpoint_sql), {"since_24h": since_24h})).mappings().all()
    latest_setpoint_ts = (await session.execute(text("select max(timestamp) from setpoint_log"))).scalar_one_or_none()
    import_rows = (await session.execute(text("""
        select bucket_start as ts, avg(coalesce(delivered_w, greatest(coalesce(net_w, power_w), 0))) as delivered_w
        from power_curve_rollups
        where granularity_seconds = 3600
          and source = 'grid'
          and bucket_start >= :since_24h
        group by bucket_start
        order by bucket_start
    """), {"since_24h": since_24h})).mappings().all()
    settings_rows = (await session.execute(text("""
        select key, value from settings
        where key in ('strategy3.traj_band_pct', 'dryad.import_price_penalty_pct',
                      'battery.inverter_poll_interval_s', 'battery.goodwe_poll_interval_grace_s')
    """))).mappings().all()
    return {
        "curve_rows": [dict(row) for row in curve_rows],
        "latest_curve_ts": latest_curve_ts,
        "plan_row": dict(plan_row) if plan_row else None,
        "setpoint_rows": [dict(row) for row in setpoint_rows],
        "latest_setpoint_ts": latest_setpoint_ts,
        "import_rows": [dict(row) for row in import_rows],
        "settings": {row["key"]: row["value"] for row in settings_rows},
    }


def build_dryad_payload(
    *,
    now: datetime,
    mqtt_status: dict[str, Any],
    inputs: dict[str, Any],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = inputs.get("settings", {})
    bridge_stale_seconds = int(float(settings.get("battery.inverter_poll_interval_s", 120))) + int(float(settings.get("battery.goodwe_poll_interval_grace_s", 60)))
    traj_band_pct = float(settings.get("strategy3.traj_band_pct", 8.0))
    penalty_threshold_pct = float(settings.get("dryad.import_price_penalty_pct", DEFAULT_IMPORT_PRICE_PENALTY_PCT))
    soc_age = age_seconds(mqtt_status.get("bridge_last_seen"), now)
    raw_soc_value = soc_fraction(mqtt_status)
    soc_stale = raw_soc_value is None or soc_age is None or soc_age > bridge_stale_seconds
    soc_value = None if soc_stale else raw_soc_value
    plan_row = inputs.get("plan_row")
    plan_payload = plan_row.get("payload") if plan_row else None
    plan_generated_at = plan_row.get("generated_at") if plan_row else None
    autarky = compute_autarky(inputs.get("curve_rows", []))
    trajectory = compute_trajectory_deviation(soc_value, plan_payload, traj_band_pct, now)
    dispatch_hitrate = compute_dispatch_hitrate(inputs.get("setpoint_rows", []))
    import_price_penalty = compute_import_price_penalty(inputs.get("import_rows", []), prices, threshold_pct=penalty_threshold_pct)
    curve_info = source_info("power_curve_points", inputs.get("latest_curve_ts"), now, 180)
    plan_info = source_info("slot_plans", plan_generated_at, now, 1800)
    dispatch_info = (
        {"source": "setpoint_log", "age_seconds": age_seconds(inputs.get("latest_setpoint_ts"), now), "stale": False}
        if not inputs.get("setpoint_rows")
        else source_info("setpoint_log", inputs.get("latest_setpoint_ts"), now, 86400)
    )
    price_info = {
        "source": "minyad-trade MQTT day-ahead cache",
        "age_seconds": None,
        "stale": not bool(prices),
    }
    soc_info = {
        "source": "GoodWe/Dyness MQTT minyad/battery/soc",
        "age_seconds": soc_age,
        "stale": soc_stale,
    }
    return {
        "ts": now.isoformat(),
        "autarky": None if curve_info["stale"] else autarky,
        "trajectory_deviation": None if soc_info["stale"] or plan_info["stale"] else trajectory,
        "dispatch_hitrate": None if dispatch_info["stale"] else dispatch_hitrate,
        "import_price_penalty": None if curve_info["stale"] or price_info["stale"] else import_price_penalty,
        "soc": soc_value,
        "sources": {
            "autarky": curve_info,
            "trajectory_deviation": {
                "source": "GoodWe/Dyness MQTT soc + slot_plans + strategy3.traj_band_pct",
                "age_seconds": max([age for age in (soc_age, age_seconds(plan_generated_at, now)) if age is not None], default=None),
                "stale": soc_info["stale"] or plan_info["stale"],
            },
            "dispatch_hitrate": dispatch_info,
            "import_price_penalty": {
                "source": "power_curve_rollups grid import + minyad-trade prices",
                "age_seconds": curve_info["age_seconds"],
                "stale": curve_info["stale"] or price_info["stale"],
            },
            "soc": soc_info,
        },
    }


async def load_dryad_history(session: AsyncSession, *, days: int, timezone_name: str) -> list[dict[str, Any]]:
    rows = (await session.execute(text("""
        select (timezone(:timezone_name, bucket_start))::date as day,
               sum(greatest(power_w, 0) * granularity_seconds / 3600.0) as generated_wh
        from power_curve_rollups
        where source = 'solar'
          and granularity_seconds = 3600
          and bucket_start >= now() - (:days * interval '1 day')
        group by day
        order by day
    """), {"days": days, "timezone_name": timezone_name})).mappings().all()
    return history_rows_to_daily([dict(row) for row in rows])
