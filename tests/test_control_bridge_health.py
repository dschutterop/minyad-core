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

    assert app.bridge_is_available is False

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
