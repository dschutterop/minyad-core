import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import coerce_float_status_value, coerce_grid_status, coerce_int_status_value


def test_status_numeric_coercion_keeps_invalid_values():
    assert coerce_int_status_value("power_w", "123") == 123
    assert coerce_int_status_value("power_w", "unknown") == "unknown"
    assert coerce_float_status_value("voltage", "52.5") == 52.5
    assert coerce_float_status_value("voltage", "unavailable") == "unavailable"


def test_grid_status_coercion_does_not_raise_on_invalid_retained_values():
    payload = {
        "grid_delivered_w": "not-a-number",
        "grid_voltage_l1_v": "230.4",
        "soc": "50",
    }

    assert coerce_grid_status(payload) == {
        "grid_delivered_w": "not-a-number",
        "grid_voltage_l1_v": 230.4,
        "soc": "50",
    }
