"""Endpoint-level tests for api.routers.battery.

Focus is the code that had *no* prior direct coverage despite being the safety-critical
path: SoC-limit enforcement and amp/voltage hardware clamping in set_battery_override,
range/consistency validation in update_battery_settings, and the setpoint-to-override-mode
translation in api_control_battery. Uses the same lightweight fake AsyncSession as
test_api_settings_endpoints.py rather than a real database.
"""

import asyncio
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from api.routers import battery as battery_router
from tests.test_api_settings_endpoints import FakeResult, FakeSession


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fake_mqtt_publish(monkeypatch):
    published = []
    monkeypatch.setattr(
        battery_router.mqtt.client,
        "publish",
        lambda topic, payload=None, qos=0, retain=False: published.append((topic, payload)),
    )
    return published


COMPLETE_STATUS = {
    "soc": "55",
    "soh": "98",
    "power_w": "0",
    "voltage": "51.2",
    "mode": "idle",
    "bridge_status": "online",
    "bridge_last_seen": "2026-06-01T00:00:00+00:00",
}


# Note: BatterySettingsUpdate.validate_ip and BatteryOverrideRequest.validate_required_fields
# are already covered directly by tests/test_api_pure_helpers.py — not duplicated here.


# --------------------------------------------------------------------------- #
# battery_settings
# --------------------------------------------------------------------------- #
def test_battery_settings_skips_status_keys_and_coerces_ints():
    rows = [
        {"key": "battery.soc_floor", "value": "25"},
        {"key": "battery.status.soc", "value": "80"},
        {"key": "battery.inverter_ip", "value": "192.0.2.5"},
    ]
    session = FakeSession([("battery.%", FakeResult(rows=rows))])

    result = run(battery_router.battery_settings(session))

    assert result["soc_floor"] == 25
    assert "status.soc" not in result and "soc" not in result  # battery.status.* is skipped, not aliased
    assert result["inverter_ip"] == "192.0.2.5"


# --------------------------------------------------------------------------- #
# battery_lp_meta
# --------------------------------------------------------------------------- #
def test_battery_lp_meta_uses_defaults_when_unconfigured():
    session = FakeSession([("from settings where key = any", FakeResult(rows=[]))])

    result = run(battery_router.battery_lp_meta(session))

    assert result["capacity_kwh"] == 10.24
    assert result["max_charge_w"] == int(min(1440.0, 30.0 * 48.0))
    assert result["max_discharge_w"] == 5000


def test_battery_lp_meta_caps_charge_power_by_amp_times_voltage():
    rows = [
        {"key": "battery.max_charge_w", "value": "3000"},
        {"key": "battery.max_charge_a", "value": "20"},
        {"key": "battery.nominal_v", "value": "48"},
    ]
    session = FakeSession([("from settings where key = any", FakeResult(rows=rows))])

    result = run(battery_router.battery_lp_meta(session))

    # hardware ceiling (20A * 48V = 960W) is tighter than the configured 3000W setting.
    assert result["max_charge_w"] == 960


def test_battery_lp_meta_falls_back_to_default_on_unparseable_value():
    rows = [{"key": "battery.capacity_wh", "value": "not-a-number"}]
    session = FakeSession([("from settings where key = any", FakeResult(rows=rows))])

    result = run(battery_router.battery_lp_meta(session))

    assert result["capacity_kwh"] == 10.24


# --------------------------------------------------------------------------- #
# household_status_payload
# --------------------------------------------------------------------------- #
def test_household_status_skips_retained_fetch_when_grid_keys_cached(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"grid_net_power_w": "500"})
    calls = []
    monkeypatch.setattr(battery_router, "collect_retained_mqtt_status", lambda: calls.append(1) or {})
    session = FakeSession([])

    result = run(battery_router.household_status_payload(session, store=False))

    assert calls == []
    assert result["power_w"] is not None


def test_household_status_falls_back_to_retained_fetch_when_grid_keys_missing(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {})
    calls = []
    monkeypatch.setattr(
        battery_router, "collect_retained_mqtt_status", lambda: calls.append(1) or {"grid_net_power_w": "300"}
    )
    session = FakeSession([])

    run(battery_router.household_status_payload(session, store=False))

    assert calls == [1]


