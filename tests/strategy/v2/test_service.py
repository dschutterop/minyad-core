import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/db")

from minyad.strategy.v2.reasons import adjusted_decision_log_due, adjustment_reason_suffix
from minyad.strategy.v2.setpoint_log import build_setpoint_log_insert
from minyad.strategy.v2 import service as service_module


def test_setpoint_log_insert_includes_battery_power_when_column_exists():
    sql = build_setpoint_log_insert(
        {
            "setpoint_w",
            "battery_soc_at_time",
            "grid_power_at_time",
            "battery_power_at_time",
            "setpoint_delta",
            "trigger_reason",
            "ack_received",
        }
    )
    assert "setpoint_w" in sql
    assert "battery_power_at_time" in sql
    assert ":battery_power" in sql
    assert "setpoint_delta" in sql
    assert "trigger_reason" in sql
    assert "ack_received" in sql


def test_setpoint_log_insert_supports_legacy_schema_without_newer_columns():
    sql = build_setpoint_log_insert(
        {
            "charge_rate_w",
            "battery_soc_at_time",
            "grid_power_at_time",
        }
    )
    assert "charge_rate_w" in sql
    assert "battery_power_at_time" not in sql
    assert ":battery_power" not in sql
    assert "setpoint_delta" not in sql
    assert "trigger_reason" not in sql
    assert "ack_received" not in sql


def test_adjustment_reason_suffix_names_guard_and_override():
    assert adjustment_reason_suffix("override: force_idle", "guard: bridge stale (61s > 60s)") == (
        "; override: force_idle; guard: bridge stale (61s > 60s)"
    )


def test_adjustment_reason_suffix_keeps_legacy_fallback():
    assert adjustment_reason_suffix(None, None) == "; guard/override adjusted setpoint"


def test_adjusted_decision_log_due_when_unchanged_suppression_persists():
    now = datetime(2026, 6, 27, 23, 54, tzinfo=timezone.utc)
    last = now - timedelta(seconds=300)
    assert adjusted_decision_log_due(
        adjusted=True,
        setpoint_changed=False,
        now=now,
        last_adjustment_log_at=last,
        interval_seconds=300,
    )


def test_adjusted_decision_log_not_due_before_interval():
    now = datetime(2026, 6, 27, 23, 54, tzinfo=timezone.utc)
    last = now - timedelta(seconds=299)
    assert not adjusted_decision_log_due(
        adjusted=True,
        setpoint_changed=False,
        now=now,
        last_adjustment_log_at=last,
        interval_seconds=300,
    )


def test_v2_non_primary_does_not_start_mqtt_or_scheduler(monkeypatch):
    async def noop_async(*args, **kwargs):
        return None

    async def no_plan(*args, **kwargs):
        return None

    class BlockedMqtt:
        def subscribe(self, *args, **kwargs):
            raise AssertionError("v2 should not subscribe when it is not primary")

        def start(self):
            raise AssertionError("v2 should not start MQTT when it is not primary")

    svc = service_module.StrategyService()
    svc.mqtt = BlockedMqtt()
    health_started = False

    async def fake_health_server():
        nonlocal health_started
        health_started = True

    monkeypatch.setattr(service_module, "STRATEGY_V2_PRIMARY", False)
    monkeypatch.setattr(svc.settings, "load", noop_async)
    monkeypatch.setattr(svc.overrides, "load", noop_async)
    monkeypatch.setattr(svc.planner, "load_plan", no_plan)
    monkeypatch.setattr(svc, "refresh_consumption_profile", noop_async)
    monkeypatch.setattr(svc, "publish_active_plan", lambda: pytest.fail("v2 should not publish an active plan"))
    monkeypatch.setattr(svc, "_start_scheduler", lambda: pytest.fail("v2 should not start its scheduler"))
    monkeypatch.setattr(svc, "_run_health_server", fake_health_server)

    asyncio.run(svc.start())

    assert health_started
