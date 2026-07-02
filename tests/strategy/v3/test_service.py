import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

# shared.db builds its async engine at import time from DB_URL; these tests never touch a real
# database (mqtt/db calls are stubbed out), but importing minyad.strategy.v3.service still pulls
# shared.db in transitively, so a syntactically valid dummy URL is enough to satisfy the import.
os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/db")

from minyad.strategy.v3.reasons import adjusted_decision_log_due, adjustment_reason_suffix
from minyad.strategy.v3.setpoint_log import build_setpoint_log_insert
from minyad.strategy.v3 import service as service_module


def test_setpoint_log_insert_includes_battery_power_when_column_exists():
    sql = build_setpoint_log_insert(
        {"setpoint_w", "battery_soc_at_time", "grid_power_at_time", "battery_power_at_time", "setpoint_delta", "trigger_reason", "ack_received"}
    )
    assert "setpoint_w" in sql
    assert "battery_power_at_time" in sql


def test_adjustment_reason_suffix_names_guard_and_override():
    assert adjustment_reason_suffix("override: force_idle", "guard: bridge stale (61s > 60s)") == (
        "; override: force_idle; guard: bridge stale (61s > 60s)"
    )


def test_adjusted_decision_log_due_when_unchanged_suppression_persists():
    now = datetime(2026, 6, 27, 23, 54, tzinfo=timezone.utc)
    last = now - timedelta(seconds=300)
    assert adjusted_decision_log_due(adjusted=True, setpoint_changed=False, now=now, last_adjustment_log_at=last, interval_seconds=300)


class FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload, retain=False, qos=0):
        self.published.append((topic, str(payload), retain))

    def subscribe(self, topic, handler):
        pass

    def start(self):
        pass


def make_service(shadow_mode: bool) -> service_module.StrategyService:
    svc = service_module.StrategyService()
    svc.shadow_mode = shadow_mode
    svc.mqtt = FakeMqtt()
    return svc


def test_invariant_1_sign_convention_positive_is_charge():
    svc = make_service(shadow_mode=False)
    svc.publish_setpoint(500)
    topics = {t: p for t, p, _ in svc.mqtt.published}
    assert topics["minyad/control/charge_w"] == "500"
    assert topics["minyad/control/discharge_w"] == "0"


def test_invariant_1_sign_convention_negative_is_discharge():
    svc = make_service(shadow_mode=False)
    svc.publish_setpoint(-500)
    topics = {t: p for t, p, _ in svc.mqtt.published}
    assert topics["minyad/control/charge_w"] == "0"
    assert topics["minyad/control/discharge_w"] == "500"


def test_invariant_1_sign_convention_zero_publishes_both_zero():
    svc = make_service(shadow_mode=False)
    svc.publish_setpoint(0)
    topics = {t: p for t, p, _ in svc.mqtt.published}
    assert topics["minyad/control/charge_w"] == "0"
    assert topics["minyad/control/discharge_w"] == "0"


def test_invariant_13_shadow_mode_never_touches_control_or_primary_setpoint_topic():
    svc = make_service(shadow_mode=True)
    svc.publish_setpoint(500)
    topics = [t for t, _, _ in svc.mqtt.published]
    assert "minyad/control/charge_w" not in topics
    assert "minyad/control/discharge_w" not in topics
    assert "minyad/strategy/setpoint_w" not in topics
    assert "minyad/strategy3/setpoint_w" in topics


def test_primary_mode_publishes_the_real_setpoint_topic():
    svc = make_service(shadow_mode=False)
    svc.publish_setpoint(500)
    topics = [t for t, _, _ in svc.mqtt.published]
    assert "minyad/strategy/setpoint_w" in topics
    assert "minyad/strategy3/setpoint_w" not in topics


def test_invariant_22_market_signal_in_shadow_mode_does_not_dispatch():
    svc = make_service(shadow_mode=True)
    seen = {}

    def on_market_signal(payload, now=None):
        seen["payload"] = payload

    async def recalculate_plan():
        seen["recalculated"] = True

    svc.planner.on_market_signal = on_market_signal
    svc.recalculate_plan = recalculate_plan

    signal_payload = {
        "id": "sig-1",
        "source": "minyad-trade",
        "type": "price_vector",
        "created_at": "2026-07-03T09:45:00+02:00",
        "valid_from": "2026-07-03T10:00:00+02:00",
        "valid_until": "2026-07-03T11:00:00+02:00",
        "priority": 50,
        "hard": False,
        "payload": {"slot_seconds": 900, "slots": []},
    }

    asyncio.run(svc.handle_message("minyad/market/signals", json_dumps(signal_payload).encode()))

    assert seen["payload"] == signal_payload
    assert seen["recalculated"] is True
    assert all(not topic.startswith("minyad/control/") for topic, _, _ in svc.mqtt.published)
    assert all(topic != "minyad/strategy/setpoint_w" for topic, _, _ in svc.mqtt.published)


def test_invariant_14_tick_lock_serializes_concurrent_ticks():
    svc = make_service(shadow_mode=True)
    order: list[str] = []

    async def slow_tick_locked():
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")

    svc._tick_locked = slow_tick_locked

    async def run():
        await asyncio.gather(svc.tick(), svc.tick())

    asyncio.run(run())
    assert order == ["start", "end", "start", "end"]


def json_dumps(value):
    import json

    return json.dumps(value)
