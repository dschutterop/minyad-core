import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import asyncio
from datetime import datetime, timezone

import api.main as api_main
from api.main import SURPLUS_API_VERSION, app, battery_curve_power_w, battery_status_payload, build_surplus_payload, compute_household_load, derive_battery_state, grid_status_payload


def test_battery_status_payload_excludes_grid_keys():
    payload = {
        "soc": "80",
        "power_w": "250",
        "grid_net_power_w": "100",
        "grid_status": "connected",
        "grid_power_w": "4",
    }

    assert battery_status_payload(payload) == {"soc": "80", "power_w": "250", "grid_power_w": "4"}


def test_battery_status_includes_soc_limit_override_flag(monkeypatch):
    class Result:
        def __init__(self, rows=None, mapping=None):
            self.rows = rows or []
            self.mapping = mapping

        def __iter__(self):
            return iter(self.rows)

        def mappings(self):
            return self

        def first(self):
            return self.mapping

    class Session:
        def __init__(self):
            self.calls = 0

        async def execute(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return Result(rows=[])
            return Result(mapping={"mode": "force_charge", "override_soc_limits": True})

        async def commit(self):
            return None

    monkeypatch.setattr(
        api_main,
        "latest_mqtt_status",
        lambda: {
            "soc": "91",
            "soh": "98",
            "power_w": "-700",
            "voltage": "52.1",
            "mode": "charge",
            "bridge_status": "online",
            "bridge_last_seen": datetime.now(timezone.utc).isoformat(),
        },
    )
    async def skip_curve_store(*_args, **_kwargs):
        await asyncio.sleep(0)
        return None

    monkeypatch.setattr(api_main, "store_power_curve_point", skip_curve_store)

    payload = asyncio.run(api_main.battery_status(Session()))

    assert payload["override_mode"] == "force_charge"
    assert payload["override_soc_limits"] is True


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


def test_household_load_counts_battery_discharge_as_consumption_supply():
    result = compute_household_load({"solar_power_w": "0", "power_w": "1000"})

    assert result["power_w"] == 1000
    assert result["method_a_w"] == 1000
    assert result["battery_discharge_w"] == 1000


def test_household_load_does_not_flag_normal_grid_import_as_mismatch():
    result = compute_household_load({
        "solar_power_w": "0",
        "power_w": "1000",
        "grid_delivered_w": "600",
        "grid_returned_w": "0",
    })

    assert result["power_w"] == 1600
    assert result["method_a_w"] == 1000
    assert result["method_b_w"] == 1600
    assert result["mismatch"] is False


def test_surplus_payload_reports_remaining_and_gross_surplus_while_battery_charges():
    payload = build_surplus_payload(
        {"grid_net_power_w": "-300", "solar_power_w": "2500"},
        {"state": "CHARGING", "control_state": "CHARGING", "power_w": "-1200", "soc": 62},
        {"soc_floor": 20, "soc_ceiling": 90, "cooldown": 180, "start_w": 500, "stop_w": 150},
        now=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
    )

    assert payload["api_version"] == SURPLUS_API_VERSION
    assert payload["surplus_w"] == 300
    assert payload["gross_surplus_w"] == 1500
    assert payload["battery"]["phase"] == "charging"
    assert payload["battery"]["is_charging"] is True
    assert payload["minyad"]["is_absorbing_surplus"] is True


def test_surplus_payload_marks_cooldown_even_when_export_remains():
    payload = build_surplus_payload(
        {"grid_net_power_w": "-700"},
        {"state": "IDLE", "control_state": "COOLDOWN", "power_w": "0"},
        {"cooldown": 180},
        now=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
    )

    assert payload["surplus_w"] == 700
    assert payload["gross_surplus_w"] == 700
    assert payload["battery"]["phase"] == "cooldown"
    assert payload["battery"]["is_cooldown"] is True
    assert payload["minyad"]["surplus_handling"] == "cooldown"


def test_surplus_payload_marks_idle_with_remaining_export():
    payload = build_surplus_payload(
        {"grid_net_power_w": "-450"},
        {"state": "IDLE", "control_state": "IDLE", "power_w": "0"},
        {},
        now=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
    )

    assert payload["has_surplus"] is True
    assert payload["battery"]["phase"] == "idle"
    assert payload["battery"]["is_idle"] is True


def test_surplus_api_exposes_versioned_route_and_legacy_alias():
    route_paths = {route.path for route in app.routes}

    assert "/api/v1/surplus" in route_paths
    assert "/api/surplus" in route_paths


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
