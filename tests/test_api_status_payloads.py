from api.main import battery_status_payload, grid_status_payload


def test_battery_status_payload_excludes_grid_keys():
    payload = {
        "soc": "80",
        "power_w": "250",
        "grid_net_power_w": "100",
        "grid_status": "connected",
    }

    assert battery_status_payload(payload) == {"soc": "80", "power_w": "250"}


def test_grid_status_payload_only_includes_grid_keys():
    payload = {
        "soc": "80",
        "grid_net_power_w": "100",
        "grid_status": "connected",
    }

    assert grid_status_payload(payload) == {"grid_net_power_w": "100", "grid_status": "connected"}
