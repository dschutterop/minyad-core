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
from minyad.strategy.v3.models import ExecutorState, Slot, SlotPlan, StrategyDecision, TrackerResult


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
        await asyncio.sleep(0)
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


def make_plan(*, status: str = "Optimal") -> SlotPlan:
    now = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    return SlotPlan(
        generated_at=now,
        valid_from=now,
        slot_seconds=900,
        soc_start_pct=50.0,
        slots=[
            Slot(
                start=now,
                soc_target_pct=51.0,
                planned_grid_charge_w=100,
                planned_export_w=20,
                pv_forecast_w=800,
                load_forecast_w=300,
                price_import=0.21,
                price_export=0.08,
                charge_w=200,
                discharge_w=0,
                curtailment_w=10,
                price_source="day_ahead",
                cloud_cover_pct=40.0,
            )
        ],
        solver_status=status,
        market_signal_ids=["sig-1"],
        constraint_reasons=["price cap"],
    )


def test_handle_message_updates_state_for_supported_topics():
    svc = make_service(shadow_mode=True)
    calls = []

    async def tick():
        await asyncio.sleep(0)
        calls.append("tick")

    svc.tick = tick
    asyncio.run(svc.handle_message("minyad/battery/soc", b"61.5"))
    asyncio.run(svc.handle_message("minyad/battery/power_w", b"123"))
    asyncio.run(svc.handle_message("minyad/battery/voltage_v", b"52.4"))
    asyncio.run(svc.handle_message("minyad/solar/production_w", b"456.7"))
    asyncio.run(svc.handle_message("minyad/bridge/last_seen", b"2026-07-03T10:00:00Z"))
    asyncio.run(svc.handle_message("minyad/grid/net_power_w", b"777"))

    assert svc.state.battery_soc == 61.5
    assert svc.state.battery_power_w == 123
    assert svc.state.battery_voltage == 52.4
    assert svc._pv_raw_w == 456
    assert svc.state.bridge_last_seen == datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    assert svc.state.net_grid_w == 777
    assert calls == ["tick"]


def test_handle_message_dispatches_reload_override_prices_and_ignores_bad_json():
    svc = make_service(shadow_mode=True)
    seen = []

    async def reload_settings():
        await asyncio.sleep(0)
        seen.append(("reload", None))

    async def apply_payload(payload):
        await asyncio.sleep(0)
        seen.append(("override", payload))

    def on_prices(day, points):
        seen.append(("prices", day, points))

    async def recalculate_plan():
        await asyncio.sleep(0)
        seen.append(("recalculate", None))

    svc.settings.reload = reload_settings
    svc.overrides.apply_payload = apply_payload
    svc.planner.on_prices = on_prices
    svc.recalculate_plan = recalculate_plan

    asyncio.run(svc.handle_message("minyad/strategy/reload", b""))
    asyncio.run(svc.handle_message("minyad/control/override", b'{"mode":"force_idle"}'))
    asyncio.run(svc.handle_message("minyad/trade/prices/da/2026-07-03/full", b"[1, 2]"))
    asyncio.run(svc.handle_message("minyad/trade/prices/da/2026-07-04/full", b"{bad"))
    asyncio.run(svc.handle_message("minyad/market/signals", b"{bad"))
    asyncio.run(svc.handle_message("minyad/strategy/setpoint_w", b"-250.5"))

    assert seen == [
        ("reload", None),
        ("override", '{"mode":"force_idle"}'),
        ("prices", "2026-07-03", [1, 2]),
        ("recalculate", None),
    ]
    assert svc.v2_setpoint_w == -250


def test_effective_pv_now_zeros_missing_or_stale_values():
    svc = make_service(shadow_mode=True)
    now = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    assert svc._effective_pv_now_w(now) == 0

    svc._pv_raw_w = 900
    svc._pv_last_seen = now - timedelta(seconds=service_module.PV_STALE_SECONDS)
    assert svc._effective_pv_now_w(now) == 900

    svc._pv_last_seen = now - timedelta(seconds=service_module.PV_STALE_SECONDS + 1)
    assert svc._effective_pv_now_w(now) == 0


def test_publish_plan_decision_surplus_and_floor_payloads():
    svc = make_service(shadow_mode=False)
    plan = make_plan()
    tracker_result = TrackerResult(bias_w=12, floor_dyn_pct=25.5, ceil_dyn_pct=91.25)
    decision = StrategyDecision(
        datetime(2026, 7, 3, 10, 1, tzinfo=timezone.utc),
        -300,
        61.0,
        100,
        12,
        25.5,
        91.25,
        "tracking",
        "Optimal",
        ["sig-1"],
        ["price cap"],
    )

    svc.publish_plan(plan)
    svc.publish_surplus_forecast(plan)
    svc.publish_floor_telemetry(tracker_result)
    svc.publish_decision(decision, tracker_result)

    topics = {topic: payload for topic, payload, _ in svc.mqtt.published}
    assert "minyad/strategy/plan" in topics
    assert '"market_signal_ids": ["sig-1"]' in topics["minyad/strategy/plan"]
    assert '"surplus_w": 300' in topics[service_module.TOPIC_SURPLUS_FORECAST]
    assert topics["minyad/strategy/soc_floor"] == "25.50"
    assert '"constraint_reasons": ["price cap"]' in topics["minyad/strategy/decision"]


