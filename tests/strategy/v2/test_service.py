from datetime import datetime, timedelta, timezone

from minyad.strategy.v2.reasons import adjusted_decision_log_due, adjustment_reason_suffix
from minyad.strategy.v2.setpoint_log import build_setpoint_log_insert


def test_setpoint_log_insert_includes_battery_power_when_column_exists():
    sql = build_setpoint_log_insert(
        {
            "setpoint_w",
            "battery_soc_at_time",
            "grid_power_at_time",
            "battery_power_at_time",
            "setpoint_delta",
            "trigger_reason",
            "ack_received",
        }
    )
    assert "setpoint_w" in sql
    assert "battery_power_at_time" in sql
    assert ":battery_power" in sql
    assert "setpoint_delta" in sql
    assert "trigger_reason" in sql
    assert "ack_received" in sql


def test_setpoint_log_insert_supports_legacy_schema_without_newer_columns():
    sql = build_setpoint_log_insert(
        {
            "charge_rate_w",
            "battery_soc_at_time",
            "grid_power_at_time",
        }
    )
    assert "charge_rate_w" in sql
    assert "battery_power_at_time" not in sql
    assert ":battery_power" not in sql
    assert "setpoint_delta" not in sql
    assert "trigger_reason" not in sql
    assert "ack_received" not in sql


def test_adjustment_reason_suffix_names_guard_and_override():
    assert adjustment_reason_suffix("override: force_idle", "guard: bridge stale (61s > 60s)") == (
        "; override: force_idle; guard: bridge stale (61s > 60s)"
    )


def test_adjustment_reason_suffix_keeps_legacy_fallback():
    assert adjustment_reason_suffix(None, None) == "; guard/override adjusted setpoint"


def test_adjusted_decision_log_due_when_unchanged_suppression_persists():
    now = datetime(2026, 6, 27, 23, 54, tzinfo=timezone.utc)
    last = now - timedelta(seconds=300)
    assert adjusted_decision_log_due(
        adjusted=True,
        setpoint_changed=False,
        now=now,
        last_adjustment_log_at=last,
        interval_seconds=300,
    )


def test_adjusted_decision_log_not_due_before_interval():
    now = datetime(2026, 6, 27, 23, 54, tzinfo=timezone.utc)
    last = now - timedelta(seconds=299)
    assert not adjusted_decision_log_due(
        adjusted=True,
        setpoint_changed=False,
        now=now,
        last_adjustment_log_at=last,
        interval_seconds=300,
    )
