"""Strategy v3 service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

from .consumption_profile import load_baseline_consumption_profile

from .constants import Settings
from .executor import StrategyExecutor
from . import forecast_accuracy
from .models import ExecutorState, SlotPlan, StrategyDecision, TrackerResult
from .override import OverrideManager
from .planner import RollingPlanner
from .reasons import adjusted_decision_log_due, adjustment_reason_suffix
from .setpoint_log import build_setpoint_log_insert
from .soc_guard import SoCGuard
from .tracker import TrajectoryTracker

configure_container_logging(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
LOGGER = logging.getLogger(__name__)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
PV_STALE_SECONDS = 300
# Cross-service secret, same pattern as MINYAD_API_SECRET/VESPER_API_SECRET already used the
# other way around (Vesper polling Minyad's surplus endpoint) — env var, not a settings-table
# row, since it's a shared credential rather than a tunable parameter.
VESPER_API_URL = os.getenv("VESPER_API_URL", "")
VESPER_API_SECRET = os.getenv("VESPER_API_SECRET", "")
METRICS_PORT = int(os.getenv("METRICS_PORT", "9104"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "0.0.0.0")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))

PROMETHEUS_REGISTRY = CollectorRegistry()
BUILD_INFO = Gauge("minyad_strategy_build_info", "Build and version information for minyad-strategy-v3.", ["version"], registry=PROMETHEUS_REGISTRY)
ERRORS_TOTAL = Counter("minyad_strategy_errors_total", "Errors observed by minyad-strategy-v3.", ["type"], registry=PROMETHEUS_REGISTRY)
SOLVE_DURATION_SECONDS = Histogram(
    "minyad_strategy_solve_duration_seconds",
    "Duration of strategy v3 plan recalculations.",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=PROMETHEUS_REGISTRY,
)
SOLVE_STATUS_TOTAL = Counter("minyad_strategy_solve_status_total", "Strategy v3 solve outcomes.", ["status"], registry=PROMETHEUS_REGISTRY)
PLAN_HORIZON_HOURS = Gauge("minyad_strategy_plan_horizon_hours", "Strategy v3 plan horizon in hours.", registry=PROMETHEUS_REGISTRY)
LAST_PLAN_TIMESTAMP_SECONDS = Gauge(
    "minyad_strategy_last_plan_timestamp_seconds",
    "Unix timestamp of the most recent strategy v3 plan.",
    registry=PROMETHEUS_REGISTRY,
)
PLANNED_BATTERY_POWER_WATTS = Gauge(
    "minyad_strategy_planned_battery_power_watts",
    "Planned battery power for the next interval; positive means discharge, negative means charge.",
    registry=PROMETHEUS_REGISTRY,
)


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    LOGGER.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


SHADOW_MODE = _truthy(os.getenv("SHADOW_MODE", "true"))

# Topics v2 also owns: while in shadow mode these must stay untouched, so shadow output goes
# to a parallel minyad/strategy3/* namespace (spec 11.1). surplus_forecast is v3-only (no v2
# equivalent) so it is always published under its real name, shadow or not.
_TOPIC_MAP = {
    True: {
        "setpoint_w": "minyad/strategy3/setpoint_w",
        "plan": "minyad/strategy3/plan",
        "decision": "minyad/strategy3/decision",
        "soc_floor": "minyad/strategy3/soc_floor",
    },
    False: {
        "setpoint_w": "minyad/strategy/setpoint_w",
        "plan": "minyad/strategy/plan",
        "decision": "minyad/strategy/decision",
        "soc_floor": "minyad/strategy/soc_floor",
    },
}
TOPIC_SURPLUS_FORECAST = "minyad/strategy/surplus_forecast"


class StrategyService:
    def __init__(self) -> None:
        self.settings = Settings(AsyncSessionLocal)
        self.mqtt = MinyadMqttClient(os.getenv("MQTT_CLIENT_ID", "minyad-strategy-v3"))
        self.planner = RollingPlanner(self.settings, AsyncSessionLocal)
        self.tracker = TrajectoryTracker(self.settings)
        self.executor = StrategyExecutor(self.settings)
        self.guard = SoCGuard(self.settings)
        self.overrides = OverrideManager(self.settings, AsyncSessionLocal)
        self.state = ExecutorState(net_grid_w=0)
        self._pv_raw_w = 0
        self._pv_last_seen: datetime | None = None
        self.v2_setpoint_w: int | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_decision: StrategyDecision | None = None
        self.last_adjustment_log_at: datetime | None = None
        self.tick_lock = asyncio.Lock()
        self.scheduler: AsyncIOScheduler | None = None
        self.shadow_mode = SHADOW_MODE

    def _topic(self, key: str) -> str:
        return _TOPIC_MAP[self.shadow_mode][key]

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        start_metrics_server()
        await self.settings.load()
        await self.overrides.load()
        await self.planner.load_pv_calibration_factors()
        await self.refresh_consumption_profile()
        await self.recalculate_plan()
        self._start_scheduler()
        topics = [
            "minyad/dsmr/net_power_w",
            "minyad/grid/net_power_w",
            "minyad/battery/+",
            "minyad/solar/production_w",
            "minyad/market/signals",
            "minyad/trade/prices/da/+/full",
            "minyad/control/override",
            "minyad/strategy/reload",
            "minyad/bridge/last_seen",
        ]
        if self.shadow_mode:
            topics.append("minyad/strategy/setpoint_w")
        for topic in topics:
            self.mqtt.subscribe(topic, self._on_mqtt)
        self.mqtt.start()
        await self._run_health_server()

    def _start_scheduler(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=AMSTERDAM)
        self.scheduler.add_job(
            self._run_recalculate_plan,
            "interval",
            minutes=self.settings.plan_interval_min,
            id="strategy3_plan_interval",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_daily_calibration,
            "cron",
            hour=6,
            minute=0,
            id="strategy3_daily_calibration",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_daily_forecast_accuracy,
            "cron",
            hour=1,
            minute=0,
            id="strategy3_daily_forecast_accuracy",
            replace_existing=True,
        )
        self.scheduler.start()

    def _run_recalculate_plan(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(asyncio.create_task, self.recalculate_plan())

    def _run_daily_calibration(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(asyncio.create_task, self.planner.daily_calibration(datetime.now(AMSTERDAM)))

    def _run_daily_forecast_accuracy(self) -> None:
        if self.loop is not None:
            yesterday = (datetime.now(AMSTERDAM) - timedelta(days=1)).date()
            self.loop.call_soon_threadsafe(
                asyncio.create_task, forecast_accuracy.run_daily_accuracy_job(AsyncSessionLocal, yesterday, tz=AMSTERDAM)
            )

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(asyncio.create_task, self.handle_message(topic, payload))

    async def handle_message(self, topic: str, payload: bytes) -> None:
        decoded = payload.decode("utf-8", errors="replace")
        if topic == "minyad/strategy/reload":
            await self.settings.reload()
            return
        if topic == "minyad/control/override":
            await self.overrides.apply_payload(decoded)
            return
        if topic == "minyad/strategy/setpoint_w":
            try:
                self.v2_setpoint_w = int(float(decoded))
            except ValueError:
                pass
            return
        if topic.startswith("minyad/trade/prices/da/") and topic.endswith("/full"):
            parts = topic.split("/")
            day = parts[4] if len(parts) > 4 else ""
            try:
                points = json.loads(decoded)
            except json.JSONDecodeError:
                return
            self.planner.on_prices(day, points)
            await self.recalculate_plan()
            return
        if topic == "minyad/market/signals":
            try:
                signal_payload = json.loads(decoded)
            except json.JSONDecodeError:
                return
            self.planner.on_market_signal(signal_payload, now=datetime.now(timezone.utc))
            await self.recalculate_plan()
            return
        if topic == "minyad/solar/production_w":
            try:
                self._pv_raw_w = int(float(decoded))
                self._pv_last_seen = datetime.now(timezone.utc)
            except ValueError:
                pass
            return
        if topic == "minyad/bridge/last_seen":
            self.state = _replace(self.state, bridge_last_seen=_parse_dt(decoded))
            return
        if topic.startswith("minyad/battery/"):
            self._handle_battery(topic, decoded)
            return
        if topic in {"minyad/dsmr/net_power_w", "minyad/grid/net_power_w"}:
            self.state = _replace(self.state, net_grid_w=int(float(decoded)))
            await self.tick()

    def _handle_battery(self, topic: str, payload: str) -> None:
        measurement = topic.removeprefix("minyad/battery/")
        if measurement == "soc":
            self.state = _replace(self.state, battery_soc=float(payload))
        elif measurement == "power_w":
            self.state = _replace(self.state, battery_power_w=int(float(payload)))
        elif measurement in {"voltage", "voltage_v"}:
            self.state = _replace(self.state, battery_voltage=float(payload))

    def _effective_pv_now_w(self, now: datetime) -> int:
        if self._pv_last_seen is None:
            return 0
        age = (now - self._pv_last_seen).total_seconds()
        return self._pv_raw_w if age <= PV_STALE_SECONDS else 0

    async def recalculate_plan(self) -> None:
        now = datetime.now(AMSTERDAM)
        try:
            with SOLVE_DURATION_SECONDS.time():
                plan = await self.planner.recalculate(now, self.state.battery_soc)
        except Exception:
            ERRORS_TOTAL.labels(type="plan_recalculate").inc()
            SOLVE_STATUS_TOTAL.labels(status="error").inc()
            raise
        record_plan_metrics(plan)
        self.publish_plan(plan)
        if plan.solver_status != "FALLBACK":
            self.publish_surplus_forecast(plan)

    async def refresh_consumption_profile(self) -> None:
        try:
            profile = await load_baseline_consumption_profile(
                AsyncSessionLocal,
                vesper_api_url=VESPER_API_URL or None,
                vesper_api_key=VESPER_API_SECRET or None,
                lookback_days=self.settings.consumption_lookback_days,
                fallback_w=self.settings.consumption_fallback_w,
            )
            self.planner.set_consumption_profile(profile)
        except Exception:  # noqa: BLE001 - profile is advisory; never break the loop
            LOGGER.exception("Unable to load household consumption profile; keeping previous")

    async def tick(self) -> None:
        async with self.tick_lock:
            await self._tick_locked()

    async def _tick_locked(self) -> None:
        now = datetime.now(timezone.utc)
        plan = self.planner.current_plan(now, self.state.battery_soc if self.state.battery_soc is not None else 50.0)
        soc_for_tracker = self.state.battery_soc if self.state.battery_soc is not None else plan.soc_plan_pct(now)
        tracker_result = self.tracker.evaluate(now, soc_for_tracker, plan)

        exec_state = _replace(self.state, pv_now_w=self._effective_pv_now_w(now))
        decision = self.executor.tick(exec_state, plan, tracker_result)
        if plan.market_signal_ids or plan.constraint_reasons:
            decision = StrategyDecision(
                decision.timestamp,
                decision.setpoint_w,
                decision.soc,
                decision.net_grid_w,
                decision.bias_w,
                decision.floor_dyn_pct,
                decision.ceil_dyn_pct,
                decision.reason,
                decision.solver_status,
                plan.market_signal_ids,
                plan.constraint_reasons,
            )
        raw_setpoint = decision.setpoint_w

        setpoint, override_reason = await self.overrides.apply_with_reason(
            decision.setpoint_w, exec_state, tracker_result.floor_dyn_pct, tracker_result.ceil_dyn_pct
        )
        setpoint, guard_reason = self.guard.apply_with_reason(
            setpoint,
            exec_state,
            tracker_result.floor_dyn_pct,
            tracker_result.ceil_dyn_pct,
            now,
            skip_soc_limits=self.overrides.bypasses_soc_limits(),
        )

        adjusted = setpoint != raw_setpoint
        if adjusted:
            adjustment_reason = adjustment_reason_suffix(override_reason, guard_reason)
            decision = StrategyDecision(
                decision.timestamp,
                setpoint,
                decision.soc,
                decision.net_grid_w,
                decision.bias_w,
                decision.floor_dyn_pct,
                decision.ceil_dyn_pct,
                f"{decision.reason}{adjustment_reason}",
                decision.solver_status,
                decision.market_signal_ids,
                decision.constraint_reasons,
            )

        setpoint_changed = self.last_decision is None or setpoint != self.last_decision.setpoint_w
        adjustment_log_due = adjusted_decision_log_due(
            adjusted=adjusted,
            setpoint_changed=setpoint_changed,
            now=decision.timestamp,
            last_adjustment_log_at=self.last_adjustment_log_at,
            interval_seconds=self.settings.adjustment_log_interval_sec,
        )
        if setpoint_changed:
            self.publish_setpoint(setpoint)
        if setpoint_changed or adjustment_log_due:
            self.publish_decision(decision, tracker_result)
            if not self.shadow_mode:
                await self.log_setpoint(decision, tracker_result)
        if adjusted and (setpoint_changed or adjustment_log_due):
            self.last_adjustment_log_at = decision.timestamp
        elif not adjusted:
            self.last_adjustment_log_at = None
        self.last_decision = decision
        self.state = _replace(self.state, current_setpoint_w=setpoint)

        if self.shadow_mode:
            await self.log_shadow(decision)

        self.publish_floor_telemetry(tracker_result)

    def publish_setpoint(self, setpoint_w: int) -> None:
        self.mqtt.publish(self._topic("setpoint_w"), str(setpoint_w), retain=True)
        if self.shadow_mode:
            return
        if setpoint_w > 0:
            self.mqtt.publish("minyad/control/charge_w", str(setpoint_w))
            self.mqtt.publish("minyad/control/discharge_w", "0")
        elif setpoint_w < 0:
            self.mqtt.publish("minyad/control/charge_w", "0")
            self.mqtt.publish("minyad/control/discharge_w", str(abs(setpoint_w)))
        else:
            self.mqtt.publish("minyad/control/charge_w", "0")
            self.mqtt.publish("minyad/control/discharge_w", "0")

    def publish_plan(self, plan: SlotPlan) -> None:
        self.mqtt.publish(self._topic("plan"), json.dumps(_plan_payload(plan)), retain=True)

    def publish_surplus_forecast(self, plan: SlotPlan) -> None:
        payload = {
            "generated_at": plan.generated_at.isoformat(),
            "slot_seconds": plan.slot_seconds,
            "slots": [{"start": slot.start.isoformat(), "surplus_w": slot.surplus_w} for slot in plan.slots],
        }
        self.mqtt.publish(TOPIC_SURPLUS_FORECAST, json.dumps(payload), retain=True)

    def publish_floor_telemetry(self, tracker_result: TrackerResult) -> None:
        self.mqtt.publish(self._topic("soc_floor"), f"{tracker_result.floor_dyn_pct:.2f}", retain=True)

    def publish_decision(self, decision: StrategyDecision, tracker_result: TrackerResult) -> None:
        self.mqtt.publish(self._topic("decision"), json.dumps(_decision_payload(decision, tracker_result)), retain=False)

    async def log_setpoint(self, decision: StrategyDecision, tracker_result: TrackerResult) -> None:
        async with AsyncSessionLocal() as session:
            columns = (await session.execute(
                text("""
                    select column_name
                    from information_schema.columns
                    where table_name = 'setpoint_log'
                """)
            )).scalars().all()
            await session.execute(
                text(build_setpoint_log_insert(set(columns))),
                {
                    "floor": tracker_result.floor_dyn_pct,
                    "ceiling": tracker_result.ceil_dyn_pct,
                    "setpoint": decision.setpoint_w,
                    "discharge_allowed": decision.setpoint_w < 0,
                    "soc": decision.soc,
                    "grid": decision.net_grid_w,
                    "battery_power": self.state.battery_power_w,
                    "delta": decision.setpoint_w - (self.last_decision.setpoint_w if self.last_decision else 0),
                    "reason": decision.reason,
                },
            )
            await session.commit()

    async def log_shadow(self, decision: StrategyDecision) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    insert into strategy_shadow_log (ts, v2_setpoint_w, v3_setpoint_w, soc, net_grid_w, v3_reason)
                    values (:ts, :v2_setpoint_w, :v3_setpoint_w, :soc, :net_grid_w, :v3_reason)
                """),
                {
                    "ts": decision.timestamp,
                    "v2_setpoint_w": self.v2_setpoint_w,
                    "v3_setpoint_w": decision.setpoint_w,
                    "soc": decision.soc,
                    "net_grid_w": decision.net_grid_w,
                    "v3_reason": decision.reason,
                },
            )
            await session.commit()

    async def _run_health_server(self) -> None:
        app = FastAPI()

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "shadow_mode": self.shadow_mode,
                "state": asdict(self.state),
                "last_decision": _decision_payload(self.last_decision, None) if self.last_decision else None,
            }

        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info"))
        await server.serve()


