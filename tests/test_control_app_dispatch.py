"""Tests for ControlApp message dispatch, bridge health and override handling.

Reuses the module-load and fake-mqtt helpers from test_control_bridge_health and
drives the async handlers directly to cover topic routing, bridge status/last_seen
updates, override application and strategy-v2 setpoint forwarding.
"""

import asyncio

import pytest

from tests.test_control_bridge_health import (
    control_main,
    make_available_app,
    noop_store_status,
)

ControlState = control_main.ControlState
OverrideMode = control_main.OverrideMode


def run(coro):
    return asyncio.run(coro)


class FakeOverrideController:
    def __init__(self, state=None):
        self._state = state or ControlState.IDLE
        self.override_mode = OverrideMode.NONE
        self.cleared = False
        self.set_overrides = []

    @property
    def state(self):
        return self._state

    def clear_override(self):
        self.cleared = True

    def set_override(self, mode, duration):
        self.set_overrides.append((mode, duration))


@pytest.fixture(autouse=True)
def _stub_store_status(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)


# --------------------------------------------------------------------------- #
# handle_solar_topic
# --------------------------------------------------------------------------- #
def test_handle_solar_topic_updates_pv_power():
    app = make_available_app()
    run(app.handle_solar_topic("1234.0"))
    assert app.latest_pv_power_w == 1234


def test_handle_solar_topic_ignores_invalid_payload():
    app = make_available_app()
    app.latest_pv_power_w = 42
    run(app.handle_solar_topic("not-a-number"))
    assert app.latest_pv_power_w == 42


# --------------------------------------------------------------------------- #
# handle_bridge_topic routing
# --------------------------------------------------------------------------- #
def test_handle_bridge_topic_routes_status():
    app = make_available_app()
    run(app.handle_bridge_topic("minyad/bridge/status", " ONLINE "))
    assert app.bridge_status == "online"


def test_handle_bridge_topic_routes_last_seen():
    app = make_available_app()
    run(app.handle_bridge_topic("minyad/bridge/last_seen", "2026-06-18T09:24:03Z"))
    assert app.bridge_last_seen_raw == "2026-06-18T09:24:03Z"


def test_handle_bridge_topic_ignores_unknown():
    app = make_available_app()
    run(app.handle_bridge_topic("minyad/bridge/whatever", "x"))
    # nothing published for an unsupported measurement
    assert app.mqtt.published == []


# --------------------------------------------------------------------------- #
# handle_bridge_status
# --------------------------------------------------------------------------- #
def test_handle_bridge_status_online_keeps_available():
    app = make_available_app()
    run(app.handle_bridge_status("online"))
    assert app.bridge_status == "online"
    assert app.bridge_is_available is True


def test_handle_bridge_status_offline_marks_unavailable():
    app = make_available_app()
    app.setpoint_w = 500
    run(app.handle_bridge_status("offline"))
    assert app.bridge_status == "offline"
    # mark_bridge_unavailable zeroes the setpoint and issues a stop command
    assert app.setpoint_w == 0
    assert ("control", "command", "stop") in app.mqtt.published


# --------------------------------------------------------------------------- #
# handle_bridge_last_seen
# --------------------------------------------------------------------------- #
def test_handle_bridge_last_seen_fresh_is_valid():
    from datetime import datetime, timezone

    app = make_available_app()
    fresh = datetime.now(timezone.utc).isoformat()
    run(app.handle_bridge_last_seen(fresh))
    assert app.bridge_last_seen_error is None


def test_handle_bridge_last_seen_invalid_records_error():
    app = make_available_app()
    run(app.handle_bridge_last_seen("not-a-timestamp"))
    assert app.bridge_last_seen is None
    assert "invalid bridge last_seen" in app.bridge_last_seen_error


def test_handle_bridge_last_seen_stale_marks_unavailable():
    from datetime import datetime, timedelta, timezone

    app = make_available_app()
    app.setpoint_w = 300
    stale = (datetime.now(timezone.utc) - timedelta(seconds=control_main.BRIDGE_LAST_SEEN_STALE_SECONDS + 30)).isoformat()
    run(app.handle_bridge_last_seen(stale))
    assert app.bridge_last_seen_error == "bridge last_seen is stale"
    assert app.setpoint_w == 0


# --------------------------------------------------------------------------- #
# _mark_bridge_health_seen
# --------------------------------------------------------------------------- #
def test_mark_bridge_health_seen_sets_event_when_online():
    app = make_available_app()
    app.bridge_health_event = asyncio.Event()
    app.bridge_status = "online"
    app._mark_bridge_health_seen()
    assert app.bridge_health_event.is_set()


