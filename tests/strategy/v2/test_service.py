import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import pytest

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/db")

from minyad.strategy.v2.reasons import adjusted_decision_log_due, adjustment_reason_suffix
from minyad.strategy.v2.setpoint_log import build_setpoint_log_insert
from minyad.strategy.v2 import service as service_module
from minyad.strategy.v2.models import DayPlan, ExecutorState, StrategyDecision


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
        await asyncio.sleep(0)
        return None

    async def no_plan(*args, **kwargs):
        await asyncio.sleep(0)
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
        await asyncio.sleep(0)
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


class FakeMqtt:
    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload, retain=False, qos=0):
        self.published.append((topic, str(payload), retain))

    def subscribe(self, topic, handler):
        pass

    def start(self):
        pass


def make_service() -> service_module.StrategyService:
    svc = service_module.StrategyService()
    svc.mqtt = FakeMqtt()
    return svc


def make_plan() -> DayPlan:
    return DayPlan(
        date=date(2026, 7, 3),
        solar_mode="sunny",
        forecast_ghi_kwh_m2=5.5,
        effective_soc_floor=25,
        effective_soc_ceiling=90,
        grid_charge_windows=[
            (
                datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 3, 3, 0, tzinfo=timezone.utc),
            )
        ],
        price_discharge_windows=[
            (
                datetime(2026, 7, 3, 19, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 3, 20, 0, tzinfo=timezone.utc),
            )
        ],
        planned_soc_at_sunset=70,
        valid_until=datetime(2026, 7, 4, 0, 0, tzinfo=timezone.utc),
        reason="test plan",
    )


def test_publish_setpoint_uses_charge_discharge_topics():
    svc = make_service()
    svc.publish_setpoint(500)
    svc.publish_setpoint(-300)
    svc.publish_setpoint(0)

    assert svc.mqtt.published == [
        (service_module.TOPIC_SETPOINT, "500", True),
        ("minyad/control/charge_w", "500", False),
        ("minyad/control/discharge_w", "0", False),
        (service_module.TOPIC_SETPOINT, "-300", True),
        ("minyad/control/charge_w", "0", False),
        ("minyad/control/discharge_w", "300", False),
        (service_module.TOPIC_SETPOINT, "0", True),
        ("minyad/control/charge_w", "0", False),
        ("minyad/control/discharge_w", "0", False),
    ]


def test_publish_active_plan_decision_and_floor_telemetry():
    svc = make_service()
    svc.plan = make_plan()
    svc.floor_schedule = type(
        "Schedule",
        (),
        {"current_floor": 31.25, "drift_factor": 1.23456, "remaining_expected_adjusted_wh": 987.65},
    )()
    decision = StrategyDecision(
        datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        250,
        61.0,
        100,
        800,
        "grid_charge",
        "cheap power",
        date(2026, 7, 3),
        True,
        False,
    )

    svc.publish_active_plan()
    svc.publish_floor_telemetry()
    svc.publish_decision(decision)

    topics = {topic: payload for topic, payload, _ in svc.mqtt.published}
    assert '"solar_mode": "sunny"' in topics[service_module.TOPIC_ACTIVE]
    assert topics[service_module.TOPIC_SOC_FLOOR] == "31.25"
    assert topics[service_module.TOPIC_FLOOR_DRIFT] == "1.235"
    assert topics[service_module.TOPIC_FLOOR_REMAINING] == "987.6"
    assert '"mode": "grid_charge"' in topics[service_module.TOPIC_DECISION]


def test_handle_message_updates_state_and_dispatches_callbacks():
    svc = make_service()
    seen = []

    async def reload():
        seen.append(("reload", None))

    async def apply_payload(payload):
        seen.append(("override", payload))

    def set_prices(payload):
        seen.append(("prices", payload))

    async def tick():
        seen.append(("tick", None))

    svc.reload = reload
    svc.overrides.apply_payload = apply_payload
    svc.planner.set_prices = set_prices
    svc.tick = tick

    asyncio.run(svc.handle_message("minyad/strategy/reload", b""))
    asyncio.run(svc.handle_message("minyad/control/override", b'{"mode":"idle"}'))
    asyncio.run(svc.handle_message("minyad/trade/prices", b"[1, 2]"))
    asyncio.run(svc.handle_message("minyad/forecast/power_w", b"123.9"))
    asyncio.run(svc.handle_message("minyad/bridge/last_seen", b"2026-07-03T10:00:00Z"))
    asyncio.run(svc.handle_message("minyad/battery/soc", b"62.5"))
    asyncio.run(svc.handle_message("minyad/battery/power_w", b"150.2"))
    asyncio.run(svc.handle_message("minyad/battery/voltage", b"52.1"))
    asyncio.run(svc.handle_message("minyad/dsmr/net_power_w", b"999"))

    assert seen == [
        ("reload", None),
        ("override", '{"mode":"idle"}'),
        ("prices", [1, 2]),
        ("tick", None),
    ]
    assert svc.state.solar_forecast_w == 123
    assert svc.state.bridge_last_seen == datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    assert svc.state.battery_soc == 62.5
    assert svc.state.battery_power_w == 150
    assert svc.state.battery_voltage == 52.1
    assert svc.state.net_grid_w == 999


