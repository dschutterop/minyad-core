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