def test_mark_bridge_health_seen_keeps_waiting_when_offline():
    app = make_available_app()
    app.bridge_health_event = asyncio.Event()
    app.bridge_status = "offline"
    app._mark_bridge_health_seen()
    assert not app.bridge_health_event.is_set()


# --------------------------------------------------------------------------- #
# apply_override
# --------------------------------------------------------------------------- #
def test_apply_override_none_clears_and_zeroes_setpoint():
    app = make_available_app()
    app.controller = FakeOverrideController()
    app.setpoint_w = 900
    run(app.apply_override({"mode": "none"}))
    assert app.controller.cleared is True
    assert app.setpoint_w == 0


def test_apply_override_returns_early_without_controller():
    app = make_available_app()
    app.controller = None
    # Should not raise even though there is no controller.
    run(app.apply_override({"mode": "force_on", "watts": 500}))
    assert app.mqtt.published == []


def test_apply_override_force_on_publishes_charge_setpoint():
    app = make_available_app()
    app.controller = FakeOverrideController()
    app.latest_battery_soc = None
    run(app.apply_override({"mode": "force_on", "watts": 700, "duration_seconds": 900}))
    assert app.controller.set_overrides
    assert ("control", "command", "resume") in app.mqtt.published
    assert app.setpoint_w == 700


def test_apply_override_force_discharge_publishes_discharge_setpoint():
    app = make_available_app()
    app.controller = FakeOverrideController()
    app.latest_battery_soc = None
    run(app.apply_override({"mode": "force_discharge", "watts": 600}))
    assert ("control", "command", "discharge") in app.mqtt.published
    assert app.setpoint_w == 600


def test_apply_override_pause_stops_charging():
    app = make_available_app()
    app.controller = FakeOverrideController()
    run(app.apply_override({"mode": "pause", "duration_seconds": 120}))
    # stop_charging publishes a stop command
    assert ("control", "command", "stop") in app.mqtt.published


# --------------------------------------------------------------------------- #
# apply_strategy_v2_setpoint
# --------------------------------------------------------------------------- #
def test_apply_strategy_v2_setpoint_noop_when_not_primary(monkeypatch):
    monkeypatch.setattr(control_main, "STRATEGY_V2_PRIMARY", False)
    app = make_available_app()
    run(app.apply_strategy_v2_setpoint(500))
    assert app.mqtt.published == []


def test_apply_strategy_v2_setpoint_positive_charges(monkeypatch):
    monkeypatch.setattr(control_main, "STRATEGY_V2_PRIMARY", True)
    app = make_available_app()
    app.latest_battery_soc = None
    run(app.apply_strategy_v2_setpoint(800))
    assert app.setpoint_w == 800
    assert ("control", "command", "resume") in app.mqtt.published


def test_apply_strategy_v2_setpoint_negative_discharges(monkeypatch):
    monkeypatch.setattr(control_main, "STRATEGY_V2_PRIMARY", True)
    app = make_available_app()
    app.latest_battery_soc = None
    run(app.apply_strategy_v2_setpoint(-450))
    assert app.setpoint_w == 450
    assert ("control", "command", "discharge") in app.mqtt.published


def test_apply_strategy_v2_setpoint_zero_stops(monkeypatch):
    monkeypatch.setattr(control_main, "STRATEGY_V2_PRIMARY", True)
    app = make_available_app()
    run(app.apply_strategy_v2_setpoint(0))
    assert ("control", "command", "stop") in app.mqtt.published


# --------------------------------------------------------------------------- #
# handle_message dispatch (override reload + solar)
# --------------------------------------------------------------------------- #
def test_handle_message_override_reload_settings(monkeypatch):
    app = make_available_app()
    calls = {"reload": 0, "guard": 0}

    async def fake_reload():
        calls["reload"] += 1

    async def fake_guard():
        calls["guard"] += 1

    monkeypatch.setattr(app, "reload_settings", fake_reload)
    monkeypatch.setattr(app, "enforce_soc_guard_now", fake_guard)
    run(app.handle_message("minyad/control/override", b'{"mode": "reload_settings"}'))
    assert calls == {"reload": 1, "guard": 1}


def test_handle_message_solar_topic_updates_pv():
    app = make_available_app()
    run(app.handle_message("minyad/solar/production_w", b"321"))
    assert app.latest_pv_power_w == 321
