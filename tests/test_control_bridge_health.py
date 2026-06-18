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

    app.bridge_last_seen = datetime.now(timezone.utc) - timedelta(seconds=control_main.BRIDGE_LAST_SEEN_STALE_SECONDS + 5)
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