async def main() -> None:
    service = StrategyService()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, lambda: asyncio.create_task(service.settings.reload()))
    await service.start()


def _replace(state: ExecutorState, **changes: Any) -> ExecutorState:
    data = asdict(state)
    data.update(changes)
    return ExecutorState(**data)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def record_plan_metrics(plan: SlotPlan) -> None:
    SOLVE_STATUS_TOTAL.labels(status=_prometheus_solve_status(plan.solver_status)).inc()
    PLAN_HORIZON_HOURS.set(len(plan.slots) * plan.slot_seconds / 3600.0)
    generated_at = plan.generated_at if plan.generated_at.tzinfo else plan.generated_at.replace(tzinfo=timezone.utc)
    LAST_PLAN_TIMESTAMP_SECONDS.set(generated_at.timestamp())
    if plan.slots:
        first_slot = plan.slots[0]
        PLANNED_BATTERY_POWER_WATTS.set(float(first_slot.discharge_w - first_slot.charge_w))


def _prometheus_solve_status(solver_status: str) -> str:
    normalized = solver_status.strip().lower()
    if normalized == "optimal":
        return "optimal"
    if "infeasible" in normalized:
        return "infeasible"
    if "timeout" in normalized or "time" in normalized:
        return "timeout"
    return "error"


