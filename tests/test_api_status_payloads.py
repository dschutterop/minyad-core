import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import battery_status_payload, grid_status_payload


def test_battery_status_payload_excludes_grid_keys():
    payload = {
        "soc": "80",
        "power_w": "250",
        "grid_net_power_w": "100",
        "grid_status": "connected",
    }

    assert battery_status_payload(payload) == {"soc": "80", "power_w": "250"}


def test_grid_status_payload_includes_grid_and_solar_keys():
    payload = {
        "soc": "80",
        "grid_net_power_w": "100",
        "grid_status": "connected",
        "solar_power_w": "400",
    }

    assert grid_status_payload(payload) == {
        "grid_net_power_w": "100",
        "grid_status": "connected",
        "solar_power_w": "400",
    }


def test_solar_status_payload_groups_inverters_and_arrays():
    from api.main import solar_status_payload

    payload = {
        "solar_power_w": "321",
        "solar_updated_at": "2026-06-23T12:00:00Z",
        "solar_bridge_status": "online",
        "solar_inverter_abc_power_w": "123",
        "solar_inverter_abc_last_report_at": "2026-06-23T11:59:59Z",
        "solar_array_roof_power_w": "321",
    }

    assert solar_status_payload(payload) == {
        "power_w": 321,
        "updated_at": "2026-06-23T12:00:00Z",
        "bridge_status": "online",
        "bridge_last_seen": None,
        "inverters": [{"serial": "abc", "power_w": 123, "last_report_at": "2026-06-23T11:59:59Z"}],
        "arrays": {"roof": 321},
    }


def test_solar_dynamic_status_key_maps_micro_inverter_topics():
    from api.main import solar_dynamic_status_key

    assert solar_dynamic_status_key("minyad/solar/inverter/123/power_w") == "solar_inverter_123_power_w"
    assert solar_dynamic_status_key("minyad/solar/inverter/123/last_report_at") == "solar_inverter_123_last_report_at"
    assert solar_dynamic_status_key("minyad/solar/array/main-roof/power_w") == "solar_array_main-roof_power_w"