def test_household_status_swallows_oserror_from_retained_fetch(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {})

    def _raise():
        raise OSError("mqtt broker unreachable")

    monkeypatch.setattr(battery_router, "collect_retained_mqtt_status", _raise)
    session = FakeSession([])

    result = run(battery_router.household_status_payload(session, store=False))

    assert isinstance(result, dict)


def test_household_status_stores_power_curve_point_when_requested(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"grid_net_power_w": "500"})
    session = FakeSession([])

    run(battery_router.household_status_payload(session, store=True))

    assert session.commits == 1


def test_household_status_does_not_store_when_store_false(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"grid_net_power_w": "500"})
    session = FakeSession([])

    run(battery_router.household_status_payload(session, store=False))

    assert session.commits == 0


# --------------------------------------------------------------------------- #
# battery_status
# --------------------------------------------------------------------------- #
def test_battery_status_skips_retained_fetch_when_cache_complete(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: dict(COMPLETE_STATUS))
    calls = []
    monkeypatch.setattr(battery_router, "collect_retained_mqtt_status", lambda: calls.append(1) or {})
    session = FakeSession([("battery.status.", FakeResult(rows=[])), ("battery_override", FakeResult(rows=[]))])

    result = run(battery_router.battery_status(session))

    assert calls == []
    assert result["override_mode"] == "none"


def test_battery_status_merges_retained_fetch_when_incomplete(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "55"})
    calls = []
    monkeypatch.setattr(
        battery_router,
        "collect_retained_mqtt_status",
        lambda: calls.append(1) or dict(COMPLETE_STATUS),
    )
    session = FakeSession([("battery.status.", FakeResult(rows=[])), ("battery_override", FakeResult(rows=[]))])

    result = run(battery_router.battery_status(session))

    assert calls == [1]
    assert result["bridge_status"] == "online"


def test_battery_status_swallows_oserror_from_retained_fetch(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "55"})

    def _raise():
        raise OSError("mqtt broker unreachable")

    monkeypatch.setattr(battery_router, "collect_retained_mqtt_status", _raise)
    session = FakeSession([("battery.status.", FakeResult(rows=[])), ("battery_override", FakeResult(rows=[]))])

    result = run(battery_router.battery_status(session))

    assert result["soc"] == 55


def test_battery_status_coerces_voltage_grid_power_and_available(monkeypatch):
    from datetime import UTC, datetime

    fresh_status = dict(COMPLETE_STATUS, bridge_last_seen=datetime.now(UTC).isoformat())
    payload = dict(fresh_status, voltage="51.7", grid_power_w="1234", available="TRUE")
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: payload)
    session = FakeSession([("battery.status.", FakeResult(rows=[])), ("battery_override", FakeResult(rows=[]))])

    result = run(battery_router.battery_status(session))

    assert result["voltage"] == 51.7
    assert result["grid_power_w"] == 1234
    assert result["available"] is True


def test_battery_status_reports_active_override_mode(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: dict(COMPLETE_STATUS))
    session = FakeSession(
        [
            ("battery.status.", FakeResult(rows=[])),
            ("battery_override", FakeResult(rows=[{"mode": "force_charge", "override_soc_limits": True}])),
        ]
    )

    result = run(battery_router.battery_status(session))

    assert result["override_mode"] == "force_charge"
    assert result["override_soc_limits"] is True


# --------------------------------------------------------------------------- #
# api_control_battery — setpoint-to-override-mode translation
# --------------------------------------------------------------------------- #
def test_api_control_battery_positive_setpoint_requests_force_charge(monkeypatch):
    captured = {}

    async def fake_set_battery_override(request, session):
        await asyncio.sleep(0)
        captured["request"] = request
        return {"status": "ok", "mode": request.mode}

    monkeypatch.setattr(battery_router, "set_battery_override", fake_set_battery_override)
    request = battery_router.AgentBatteryControlRequest(setpoint_w=800, duration_minutes=10)

    result = run(battery_router.api_control_battery(request, session=object()))

    assert captured["request"].mode == "force_charge"
    assert captured["request"].watts == 800
    assert result["action"] == "charge"


