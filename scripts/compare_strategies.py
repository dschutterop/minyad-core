#!/usr/bin/env python3
"""Summarize v2-vs-v3 shadow-mode agreement from strategy_shadow_log.

Prints daily aggregates per spec strategy_v3.md section 11.2: mean |v2-v3| setpoint
disagreement, sign disagreement count, an estimated would-have-exported Wh (what v3's
setpoint would have driven net grid power to, approximating a 1:1 W-for-W response),
and a would-have-hit-floor event count (v3 decisions where the guard's SoC floor hold
fired, read from the logged reason string).
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import psycopg

DAYS = int(os.getenv("DAYS", "7"))


def _fetch_shadow_rows(db_url: str, since: date) -> list[tuple]:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select ts, v2_setpoint_w, v3_setpoint_w, soc, net_grid_w, v3_reason
                from strategy_shadow_log
                where ts >= %s
                order by ts asc
                """,
                (since,),
            )
            return cur.fetchall()


def _summarize_day(day_rows: list[tuple]) -> dict[str, Any]:
    diffs = []
    sign_disagreements = 0
    would_have_exported_wh = 0.0
    would_have_hit_floor = 0
    prev_ts = None
    for ts, v2_w, v3_w, _soc, net_grid_w, v3_reason in day_rows:
        if v2_w is not None:
            diffs.append(abs(v2_w - v3_w))
            if _sign(v2_w) * _sign(v3_w) < 0:
                sign_disagreements += 1
            if prev_ts is not None and net_grid_w is not None:
                hours = (ts - prev_ts).total_seconds() / 3600.0
                counterfactual_grid_w = net_grid_w - (v2_w - v3_w)
                would_have_exported_wh += max(0.0, -counterfactual_grid_w) * hours
        if v3_reason and "SoC floor hold" in v3_reason:
            would_have_hit_floor += 1
        prev_ts = ts
    return {
        "mean_abs_diff": sum(diffs) / len(diffs) if diffs else 0.0,
        "sign_disagreements": sign_disagreements,
        "would_have_exported_wh": would_have_exported_wh,
        "would_have_hit_floor": would_have_hit_floor,
    }


def _print_day_summary(day: date, day_rows: list[tuple]) -> None:
    stats = _summarize_day(day_rows)
    print(f"{day.isoformat()}  ticks={len(day_rows)}")
    print(f"  mean |v2-v3| setpoint diff : {stats['mean_abs_diff']:.1f} W")
    print(f"  sign disagreements         : {stats['sign_disagreements']}")
    print(f"  would-have-exported        : {stats['would_have_exported_wh']:.1f} Wh (estimated)")
    print(f"  would-have-hit-floor events: {stats['would_have_hit_floor']}")
    print()


def main() -> None:
    db_url = os.environ["DB_URL"]
    since = date.today() - timedelta(days=DAYS)
    rows = _fetch_shadow_rows(db_url, since)

    by_day: dict[date, list[tuple]] = defaultdict(list)
    for row in rows:
        by_day[row[0].date()].append(row)

    if not by_day:
        print(f"No strategy_shadow_log rows in the last {DAYS} days.")
        return

    for day in sorted(by_day):
        _print_day_summary(day, by_day[day])


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


if __name__ == "__main__":
    main()