def _plan_payload(plan: SlotPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "valid_from": plan.valid_from.isoformat(),
        "slot_seconds": plan.slot_seconds,
        "soc_start_pct": plan.soc_start_pct,
        "slots": [
            {
                "start": slot.start.isoformat(),
                "soc_target_pct": slot.soc_target_pct,
                "planned_grid_charge_w": slot.planned_grid_charge_w,
                "planned_export_w": slot.planned_export_w,
                "pv_forecast_w": slot.pv_forecast_w,
                "load_forecast_w": slot.load_forecast_w,
                "curtailment_w": slot.curtailment_w,
                "price_source": slot.price_source,
                "cloud_cover_pct": slot.cloud_cover_pct,
                "price_import": slot.price_import,
                "price_export": slot.price_export,
            }
            for slot in plan.slots
        ],
        "friday_full_cycle": plan.friday_full_cycle,
        "solver_status": plan.solver_status,
        "pv_calibration_factor": plan.pv_calibration_factor,
        "plan_schema": plan.plan_schema,
        **({"market_signal_ids": plan.market_signal_ids} if plan.market_signal_ids else {}),
        **({"constraint_reasons": plan.constraint_reasons} if plan.constraint_reasons else {}),
    }


def _decision_payload(decision: StrategyDecision | None, tracker_result: TrackerResult | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "timestamp": decision.timestamp.isoformat(),
        "setpoint_w": decision.setpoint_w,
        "soc": decision.soc,
        "net_grid_w": decision.net_grid_w,
        "bias_w": decision.bias_w,
        "floor_dyn_pct": decision.floor_dyn_pct,
        "ceil_dyn_pct": decision.ceil_dyn_pct,
        "reason": decision.reason,
        "solver_status": decision.solver_status,
        **({"market_signal_ids": decision.market_signal_ids} if decision.market_signal_ids else {}),
        **({"constraint_reasons": decision.constraint_reasons} if decision.constraint_reasons else {}),
    }


if __name__ == "__main__":
    asyncio.run(main())