def test_tick_returns_when_executor_or_plan_missing():
    svc = make_service()
    asyncio.run(svc._tick_locked())
    assert svc.last_decision is None


def test_tick_applies_adjustments_logs_and_updates_state():
    svc = make_service()
    plan = make_plan()
    decision = StrategyDecision(
        datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        100,
        55.0,
        20,
        500,
        "normal",
        "raw",
        date(2026, 7, 3),
        False,
        False,
    )
    events = []

    svc.plan = plan
    svc.executor = type("Executor", (), {"tick": lambda self, state: decision})()
    svc.state = ExecutorState(net_grid_w=20, battery_soc=55.0)
    svc.update_floor_schedule = lambda now: events.append(("floor_update", now))

    async def apply_with_reason(setpoint, state, plan_arg):
        return setpoint + 50, "override: raise"

    svc.overrides.apply_with_reason = apply_with_reason
    svc.overrides.bypasses_soc_limits = lambda: False
    svc.guard.apply_with_reason = lambda setpoint, state, plan_arg, now, skip_soc_limits: (setpoint - 25, "guard: trim")
    svc.settings.int = lambda key: 300
    svc.publish_setpoint = lambda setpoint: events.append(("setpoint", setpoint))
    svc.publish_decision = lambda decision_arg: events.append(("decision", decision_arg.reason, decision_arg.setpoint_w))

    async def log_setpoint(decision_arg):
        events.append(("log", decision_arg.setpoint_w))

    svc.log_setpoint = log_setpoint

    asyncio.run(svc.tick())

    assert ("setpoint", 125) in events
    assert ("decision", "raw; override: raise; guard: trim", 125) in events
    assert ("log", 125) in events
    assert svc.state.current_setpoint_w == 125


def test_recalculate_refreshes_profile_resets_floor_and_publishes(monkeypatch):
    svc = make_service()
    plan = make_plan()
    events = []
    svc.floor_schedule = object()

    async def recalculate():
        return plan

    svc.planner.recalculate = recalculate

    class Executor:
        def set_plan(self, new_plan):
            events.append(("set_plan", new_plan))

    svc.executor = Executor()

    async def refresh():
        events.append(("refresh", None))

    svc.refresh_consumption_profile = refresh
    svc.guard.set_floor_schedule = lambda schedule: events.append(("guard_floor", schedule))
    svc.publish_active_plan = lambda: events.append(("publish", svc.plan))

    asyncio.run(svc.recalculate())

    assert svc.plan is plan
    assert svc.floor_schedule is None
    assert events == [
        ("set_plan", plan),
        ("refresh", None),
        ("guard_floor", None),
        ("publish", plan),
    ]


def test_household_load_and_parse_helpers():
    svc = make_service()
    svc.state = ExecutorState(net_grid_w=-100, battery_power_w=25)
    assert svc._household_load_w() == 0.0
    svc.state = ExecutorState(net_grid_w=300, battery_power_w=25)
    assert svc._household_load_w() == 325.0
    assert service_module._parse_local_time("06:30").hour == 6
    assert service_module._parse_dt("2026-07-03T10:00:00").tzinfo == timezone.utc


class FakeScheduler:
    instances = []

    def __init__(self, *, timezone):
        self.timezone = timezone
        self.jobs = []
        self.started = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))

    def start(self):
        self.started = True


def test_start_scheduler_uses_configured_daily_recalculate_time(monkeypatch):
    FakeScheduler.instances = []
    svc = make_service()
    svc.settings.get = lambda key, default=None: "06:45"
    monkeypatch.setattr(service_module, "AsyncIOScheduler", FakeScheduler)

    svc._start_scheduler()

    scheduler = FakeScheduler.instances[0]
    assert scheduler.started
    assert scheduler.jobs == [
        (
            svc.recalculate,
            "cron",
            {"hour": 6, "minute": 45, "id": "daily_strategy_recalculate", "replace_existing": True},
        )
    ]
    assert svc.scheduler is scheduler


def test_on_mqtt_queues_message_when_loop_is_available(monkeypatch):
    svc = make_service()
    calls = []

    class Loop:
        def call_soon_threadsafe(self, func, *args):
            calls.append((func, args))

    svc.loop = Loop()
    monkeypatch.setattr(service_module.asyncio, "create_task", lambda coro: ("task", coro))

    svc._on_mqtt("minyad/grid/net_power_w", b"10")

    assert len(calls) == 1
    calls[0][1][0].close()