def test_slot_plan_interpolates_soc_and_finds_containing_slot():
    plan = make_plan()
    first_slot = plan.slots[0]
    before = plan.valid_from - timedelta(minutes=1)
    middle = plan.valid_from + timedelta(seconds=450)
    after = plan.valid_from + timedelta(seconds=1800)

    assert first_slot.surplus_w == 300
    assert plan.slot_containing(plan.valid_from + timedelta(seconds=1)) is first_slot
    assert plan.slot_containing(after) is None
    assert plan.soc_plan_pct(before) == plan.soc_start_pct
    assert plan.soc_plan_pct(middle) == 50.5
    assert plan.soc_plan_pct(after) == first_slot.soc_target_pct
    assert service_module._prometheus_solve_status("Optimal") == "optimal"
    assert service_module._prometheus_solve_status("infeasible solution") == "infeasible"
    assert service_module._prometheus_solve_status("time limit") == "timeout"
    assert service_module._prometheus_solve_status("weird") == "error"


def test_recalculate_plan_publishes_surplus_unless_fallback():
    svc = make_service(shadow_mode=False)
    published = []
    plans = [make_plan(status="Optimal"), make_plan(status="FALLBACK")]

    async def recalculate(now, soc):
        await asyncio.sleep(0)
        published.append(("recalculate", soc))
        return plans.pop(0)

    svc.planner.recalculate = recalculate
    svc.publish_plan = lambda plan: published.append(("plan", plan.solver_status))
    svc.publish_surplus_forecast = lambda plan: published.append(("surplus", plan.solver_status))

    asyncio.run(svc.recalculate_plan())
    asyncio.run(svc.recalculate_plan())

    assert published == [
        ("recalculate", None),
        ("plan", "Optimal"),
        ("surplus", "Optimal"),
        ("recalculate", None),
        ("plan", "FALLBACK"),
    ]


def test_tick_applies_override_guard_logs_shadow_and_updates_state():
    svc = make_service(shadow_mode=True)
    now = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    plan = make_plan()
    tracker_result = TrackerResult(bias_w=5, floor_dyn_pct=30.0, ceil_dyn_pct=90.0)
    decision = StrategyDecision(now, 100, 55.0, 20, 5, 30.0, 90.0, "raw", "Optimal")
    events = []

    svc.state = ExecutorState(net_grid_w=20, battery_soc=55.0)
    svc.planner.current_plan = lambda now_arg, soc: plan
    svc.tracker.evaluate = lambda now_arg, soc, plan_arg: tracker_result
    svc.executor.tick = lambda state, plan_arg, tracker: decision

    async def apply_with_reason(setpoint, state, floor, ceiling):
        await asyncio.sleep(0)
        return setpoint + 50, "override: raise"

    svc.overrides.apply_with_reason = apply_with_reason
    svc.overrides.bypasses_soc_limits = lambda: False
    svc.guard.apply_with_reason = lambda setpoint, state, floor, ceiling, now_arg, skip_soc_limits: (setpoint - 25, "guard: trim")
    svc.publish_decision = lambda decision_arg, tracker: events.append(("decision", decision_arg.reason, decision_arg.setpoint_w))
    svc.publish_setpoint = lambda setpoint: events.append(("setpoint", setpoint))
    svc.publish_floor_telemetry = lambda tracker: events.append(("floor", tracker.floor_dyn_pct))

    async def log_shadow(decision_arg):
        await asyncio.sleep(0)
        events.append(("shadow", decision_arg.setpoint_w))

    svc.log_shadow = log_shadow

    asyncio.run(svc.tick())

    assert ("setpoint", 125) in events
    assert ("decision", "raw; override: raise; guard: trim", 125) in events
    assert ("shadow", 125) in events
    assert ("floor", 30.0) in events
    assert svc.state.current_setpoint_w == 125


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


class FakeLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, func, *args):
        self.calls.append((func, args))


def test_start_scheduler_registers_interval_and_daily_jobs(monkeypatch):
    FakeScheduler.instances = []
    svc = make_service(shadow_mode=True)
    svc.settings = type("Settings", (), {"plan_interval_min": 7})()
    monkeypatch.setattr(service_module, "AsyncIOScheduler", FakeScheduler)

    svc._start_scheduler()

    scheduler = FakeScheduler.instances[0]
    assert scheduler.started
    assert [job[2]["id"] for job in scheduler.jobs] == [
        "strategy3_plan_interval",
        "strategy3_daily_calibration",
        "strategy3_daily_forecast_accuracy",
    ]
    assert scheduler.jobs[0][1] == "interval"
    assert scheduler.jobs[0][2]["minutes"] == 7
    assert scheduler.jobs[1][2]["hour"] == 6
    assert svc.scheduler is scheduler


def test_run_helpers_schedule_coroutines_on_loop(monkeypatch):
    svc = make_service(shadow_mode=True)
    loop = FakeLoop()
    svc.loop = loop
    created = []
    monkeypatch.setattr(service_module.asyncio, "create_task", lambda coro: created.append(coro) or ("task", coro))
    monkeypatch.setattr(service_module.forecast_accuracy, "run_daily_accuracy_job", lambda *args, **kwargs: asyncio.sleep(0))
    svc.planner.daily_calibration = lambda when: asyncio.sleep(0)

    svc._run_recalculate_plan()
    svc._run_daily_calibration()
    svc._run_daily_forecast_accuracy()

    assert len(loop.calls) == 3
    assert all(call[0] is service_module.asyncio.create_task for call in loop.calls)
    assert len(created) == 0
    for _, args in loop.calls:
        coro = args[0]
        assert hasattr(coro, "send")
        coro.close()


def test_on_mqtt_queues_message_when_loop_is_available(monkeypatch):
    svc = make_service(shadow_mode=True)
    loop = FakeLoop()
    svc.loop = loop
    monkeypatch.setattr(service_module.asyncio, "create_task", lambda coro: ("task", coro))

    svc._on_mqtt("minyad/grid/net_power_w", b"10")

    assert len(loop.calls) == 1
    loop.calls[0][1][0].close()
