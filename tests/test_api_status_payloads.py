import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import battery_curve_power_w, battery_status_payload, compute_household_load, derive_battery_state, grid_status_payload


def test_battery_status_payload_excludes_grid_keys():
    payload = {
        "soc": "80",
        "power_w": "250",
        "grid_net_power_w": "100",
        "grid_status": "connected",
        "grid_power_w": "4",
    }

    assert battery_status_payload(payload) == {"soc": "80", "power_w": "250", "grid_power_w": "4"}


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


def test_derive_battery_state_uses_bridge_power_and_mode_for_external_charge():
    payload = {"power_w": "1200", "grid_power_w": "4", "mode": "charge"}

    assert derive_battery_state(payload, fallback="IDLE") == "CHARGING"


def test_derive_battery_state_uses_bridge_power_sign_without_mode():
    assert derive_battery_state({"power_w": "250"}) == "DISCHARGING"
    assert derive_battery_state({"power_w": "-250"}) == "CHARGING"


def test_derive_battery_state_keeps_fallback_inside_deadband():
    assert derive_battery_state({"power_w": "4", "mode": "idle"}, fallback="IDLE") == "IDLE"


def test_battery_curve_power_prefers_actual_power_over_stale_setpoint():
    payload = {"power_w": "0", "discharge_w": "2200", "setpoint_w": "0"}

    assert battery_curve_power_w(payload) == 0


def test_battery_curve_power_falls_back_to_setpoint_without_actual_power():
    assert battery_curve_power_w({"discharge_w": "2200"}) == 2200
    assert battery_curve_power_w({"setpoint_w": "1400"}) == -1400


def test_household_load_uses_idle_actual_battery_power_over_stale_discharge_setpoint():
    payload = {
        "solar_power_w": "1000",
        "power_w": "0",
        "discharge_w": "2200",
        "grid_net_power_w": "500",
    }

    result = compute_household_load(payload)

    assert result["battery_discharge_w"] == 0
    assert result["battery_charge_w"] == 0


def test_build_health_status_reports_core_components(monkeypatch):
    from datetime import datetime, timezone
    from api.main import build_health_status, mqtt

    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(mqtt, "connection_info", lambda: {"host": "mqtt", "port": 1883, "connected": True})
    payload = build_health_status(
        {
            "soc": "80",
            "power_w": "0",
            "voltage": "52",
            "mode": "idle",
            "bridge_status": "online",
            "bridge_last_seen": now,
            "grid_net_power_w": "123",
            "grid_timestamp": now,
            "grid_status": "connected",
            "solar_power_w": "456",
            "solar_updated_at": now,
        },
        db_ok=True,
    )

    assert payload["status"] in {"ok", "warning"}
    component_names = {component["name"] for component in payload["components"]}
    assert {"API", "PostgreSQL", "MQTT broker", "Battery / GoodWe bridge", "DSMR / grid meter", "Solar / Enphase bridge"} <= component_names
