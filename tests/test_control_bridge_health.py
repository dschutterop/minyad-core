import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

shared_db = types.ModuleType("shared.db")
shared_db.AsyncSessionLocal = object
sys.modules.setdefault("shared.db", shared_db)
ROOT = Path(__file__).resolve().parents[1]
CONTROL_DIR = ROOT / "control"
if str(CONTROL_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROL_DIR))

spec = importlib.util.spec_from_file_location("control_main", CONTROL_DIR / "main.py")
control_main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(control_main)


async def noop_store_status(**_values):
    return None


def test_bridge_requires_fresh_last_seen(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = control_main.ControlApp()
    app.bridge_status = "online"

    assert app.bridge_is_available is True

    app.bridge_last_seen = datetime.now(timezone.utc) - timedelta(
        seconds=control_main.BRIDGE_LAST_SEEN_STALE_SECONDS + 5
    )
    assert app.bridge_is_available is False

    app.bridge_last_seen = datetime.now(timezone.utc)
    assert app.bridge_is_available is True


def test_parse_bridge_last_seen_accepts_zulu_timestamp():
    app = control_main.ControlApp()
    parsed = app.parse_bridge_last_seen("2026-06-18T09:24:03Z")

    assert parsed == datetime(2026, 6, 18, 9, 24, 3, tzinfo=timezone.utc)


def test_parse_bridge_last_seen_rejects_invalid_timestamp():
    app = control_main.ControlApp()

    assert app.parse_bridge_last_seen("not-a-timestamp") is None


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish_measurement(self, source, measurement, payload):
        self.published.append((source, measurement, payload))


def make_available_app():
    app = control_main.ControlApp()
    app.mqtt = FakeMqtt()
    app.bridge_status = "online"
    app.bridge_last_seen = datetime.now(timezone.utc)
    return app


def test_charge_setpoint_publishes_bridge_charge_topic(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()

    asyncio.run(app.publish_setpoint(250))

    assert ("control", "charge_w", 250) in app.mqtt.published
    assert ("control", "setpoint_w", 250) in app.mqtt.published


def test_stop_charging_publishes_zero_charge_topic(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()

    asyncio.run(app.stop_charging())

    assert ("control", "charge_w", 0) in app.mqtt.published
    assert ("control", "discharge_w", 0) in app.mqtt.published


def test_retained_bridge_status_marks_initial_health_seen():
    app = control_main.ControlApp()
    app.bridge_health_event = asyncio.Event()
    app.bridge_status = "online"

    app._mark_bridge_health_seen()

    assert app.bridge_health_event.is_set()


def test_online_bridge_status_without_last_seen_allows_setpoint(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = control_main.ControlApp()
    app.mqtt = FakeMqtt()
    app.bridge_status = "online"

    asyncio.run(app.publish_setpoint(250))

    assert ("control", "charge_w", 250) in app.mqtt.published


def test_live_battery_telemetry_refreshes_stale_bridge_heartbeat(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = control_main.ControlApp()
    app.bridge_status = "online"
    app.bridge_last_seen = datetime.now(timezone.utc) - timedelta(
        seconds=control_main.BRIDGE_LAST_SEEN_STALE_SECONDS + 5
    )
    app.bridge_last_seen_raw = app.bridge_last_seen.isoformat()
    app.bridge_last_seen_error = "bridge last_seen is stale"

    app.refresh_bridge_last_seen_from_battery_telemetry()

    assert app.bridge_is_available is True
    assert app.bridge_last_seen_error is None


def test_offline_bridge_does_not_refresh_from_battery_telemetry(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = control_main.ControlApp()
    app.bridge_status = "offline"
    stale_last_seen = datetime.now(timezone.utc) - timedelta(
        seconds=control_main.BRIDGE_LAST_SEEN_STALE_SECONDS + 5
    )
    app.bridge_last_seen = stale_last_seen
    app.bridge_last_seen_raw = stale_last_seen.isoformat()
    app.bridge_last_seen_error = "bridge last_seen is stale"

    app.refresh_bridge_last_seen_from_battery_telemetry()

    assert app.bridge_is_available is False
    assert app.bridge_last_seen == stale_last_seen
    assert app.bridge_last_seen_error == "bridge last_seen is stale"

def test_battery_mode_accepts_goodwe_text_payload(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = control_main.ControlApp()

    asyncio.run(app.handle_battery_topic("minyad/battery/mode", "charge"))

    assert stored == {"mode": "charge"}


def test_invalid_numeric_battery_payload_is_ignored(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = control_main.ControlApp()

    asyncio.run(app.handle_battery_topic("minyad/battery/soc", "charge"))

    assert stored == {}


class FakeGridController:
    def __init__(self):
        self.samples = []
        self.state = control_main.ControlState.IDLE
        self.override_mode = control_main.OverrideMode.NONE

    def tick(self, surplus_w):
        self.samples.append(surplus_w)
        if surplus_w <= -300:
            self.state = control_main.ControlState.DISCHARGING
            return self.state
        return None


def test_grid_net_power_import_is_converted_to_negative_surplus(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = make_available_app()
    app.controller = FakeGridController()

    asyncio.run(app.handle_message("minyad/grid/net_power_w", b"1200"))

    assert app.controller.samples == [-1200]
    assert ("control", "state", "DISCHARGING") in app.mqtt.published
    assert stored["state"] == "DISCHARGING"


def test_start_charging_tracks_current_grid_export(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.latest_grid_power_w = -500

    asyncio.run(app.start_charging())

    assert ("control", "charge_w", 500) in app.mqtt.published


def test_active_charge_target_rebalances_observed_export():
    app = control_main.ControlApp()
    app.latest_battery_power_w = -300
    app.latest_grid_power_w = -200

    assert app.charge_target_w() == 500


def test_active_charge_target_trims_observed_import():
    app = control_main.ControlApp()
    app.latest_battery_power_w = -500
    app.latest_grid_power_w = 125

    assert app.charge_target_w() == 375


def test_start_discharging_tracks_current_grid_import(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.settings = {"max_discharge_w": 5000}
    app.latest_grid_power_w = 635

    asyncio.run(app.start_discharging())

    assert ("control", "discharge_w", 635) in app.mqtt.published
    assert ("control", "discharge_w", 5000) not in app.mqtt.published


def test_discharge_target_ignores_grid_export():
    app = control_main.ControlApp()
    app.latest_grid_power_w = -133

    assert app.discharge_target_w() == 0


def test_active_discharge_target_rebalances_observed_import():
    app = control_main.ControlApp()
    app.latest_battery_power_w = 1117
    app.latest_grid_power_w = 1334

    assert app.discharge_target_w() == 2451


def test_active_discharge_target_trims_observed_export():
    app = control_main.ControlApp()
    app.latest_battery_power_w = 1012
    app.latest_grid_power_w = -345

    assert app.discharge_target_w() == 667


class FakeHysteresisController:
    def __init__(self, state=None):
        self.start_w = 500
        self.discharge_start_w = -300
        self._state = state or control_main.ControlState.IDLE
        self.override_mode = control_main.OverrideMode.NONE
        self.ticked = []
        self._charge_since = None
        self._discharge_since = None
        self._stop_since = None
        self._cooldown_until = None
        self._lock = __import__("threading").RLock()

    @property
    def state(self):
        return self._state

    def tick(self, surplus_w):
        self.ticked.append(surplus_w)
        return None


def make_app_with_soc(soc, controller_state=None, settings=None):
    app = make_available_app()
    app.latest_battery_soc = soc
    app.settings = settings or {}
    app.controller = FakeHysteresisController(controller_state)
    return app


def test_soc_guard_masks_discharge_trigger_at_floor(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_app_with_soc(soc=20)  # at floor default

    # Surplus of -400 would normally trigger discharge; guard must clamp it
    surplus = app._apply_soc_guard(-400)

    assert surplus > app.controller.discharge_start_w


def test_soc_guard_masks_charge_trigger_at_ceiling(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_app_with_soc(soc=90)  # at ceiling default

    surplus = app._apply_soc_guard(800)

    assert surplus < app.controller.start_w


def test_soc_guard_forces_idle_when_discharging_at_floor(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_app_with_soc(soc=15, controller_state=control_main.ControlState.DISCHARGING)

    app._apply_soc_guard(-400)

    assert app.controller.state is control_main.ControlState.IDLE


def test_soc_guard_does_not_interfere_above_floor(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_app_with_soc(soc=50)

    surplus = app._apply_soc_guard(-400)

    assert surplus == -400


def test_battery_soc_topic_updates_latest_soc(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = control_main.ControlApp()

    asyncio.run(app.handle_battery_topic("minyad/battery/soc", "67"))

    assert app.latest_battery_soc == 67


def test_battery_power_topic_updates_latest_power(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = control_main.ControlApp()

    asyncio.run(app.handle_battery_topic("minyad/battery/power_w", "1012"))

    assert app.latest_battery_power_w == 1012
    assert stored["power_w"] == 1012


def test_idle_export_while_battery_discharging_trims_discharge_setpoint(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.settings = {"max_discharge_w": 5000}
    app.controller = FakeHysteresisController(control_main.ControlState.IDLE)
    app.latest_battery_power_w = 1012

    asyncio.run(app.handle_message("minyad/grid/net_power_w", b"-345"))

    assert app.controller.state is control_main.ControlState.DISCHARGING
    assert ("control", "state", "HYSTERESE") in app.mqtt.published
    assert ("control", "discharge_w", 667) in app.mqtt.published
    assert app.controller.ticked == [345]


def test_idle_import_while_battery_discharging_adopts_and_increases_setpoint(monkeypatch):
    stored = {}

    async def capture_store_status(**values):
        stored.update(values)

    monkeypatch.setattr(control_main, "store_status", capture_store_status)
    app = make_available_app()
    app.settings = {"max_discharge_w": 5000}
    app.controller = FakeHysteresisController(control_main.ControlState.IDLE)
    app.latest_battery_power_w = 561

    asyncio.run(app.handle_message("minyad/grid/net_power_w", b"472"))

    assert app.controller.state is control_main.ControlState.DISCHARGING
    assert ("control", "state", "HYSTERESE") in app.mqtt.published
    assert stored["state"] == "HYSTERESE"
    assert ("control", "discharge_w", 1033) in app.mqtt.published
    assert ("control", "discharge_w", 472) not in app.mqtt.published
    assert app.controller.ticked == [-472]


def test_active_charging_sample_does_not_republish_setpoint(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.controller = FakeHysteresisController(control_main.ControlState.CHARGING)
    app.latest_grid_power_w = -600
    app.latest_battery_power_w = -400
    app.setpoint_w = 500

    asyncio.run(app.handle_message("minyad/grid/net_power_w", b"-200"))

    assert ("control", "charge_w", 600) not in app.mqtt.published
    assert not any(measurement == "charge_w" for _, measurement, _ in app.mqtt.published)
    assert app.controller.ticked == [200]


def test_charge_transition_publishes_initial_setpoint(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.controller = FakeHysteresisController(control_main.ControlState.IDLE)
    app.latest_grid_power_w = -700

    def tick(surplus_w):
        app.controller.ticked.append(surplus_w)
        app.controller._state = control_main.ControlState.CHARGING
        return control_main.ControlState.CHARGING

    app.controller.tick = tick

    asyncio.run(app.handle_message("minyad/grid/net_power_w", b"-700"))

    assert ("control", "charge_w", 700) in app.mqtt.published
    assert app.controller.ticked == [700]


def test_control_service_publishes_two_actuator_values_without_modbus(monkeypatch):
    monkeypatch.setattr(control_main, "store_status", noop_store_status)
    app = make_available_app()
    app.settings = {"max_discharge_w": 5000}
    app.latest_grid_power_w = 450
    app.latest_battery_power_w = 150

    asyncio.run(app.publish_discharge_setpoint(app.discharge_target_w()))

    assert ("control", "charge_w", 0) in app.mqtt.published
    assert ("control", "discharge_w", 600) in app.mqtt.published
    assert all(topic[1] != "modbus" for topic in app.mqtt.published)
