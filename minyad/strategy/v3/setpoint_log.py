"""Helpers for writing strategy v3 setpoint log rows."""

from __future__ import annotations


def build_setpoint_log_insert(columns: set[str]) -> str:
    setpoint_column = "setpoint_w" if "setpoint_w" in columns else "charge_rate_w"
    insert_columns = [
        "source",
        "soc_floor",
        "soc_ceiling",
        setpoint_column,
        "discharge_allowed",
    ]
    values = [
        "'strategy_v3'",
        ":floor",
        ":ceiling",
        ":setpoint",
        ":discharge_allowed",
    ]
    optional_columns = {
        "battery_soc_at_time": ":soc",
        "grid_power_at_time": ":grid",
        "battery_power_at_time": ":battery_power",
        "setpoint_delta": ":delta",
        "trigger_reason": ":reason",
        "ack_received": "true",
    }
    for column, value in optional_columns.items():
        if column in columns:
            insert_columns.append(column)
            values.append(value)
    return f"""
                    insert into setpoint_log (
                        {", ".join(insert_columns)}
                    ) values (
                        {", ".join(values)}
                    )
                """
