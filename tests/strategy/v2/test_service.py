from minyad.strategy.v2.setpoint_log import build_setpoint_log_insert


def test_setpoint_log_insert_includes_battery_power_when_column_exists():
    sql = build_setpoint_log_insert(
        {
            "setpoint_w",
            "battery_soc_at_time",
            "grid_power_at_time",
            "battery_power_at_time",
        }
    )
    assert "setpoint_w" in sql
    assert "battery_power_at_time" in sql
    assert ":battery_power" in sql


def test_setpoint_log_insert_supports_legacy_schema_without_battery_power():
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
