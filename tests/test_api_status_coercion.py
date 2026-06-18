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


def test_goodwe_voltage_v_topic_maps_to_voltage_status():
    from api.main import MQTT_STATUS_KEYS

    assert MQTT_STATUS_KEYS["minyad/battery/voltage_v"] == "voltage"


def test_cache_complete_with_goodwe_battery_topics_without_optional_legacy_fields():
    from api.main import cached_status_is_incomplete

    payload = {
        "soc": "50",
        "soh": "100",
        "power_w": "0",
        "voltage": "52.1",
        "mode": "idle",
        "bridge_status": "online",
        "bridge_last_seen": "2026-06-18T09:24:03Z",
    }

    assert cached_status_is_incomplete(payload) is False
