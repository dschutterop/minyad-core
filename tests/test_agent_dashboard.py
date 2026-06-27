from __future__ import annotations

from datetime import datetime, timezone
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import serialize_agent_decision, serialize_control_decision, setpoint_log_select_list


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


def test_serialize_control_decision_labels_strategy_v2_signs() -> None:
    result = serialize_control_decision(
        {
            "timestamp": datetime(2026, 6, 27, 12, 30, tzinfo=timezone.utc),
            "source": "strategy_v2",
            "setpoint_w": -560,
            "discharge_allowed": True,
        }
    )

    assert result["timestamp"] == "2026-06-27T12:30:00+00:00"
    assert result["action"] == "discharge"


def test_serialize_control_decision_labels_legacy_signs() -> None:
    result = serialize_control_decision(
        {
            "timestamp": datetime(2026, 6, 27, 12, 30, tzinfo=timezone.utc),
            "source": "strategy",
            "setpoint_w": -560,
            "discharge_allowed": False,
        }
    )

    assert result["action"] == "charge"


def test_setpoint_log_select_list_supports_legacy_column_names() -> None:
    select_list = setpoint_log_select_list({"charge_rate_w", "home_load_at_time"})

    assert "charge_rate_w as setpoint_w" in select_list
    assert "home_load_at_time as apparent_load_at_time" in select_list