def test_api_control_battery_negative_setpoint_requests_force_discharge(monkeypatch):
    captured = {}

    async def fake_set_battery_override(request, session):
        await asyncio.sleep(0)
        captured["request"] = request
        return {"status": "ok", "mode": request.mode}

    monkeypatch.setattr(battery_router, "set_battery_override", fake_set_battery_override)
    request = battery_router.AgentBatteryControlRequest(setpoint_w=-500, duration_minutes=5)

    result = run(battery_router.api_control_battery(request, session=object()))

    assert captured["request"].mode == "force_discharge"
    assert captured["request"].watts == 500
    assert result["action"] == "discharge"


def test_api_control_battery_zero_setpoint_without_active_override_clears_to_none(monkeypatch):
    async def fake_current_override(session):
        await asyncio.sleep(0)
        return None

    captured = {}

    async def fake_set_battery_override(request, session):
        await asyncio.sleep(0)
        captured["request"] = request
        return {"status": "ok", "mode": request.mode}

    monkeypatch.setattr(battery_router, "current_battery_override", fake_current_override)
    monkeypatch.setattr(battery_router, "set_battery_override", fake_set_battery_override)
    request = battery_router.AgentBatteryControlRequest(setpoint_w=0)

    result = run(battery_router.api_control_battery(request, session=object()))

    assert captured["request"].mode == "none"
    assert result["action"] == "hold"


def test_api_control_battery_passes_through_422_from_set_battery_override(monkeypatch):
    async def fake_set_battery_override(request, session):
        await asyncio.sleep(0)
        return JSONResponse(status_code=422, content={"detail": "blocked"})

    monkeypatch.setattr(battery_router, "set_battery_override", fake_set_battery_override)
    request = battery_router.AgentBatteryControlRequest(setpoint_w=800)

    result = run(battery_router.api_control_battery(request, session=object()))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422


# --------------------------------------------------------------------------- #
# set_battery_override — SoC-limit and hardware-clamp validation
# --------------------------------------------------------------------------- #
def _settings_session(rows):
    return FakeSession([("battery.%", FakeResult(rows=rows))])


