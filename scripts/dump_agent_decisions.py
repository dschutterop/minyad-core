#!/usr/bin/env python3
"""Print recent Minyad operator-agent decisions for dry-run review."""

from __future__ import annotations

import json
import os
from datetime import timezone

import psycopg


def main() -> None:
    limit = int(os.getenv("LIMIT", "25"))
    db_url = os.environ["DB_URL"]
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, created_at, action_taken, setpoint_w, confidence, dry_run, model, reasoning, input_snapshot
                from agent_decisions
                order by created_at desc
                limit %s
                """,
                (limit,),
            )
            for row in cur.fetchall():
                decision_id, created_at, action, setpoint_w, confidence, dry_run, model, reasoning, snapshot = row
                print(f"#{decision_id} {created_at.astimezone(timezone.utc).isoformat()} dry_run={dry_run} model={model}")
                print(f"  action={action} setpoint_w={setpoint_w} confidence={confidence}")
                print(f"  reasoning={reasoning}")
                state = snapshot.get("state", {}) if isinstance(snapshot, dict) else {}
                battery = state.get("battery", {}) if isinstance(state, dict) else {}
                grid = state.get("grid", {}) if isinstance(state, dict) else {}
                household = state.get("household", {}) if isinstance(state, dict) else {}
                print(f"  snapshot soc={battery.get('soc')} grid_net={grid.get('grid_net_power_w')} household={household.get('power_w')}")
                print(json.dumps(snapshot, indent=2, default=str)[:1200])
                print()


if __name__ == "__main__":
    main()
