from __future__ import annotations

from datetime import datetime, timezone
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import serialize_agent_decision


def test_serialize_agent_decision_formats_timestamp_and_json_snapshot() -> None:
    created_at = datetime(2026, 6, 24, 12, 30, tzinfo=timezone.utc)

    result = serialize_agent_decision(
        {
            "id": 7,
            "created_at": created_at,
            "action_taken": "charge",
            "setpoint_w": 1200,
            "reasoning": "Solar surplus is expected.",
            "confidence": "high",
            "input_snapshot": '{"solar_w": 2400}',
            "dry_run": False,
            "model": "claude-sonnet-4-6",
        }
    )

    assert result["created_at"] == "2026-06-24T12:30:00+00:00"
    assert result["input_snapshot"] == {"solar_w": 2400}