def test_set_battery_override_blocks_discharge_at_or_below_floor(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "20"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_discharge", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    assert session.commits == 0


def test_set_battery_override_blocks_charge_at_or_above_ceiling(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "90"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_charge", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422


def test_set_battery_override_soc_limit_override_flag_bypasses_floor_check(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "5"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(
        mode="force_discharge", watts=500, duration_seconds=60, override_soc_limits=True
    )

    result = run(battery_router.set_battery_override(request, session))

    assert result["status"] == "ok"
    assert session.commits == 1


def test_set_battery_override_rejects_watts_above_hardware_clamp(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "50"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
            {"key": "battery.max_charge_w", "value": "3000"},
            {"key": "battery.max_charge_a", "value": "10"},
            {"key": "battery.nominal_v", "value": "48"},
        ]
    )
    # hardware ceiling is 10A * 48V = 480W; requesting 500W of charge should be rejected
    # even though it is below the configured max_charge_w of 3000W.
    request = battery_router.BatteryOverrideRequest(mode="force_charge", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    assert "MAX_CHARGE_W" in result.body.decode()


def test_set_battery_override_treats_unparseable_soc_as_unknown(monkeypatch):
    # An unparseable cached SoC must not be mistaken for "at the floor" — it should be
    # treated as unknown (soc_value=None), which skips the SoC-limit check entirely rather
    # than blocking or wrongly allowing the override based on a bogus comparison.
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "not-a-number"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
            {"key": "battery.max_charge_w", "value": "1440"},
            {"key": "battery.max_charge_a", "value": "30"},
            {"key": "battery.nominal_v", "value": "48"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_charge", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert result["status"] == "ok"


def test_set_battery_override_falls_back_to_db_soc_when_mqtt_cache_empty(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {})
    session = FakeSession(
        [
            ("battery.%", FakeResult(rows=[{"key": "battery.soc_floor", "value": "20"}, {"key": "battery.soc_ceiling", "value": "90"}])),
            ("battery.status.soc", FakeResult(scalar="15")),
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_discharge", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422


def test_set_battery_override_persists_and_publishes_on_success(monkeypatch, _fake_mqtt_publish):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "50"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
            {"key": "battery.max_charge_w", "value": "1440"},
            {"key": "battery.max_charge_a", "value": "30"},
            {"key": "battery.nominal_v", "value": "48"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_charge", watts=500, duration_seconds=120)

    result = run(battery_router.set_battery_override(request, session))

    assert result["status"] == "ok"
    assert session.commits == 1
    assert any(topic == battery_router.TOPIC_CONTROL_OVERRIDE for topic, _ in _fake_mqtt_publish)
    insert_params = [params for sql, params in session.executed if "insert into battery_override" in sql]
    assert insert_params and insert_params[0]["mode"] == "force_charge"


def test_set_battery_override_normalizes_legacy_mode_aliases(monkeypatch):
    monkeypatch.setattr(battery_router, "latest_mqtt_status", lambda: {"soc": "50"})
    session = _settings_session(
        [
            {"key": "battery.soc_floor", "value": "20"},
            {"key": "battery.soc_ceiling", "value": "90"},
            {"key": "battery.max_charge_w", "value": "1440"},
            {"key": "battery.max_charge_a", "value": "30"},
            {"key": "battery.nominal_v", "value": "48"},
        ]
    )
    request = battery_router.BatteryOverrideRequest(mode="force_on", watts=500, duration_seconds=60)

    result = run(battery_router.set_battery_override(request, session))

    assert result["mode"] == "force_charge"


# --------------------------------------------------------------------------- #
# clear_battery_override
# --------------------------------------------------------------------------- #
def test_clear_battery_override_commits_and_publishes(_fake_mqtt_publish):
    session = FakeSession([])

    result = run(battery_router.clear_battery_override(session))

    assert result == {"status": "ok", "mode": "none"}
    assert session.commits == 1
    assert any(topic == battery_router.TOPIC_CONTROL_OVERRIDE for topic, _ in _fake_mqtt_publish)


# --------------------------------------------------------------------------- #
# update_battery_settings — range/consistency validation
# --------------------------------------------------------------------------- #
def _current_settings_session(current_rows):
    return FakeSession([("battery.%", FakeResult(rows=current_rows))])


def test_update_battery_settings_rejects_stop_w_above_start_w():
    session = _current_settings_session([{"key": "battery.start_w", "value": "500"}])
    update = battery_router.BatterySettingsUpdate(stop_w=600)

    with pytest.raises(HTTPException) as exc:
        run(battery_router.update_battery_settings(update, session))
    assert exc.value.status_code == 422
    assert "stop_w" in exc.value.detail


def test_update_battery_settings_rejects_soc_floor_at_or_above_ceiling():
    session = _current_settings_session([{"key": "battery.soc_ceiling", "value": "80"}])
    update = battery_router.BatterySettingsUpdate(soc_floor=80)

    with pytest.raises(HTTPException) as exc:
        run(battery_router.update_battery_settings(update, session))
    assert exc.value.status_code == 422
    assert "soc_floor" in exc.value.detail


def test_update_battery_settings_rejects_out_of_range_value():
    session = _current_settings_session([])
    update = battery_router.BatterySettingsUpdate(cooldown=10)  # BATTERY_KEYS["cooldown"] is (60, 7200)

    with pytest.raises(HTTPException) as exc:
        run(battery_router.update_battery_settings(update, session))
    assert exc.value.status_code == 422
    assert "cooldown" in exc.value.detail


def test_update_battery_settings_persists_valid_update_and_publishes(monkeypatch, _fake_mqtt_publish):
    # The fake session can't simulate a mutated table, so it always re-reads the pre-update
    # rows; assertions target what update_battery_settings actually writes (upsert params,
    # the in-memory-derived bridge_stale_seconds insert) rather than the stale read-back.
    session = _current_settings_session([{"key": "battery.soc_floor", "value": "20"}, {"key": "battery.soc_ceiling", "value": "90"}])
    monkeypatch.setattr(battery_router, "publish_battery_mqtt_settings", lambda settings: None)
    update = battery_router.BatterySettingsUpdate(soc_floor=25)

    run(battery_router.update_battery_settings(update, session))

    assert session.commits == 1
    soc_floor_inserts = [
        params for sql, params in session.executed if "insert into settings" in sql and params.get("key") == "battery.soc_floor"
    ]
    assert soc_floor_inserts == [{"key": "battery.soc_floor", "value": "25"}]
    stale_seconds_inserts = [params for sql, params in session.executed if "strategy.bridge_stale_seconds" in sql]
    assert stale_seconds_inserts
    assert any(topic == battery_router.TOPIC_CONTROL_OVERRIDE for topic, _ in _fake_mqtt_publish)
