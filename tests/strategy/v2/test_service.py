from minyad.strategy.v2.reasons import adjustment_reason_suffix
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
