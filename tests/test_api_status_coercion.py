import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import coerce_float_status_value, coerce_grid_status, coerce_int_status_value, parse_status_timestamp


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


def test_grid_status_coercion_converts_solar_power():
    assert coerce_grid_status({"solar_power_w": "412"}) == {"solar_power_w": 412}


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


def test_grid_status_stores_solar_curve_point(monkeypatch):
    import asyncio
    from api import main as api_main

    stored = []

    async def fake_store_power_curve_point(session, source, power_w, **kwargs):
        await asyncio.sleep(0)
        stored.append((source, power_w, kwargs))

    class FakeSession:
        commits = 0

        async def commit(self):
            self.commits += 1

    session = FakeSession()
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: {"solar_power_w": "412"})
    monkeypatch.setattr(api_main, "store_power_curve_point", fake_store_power_curve_point)

    payload = asyncio.run(api_main.grid_status(session))

    assert payload["solar_power_w"] == 412
    assert stored == [("solar", 412, {"timestamp": None, "metadata": {"updated_at": None}})]
    assert session.commits == 1


def test_parse_status_timestamp_accepts_zulu_timestamps():
    parsed = parse_status_timestamp("2026-06-19T12:34:56Z")

    assert parsed.isoformat() == "2026-06-19T12:34:56+00:00"
