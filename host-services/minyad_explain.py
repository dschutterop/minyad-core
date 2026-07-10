#!/usr/bin/env python3
"""Explain Minyad battery charge/discharge decisions from PostgreSQL.

Standalone host-side CLI intended to run next to goodwe_bridge.py and
 dsmr_bridge.py. It only reads PostgreSQL; no writes are performed.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_SERVICES_DIR = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(HOST_SERVICES_DIR / ".env", override=True)

LOCAL_TZ = ZoneInfo(os.getenv("MINYAD_TZ", "Europe/Amsterdam"))
NO_DECISIONS_MESSAGE = "no decisions in this range"
CONTROL_MAIN = REPO_ROOT / "control" / "main.py"
HYSTERESIS = REPO_ROOT / "control" / "hysteresis.py"
STRATEGY = REPO_ROOT / "minyad" / "strategy" / "charge_controller.py"

SETTING_KEYS = (
    "battery.start_w",
    "battery.stop_w",
    "battery.discharge_start_w",
    "battery.discharge_stop_w",
    "battery.start_duration",
    "battery.stop_duration",
    "battery.cooldown",
    "battery.max_charge_w",
    "battery.max_discharge_w",
    "battery.soc_floor",
    "battery.soc_ceiling",
    "strategy.grid_target_w",
)

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    label: str


def parse_window(value: str, now: datetime | None = None) -> Window:
    now = now or datetime.now(LOCAL_TZ)
    value = value.strip().lower()
    if value == "day":
        start = datetime.combine(now.date(), time.min, LOCAL_TZ)
        return Window(start, now, "today")
    if value == "week":
        start_date = now.date() - timedelta(days=now.weekday())
        return Window(datetime.combine(start_date, time.min, LOCAL_TZ), now, "this week")
    if value == "month":
        return Window(datetime(now.year, now.month, 1, tzinfo=LOCAL_TZ), now, "this month")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        d = date.fromisoformat(value)
        start = datetime.combine(d, time.min, LOCAL_TZ)
        return Window(start, start + timedelta(days=1), value)
    match = re.fullmatch(r"(\d{2}:\d{2})-(\d{2}:\d{2})", value)
    if match:
        start_t = time.fromisoformat(match.group(1))
        end_t = time.fromisoformat(match.group(2))
        start = datetime.combine(now.date(), start_t, LOCAL_TZ)
        end = datetime.combine(now.date(), end_t, LOCAL_TZ)
        if end <= start:
            end += timedelta(days=1)
        return Window(start, end, value)
    raise SystemExit(f"Unsupported --range {value!r}; use day, week, month, YYYY-MM-DD, or HH:MM-HH:MM")


def db_url() -> str:
    url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DB_URL or DATABASE_URL is required")
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url.removeprefix("postgresql+asyncpg://")
    return url


def connect():
    conn = psycopg2.connect(db_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def load_settings(cur) -> dict[str, str]:
    cur.execute("select key, value from settings where encrypted = false and key = any(%s)", (list(SETTING_KEYS),))
    return {r["key"]: r["value"] for r in cur.fetchall()}


def source_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for path in (CONTROL_MAIN, HYSTERESIS, STRATEGY):
        try:
            tree = ast.parse(path.read_text())
        except FileNotFoundError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    defaults[node.targets[0].id] = ast.literal_eval(node.value)
                except Exception:
                    pass
    return defaults


def get_columns(cur, table: str) -> set[str]:
    cur.execute("select column_name from information_schema.columns where table_name=%s", (table,))
    return {r["column_name"] for r in cur.fetchall()}


def load_decisions(cur, start: datetime, end: datetime) -> list[dict[str, Any]]:
    cols = get_columns(cur, "setpoint_log")
    setpoint_col = "setpoint_w" if "setpoint_w" in cols else "charge_rate_w"
    load_col = "apparent_load_at_time" if "apparent_load_at_time" in cols else "home_load_at_time"
    cur.execute(f"""
        select id, timestamp, source, soc_floor, soc_ceiling, {setpoint_col} as setpoint_w,
               discharge_allowed, battery_soc_at_time, grid_power_at_time, battery_power_at_time,
               {load_col} as apparent_load_at_time, setpoint_delta, trigger_reason,
               ack_received, ack_latency_ms
          from setpoint_log
         where timestamp >= %s and timestamp < %s
         order by timestamp asc
    """, (start.astimezone(timezone.utc), end.astimezone(timezone.utc)))
    rows = cur.fetchall()
    prev = None
    out = []
    for row in rows:
        sp = int(row["setpoint_w"] or 0)
        if prev is None or sp != prev:
            row["old_setpoint_w"] = prev
            out.append(row)
        prev = sp
    return out


def nearest(cur, table: str, ts: datetime, source: str | None = None) -> dict[str, Any] | None:
    source_clause = "and source = %s" if source else ""
    params: list[Any] = [ts, ts]
    if source:
        params.append(source)
    cur.execute(f"""
        select * from {table}
         where timestamp between %s - interval '10 minutes' and %s + interval '10 minutes' {source_clause}
         order by abs(extract(epoch from (timestamp - %s))) asc limit 1
    """, (*params, ts))
    return cur.fetchone()


def forecast_remaining_kwh(cur, ts: datetime) -> float | None:
    cols = get_columns(cur, "solar_forecast_points")
    tcol = "forecast_time" if "forecast_time" in cols else "timestamp"
    wcol = "estimated_w" if "estimated_w" in cols else "power_w"
    local_end = ts.astimezone(LOCAL_TZ).replace(hour=23, minute=59, second=59, microsecond=0).astimezone(timezone.utc)
    cur.execute(f"select coalesce(sum({wcol}),0) as wh from solar_forecast_points where {tcol} >= %s and {tcol} <= %s", (ts, local_end))
    # Forecast points are hourly in current forecast service; convert W samples to rough kWh.
    val = cur.fetchone()["wh"]
    return float(val) / 1000 if val is not None else None


def direction(sp: int) -> tuple[str, int]:
    if sp < 0:
        return "Charge", abs(sp)
    if sp > 0:
        return "Discharge", sp
    return "Idle", 0


def _resolve_grid_power(cur, row: dict[str, Any], ts: datetime) -> float | None:
    grid = row.get("grid_power_at_time")
    if grid is not None:
        return grid
    gp = nearest(cur, "power_curve_points", ts, "grid")
    return gp and (gp.get("net_w") if "net_w" in gp else gp.get("power_w"))

def _explain_line_parts(row: dict[str, Any], remaining: float | None, grid: float | None) -> list[str]:
    parts = [f"SoC {row['battery_soc_at_time']:.0f}%" if row.get("battery_soc_at_time") is not None else "SoC unknown"]
    if remaining is not None:
        parts.append(f"solar forecast +{remaining:.1f}kWh remaining")
    if grid is not None:
        if grid < 0:
            parts.append(f"grid export {abs(grid)/1000:.1f}kW idle")
        elif grid > 0:
            parts.append(f"grid import {grid/1000:.1f}kW")
        else:
            parts.append("grid balanced")
    return parts

def explain_line(cur, row: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    ts = row["timestamp"]
    d, watts = direction(int(row["setpoint_w"] or 0))
    grid = _resolve_grid_power(cur, row, ts)
    remaining = forecast_remaining_kwh(cur, ts)
    solar_actual = nearest(cur, "power_curve_points", ts, "solar")
    solar_forecast = nearest(cur, "solar_forecast_points", ts)
    actual_solar_w = solar_actual and (solar_actual.get("power_w") or solar_actual.get("net_w"))
    forecast_solar_w = solar_forecast and (solar_forecast.get("estimated_w") or solar_forecast.get("power_w"))
    parts = _explain_line_parts(row, remaining, grid)
    text = f"{ts.astimezone(LOCAL_TZ):%H:%M} — {d} @ {watts}W: " + ", ".join(parts) + "."
    if verbose:
        text += f" reason: {row.get('trigger_reason')}; old→new {row.get('old_setpoint_w')}→{row.get('setpoint_w')}W; floor/ceiling {row.get('soc_floor')}/{row.get('soc_ceiling')}%; solar forecast/actual {forecast_solar_w}/{actual_solar_w}W."
    return {"timestamp": ts.isoformat(), "old_setpoint_w": row.get("old_setpoint_w"), "setpoint_w": row.get("setpoint_w"), "direction": d.lower(), "watts": watts, "soc": row.get("battery_soc_at_time"), "grid_power_w": grid, "solar_forecast_w": forecast_solar_w, "solar_actual_w": actual_solar_w, "solar_forecast_remaining_kwh": remaining, "reason": row.get("trigger_reason"), "text": text}


def summary(rows: list[dict[str, Any]], end: datetime) -> dict[str, Any]:
    cycles = {"charge": 0, "discharge": 0, "idle": 0}
    seconds = {"charge": 0.0, "discharge": 0.0, "idle": 0.0}
    socs = [float(r["battery_soc_at_time"]) for r in rows if r.get("battery_soc_at_time") is not None]
    avoided_wh = 0.0
    for i, r in enumerate(rows):
        mode = direction(int(r["setpoint_w"] or 0))[0].lower()
        cycles[mode] += 1
        nxt = rows[i + 1]["timestamp"] if i + 1 < len(rows) else end
        dur = max(0.0, (nxt - r["timestamp"]).total_seconds())
        seconds[mode] += dur
        if mode == "discharge":
            avoided_wh += int(r["setpoint_w"] or 0) * dur / 3600
    return {"cycle_counts": cycles, "time_in_mode_seconds": seconds, "avg_soc_swing_pct": (max(socs)-min(socs) if socs else None), "estimated_grid_import_avoided_kwh": avoided_wh/1000}


def thresholds(settings: dict[str, str]) -> dict[str, Any]:
    d = source_defaults()
    def val(key: str, default_name: str, fallback: Any) -> Any:
        return settings.get(key, d.get(default_name, fallback))
    return {
        "start_charge_when_surplus_w_gte": int(val("battery.start_w", "", 500)),
        "stop_charge_when_surplus_w_lt": int(val("battery.stop_w", "", 150)),
        "start_discharge_when_surplus_w_lte": int(val("battery.discharge_start_w", "", -300)),
        "stop_discharge_when_surplus_w_gt": int(val("battery.discharge_stop_w", "", -100)),
        "start_duration_seconds": int(val("battery.start_duration", "", 180)),
        "stop_duration_seconds": int(val("battery.stop_duration", "", 300)),
        "cooldown_seconds": int(val("battery.cooldown", "", 600)),
        "soc_floor_pct": int(val("battery.soc_floor", "SOC_FLOOR_DEFAULT", 20)),
        "soc_ceiling_pct": int(val("battery.soc_ceiling", "SOC_CEILING_DEFAULT", 90)),
        "max_charge_w": int(val("battery.max_charge_w", "DEFAULT_MAX_CHARGE_W", 1440)),
        "max_discharge_w": int(val("battery.max_discharge_w", "DEFAULT_MAX_DISCHARGE_W", 5000)),
        "grid_target_w": int(float(val("strategy.grid_target_w", "", 0))),
        "logic_sources": [str(CONTROL_MAIN), str(HYSTERESIS), str(STRATEGY)],
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Explain Minyad charge/discharge setpoint changes")
    p.add_argument("--range", dest="range_", help="day, week, month, YYYY-MM-DD, or HH:MM-HH:MM")
    p.add_argument("--why", action="store_true", help="deep dive on most recent decision")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--format", choices=("json", "table", "text"), default="text")
    args = p.parse_args()
    if not args.why and not args.range_:
        p.error("--range is required unless --why is used")
    return args

def _resolve_window(cur, args: argparse.Namespace) -> Window | None:
    if not args.why:
        return parse_window(args.range_)
    cur.execute("select min(timestamp) as first, max(timestamp) as last from setpoint_log")
    bounds = cur.fetchone()
    if not bounds or bounds["last"] is None:
        return None
    return Window(bounds["last"] - timedelta(seconds=1), bounds["last"] + timedelta(seconds=1), "most recent")

def _build_payload(args: argparse.Namespace, rows: list[dict[str, Any]], explained: list[dict[str, Any]], win: Window, settings: dict[str, str]) -> Any:
    if args.summary:
        return summary(rows, win.end.astimezone(timezone.utc))
    if args.why:
        return explained[-1] | {"thresholds_and_weights": thresholds(settings)}
    return explained

def _print_payload(args: argparse.Namespace, payload: Any, explained: list[dict[str, Any]]) -> None:
    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif args.format == "table":
        print("TIME                 OLD→NEW W  MODE       SOC   GRID W  EXPLANATION")
        for e in explained:
            print(f"{e['timestamp'][:19]:19} {str(e['old_setpoint_w']):>4}→{e['setpoint_w']:<5} {e['direction']:<10} {str(e['soc']):>5} {str(e['grid_power_w']):>7}  {e['text']}")
    elif isinstance(payload, dict):
        print(json.dumps(payload, indent=2, default=str) if args.summary else payload["text"] + "\n" + json.dumps(payload["thresholds_and_weights"], indent=2))
    else:
        for e in explained:
            print(e["text"])

def main() -> None:
    args = _parse_args()
    with connect() as conn, conn.cursor() as cur:
        settings = load_settings(cur)
        win = _resolve_window(cur, args)
        if win is None:
            print(NO_DECISIONS_MESSAGE)
            return
        rows = load_decisions(cur, win.start, win.end)
        if not rows:
            print(json.dumps({"message": NO_DECISIONS_MESSAGE, "range": win.label}) if args.format == "json" else NO_DECISIONS_MESSAGE)
            return
        explained = [explain_line(cur, r, args.verbose or args.why) for r in rows]
        payload = _build_payload(args, rows, explained, win, settings)
        _print_payload(args, payload, explained)

if __name__ == "__main__":
    main()
