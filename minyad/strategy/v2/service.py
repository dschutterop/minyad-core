"""Strategy v2 service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import asdict
from datetime import datetime, time, timezone
from typing import Any

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

from .constants import Settings
from .consumption_profile import ConsumptionProfile, load_consumption_profile
from .executor import StrategyExecutor
from .floor_schedule import FloorScheduleState, build_floor_schedule, night_horizon
from .models import DayPlan, ExecutorState, StrategyDecision
from .override import OverrideManager
from .planner import AMSTERDAM, StrategyPlanner, default_day_plan
from .reasons import adjusted_decision_log_due, adjustment_reason_suffix
from .setpoint_log import build_setpoint_log_insert
from .soc_guard import SoCGuard

configure_container_logging(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
LOGGER = logging.getLogger(__name__)

TOPIC_SETPOINT = "minyad/strategy/setpoint_w"
TOPIC_ACTIVE = "minyad/strategy/active"
TOPIC_DECISION = "minyad/strategy/decision"
TOPIC_SOC_FLOOR = "minyad/strategy/soc_floor"
TOPIC_FLOOR_DRIFT = "minyad/strategy/floor_drift_factor"
TOPIC_FLOOR_REMAINING = "minyad/strategy/floor_remaining_expected_wh"


class StrategyService:
    def __init__(self) -> None:
        self.settings = Settings(AsyncSessionLocal)
        self.mqtt = MinyadMqttClient("minyad-strategy")
        self.planner = StrategyPlanner(self.settings, AsyncSessionLocal)
        self.plan: DayPlan | None = None
        self.executor: StrategyExecutor | None = None
        self.guard = SoCGuard(self.settings)
        self.overrides = OverrideManager(self.settings, AsyncSessionLocal)
        self.consumption_profile: ConsumptionProfile | None = None
        self.floor_schedule: FloorScheduleState | None = None
        self.state = ExecutorState(net_grid_w=0)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_decision: StrategyDecision | None = None
        self.last_adjustment_log_at: datetime | None = None
        self.tick_lock = asyncio.Lock()
        self.scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.settings.load()
        await self.overrides.load()
        self.plan = await self.planner.load_plan(datetime.now(AMSTERDAM).date()) or default_day_plan(self.settings)
        self.executor = StrategyExecutor(self.settings, self.plan)
        await self.refresh_consumption_profile()
        self.publish_active_plan()
        self._start_scheduler()
        for topic in (
            "minyad/dsmr/net_power_w",
            "minyad/grid/net_power_w",
            "minyad/battery/+",
            "minyad/forecast/power_w",
            "minyad/trade/prices",
            "minyad/control/override",
            "minyad/strategy/reload",
            "minyad/bridge/last_seen",
        ):
            self.mqtt.subscribe(topic, self._on_mqtt)
        self.mqtt.start()
        await self._run_health_server()

    def _start_scheduler(self) -> None:
        hour, minute = [int(part) for part in self.settings.get("strategy.daily_recalculate_local_time", "22:00").split(":", 1)]
        self.scheduler = AsyncIOScheduler(timezone=AMSTERDAM)
        self.scheduler.add_job(self.recalculate, "cron", hour=hour, minute=minute, id="daily_strategy_recalculate", replace_existing=True)
        self.scheduler.start()

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(asyncio.create_task, self.handle_message(topic, payload))

    async def handle_message(self, topic: str, payload: bytes) -> None:
        decoded = payload.decode("utf-8", errors="replace")
        if topic == "minyad/strategy/reload":
            await self.reload()
            return
        if topic == "minyad/control/override":
            await self.overrides.apply_payload(decoded)
            return
        if topic == "minyad/trade/prices":
            self.planner.set_prices(json.loads(decoded))
            return
        if topic == "minyad/forecast/power_w":
            self.state = _replace(self.state, solar_forecast_w=int(float(decoded)))
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

    async def tick(self) -> None:
        async with self.tick_lock:
            await self._tick_locked()

    async def _tick_locked(self) -> None:
        if self.executor is None or self.plan is None:
            return
        decision = self.executor.tick(self.state)
        raw_setpoint = decision.setpoint_w
        self.update_floor_schedule(decision.timestamp)
        setpoint, override_reason = await self.overrides.apply_with_reason(decision.setpoint_w, self.state, self.plan)
        setpoint, guard_reason = self.guard.apply_with_reason(setpoint, self.state, self.plan, decision.timestamp)
        adjusted = setpoint != raw_setpoint
        if adjusted:
            adjustment_reason = adjustment_reason_suffix(override_reason, guard_reason)
            decision = StrategyDecision(
                decision.timestamp,
                setpoint,
                decision.soc,
                decision.net_grid_w,
                decision.solar_forecast_w,
                decision.mode,
                f"{decision.reason}{adjustment_reason}",
                decision.plan_date,
                decision.in_grid_charge_window,
                decision.in_price_discharge_window,
            )
        setpoint_changed = self.last_decision is None or setpoint != self.last_decision.setpoint_w
        adjustment_log_due = adjusted_decision_log_due(
            adjusted=adjusted,
            setpoint_changed=setpoint_changed,
            now=decision.timestamp,
            last_adjustment_log_at=self.last_adjustment_log_at,
            interval_seconds=self.settings.int("strategy.adjustment_log_interval_sec"),
        )
        if setpoint_changed:
            self.publish_setpoint(setpoint)
        if setpoint_changed or adjustment_log_due:
            self.publish_decision(decision)
            await self.log_setpoint(decision)
        if adjusted and (setpoint_changed or adjustment_log_due):
            self.last_adjustment_log_at = decision.timestamp
        elif not adjusted:
            self.last_adjustment_log_at = None
        self.last_decision = decision
        self.state = _replace(self.state, current_setpoint_w=setpoint)

    def publish_setpoint(self, setpoint_w: int) -> None:
        self.mqtt.publish(TOPIC_SETPOINT, str(setpoint_w), retain=True)
        if setpoint_w > 0:
            self.mqtt.publish("minyad/control/charge_w", str(setpoint_w))
            self.mqtt.publish("minyad/control/discharge_w", "0")
        elif setpoint_w < 0:
            self.mqtt.publish("minyad/control/charge_w", "0")
            self.mqtt.publish("minyad/control/discharge_w", str(abs(setpoint_w)))
        else:
            self.mqtt.publish("minyad/control/charge_w", "0")
            self.mqtt.publish("minyad/control/discharge_w", "0")

    def publish_active_plan(self) -> None:
        if self.plan is None:
            return
        self.mqtt.publish(TOPIC_ACTIVE, json.dumps(_plan_payload(self.plan)), retain=True)

    def publish_floor_telemetry(self) -> None:
        schedule = self.floor_schedule
        if schedule is None:
            return
        self.mqtt.publish(TOPIC_SOC_FLOOR, f"{schedule.current_floor:.2f}", retain=True)
        self.mqtt.publish(TOPIC_FLOOR_DRIFT, f"{schedule.drift_factor:.3f}", retain=True)
        self.mqtt.publish(TOPIC_FLOOR_REMAINING, f"{schedule.remaining_expected_adjusted_wh:.1f}", retain=True)

    def publish_decision(self, decision: StrategyDecision) -> None:
        self.mqtt.publish(TOPIC_DECISION, json.dumps(_decision_payload(decision)), retain=True)

    async def log_setpoint(self, decision: StrategyDecision) -> None:
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
                    "floor": self.plan.effective_soc_floor if self.plan else 0,
                    "ceiling": self.plan.effective_soc_ceiling if self.plan else 100,
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

    async def reload(self) -> None:
        await self.settings.reload()
        if self.executor and self.plan:
            self.executor.set_plan(self.plan)

    async def recalculate(self) -> None:
        self.plan = await self.planner.recalculate()
        if self.executor:
            self.executor.set_plan(self.plan)
        else:
            self.executor = StrategyExecutor(self.settings, self.plan)
        await self.refresh_consumption_profile()
        # A new plan opens a new night cycle; drop the stale floor schedule so the
        # next tick inside the horizon rebuilds it against the fresh plan floor.
        self.floor_schedule = None
        self.guard.set_floor_schedule(None)
        self.publish_active_plan()

    async def refresh_consumption_profile(self) -> None:
        try:
            self.consumption_profile = await load_consumption_profile(
                AsyncSessionLocal,
                lookback_days=self.settings.int("strategy.consumption_lookback_days"),
                fallback_w=self.settings.float("strategy.consumption_fallback_w"),
            )
        except Exception:  # noqa: BLE001 - profile is advisory; never break the loop
            LOGGER.exception("Unable to load household consumption profile; keeping previous")

    def _household_load_w(self) -> float:
        """Approximate instantaneous household load for floor self-correction.

        Inside the overnight floor horizon solar production is ~0, so the load
        is well approximated by grid import plus battery discharge. Both use the
        same sign convention as the executor (net_grid_w > 0 = import,
        battery_power_w > 0 = discharge).
        """
        return max(0.0, float(self.state.net_grid_w) + float(self.state.battery_power_w))

    def update_floor_schedule(self, now: datetime) -> None:
        """Build/observe/recompute the self-correcting floor and arm the guard."""
        if self.plan is None or self.consumption_profile is None:
            return
        start_t = _parse_local_time(self.settings.get("strategy.floor_horizon_start_local", "21:00"))
        end_t = _parse_local_time(self.settings.get("strategy.floor_horizon_end_local", "07:00"))
        horizon_start, horizon_end = night_horizon(now, start_t, end_t)

        if not (horizon_start <= now < horizon_end) or self.state.battery_soc is None:
            self.floor_schedule = None
            self.guard.set_floor_schedule(None)
            return

        if self.floor_schedule is None or self.floor_schedule.horizon_start != horizon_start:
            self.floor_schedule = build_floor_schedule(
                now,
                self.state.battery_soc,
                self.plan.effective_soc_floor,
                horizon_start,
                horizon_end,
                self.consumption_profile,
            )

        self.floor_schedule.observe(now, self._household_load_w())
        self.floor_schedule.recompute(now, self.state.battery_soc)
        self.guard.set_floor_schedule(self.floor_schedule)
        self.publish_floor_telemetry()

    async def _run_health_server(self) -> None:
        app = FastAPI()

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "state": asdict(self.state),
                "plan": _plan_payload(self.plan) if self.plan else None,
                "last_decision": _decision_payload(self.last_decision) if self.last_decision else None,
            }

        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info"))
        await server.serve()


async def main() -> None:
    service = StrategyService()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, lambda: asyncio.create_task(service.reload()))
    await service.start()


def _replace(state: ExecutorState, **changes: Any) -> ExecutorState:
    data = asdict(state)
    data.update(changes)
    return ExecutorState(**data)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_local_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def _plan_payload(plan: DayPlan) -> dict[str, Any]:
    return {
        "date": plan.date.isoformat(),
        "solar_mode": plan.solar_mode,
        "forecast_ghi_kwh_m2": plan.forecast_ghi_kwh_m2,
        "effective_soc_floor": plan.effective_soc_floor,
        "effective_soc_ceiling": plan.effective_soc_ceiling,
        "grid_charge_windows": _windows_payload(plan.grid_charge_windows),
        "price_discharge_windows": _windows_payload(plan.price_discharge_windows),
        "planned_soc_at_sunset": plan.planned_soc_at_sunset,
        "valid_until": plan.valid_until.isoformat() if plan.valid_until else None,
        "reason": plan.reason,
    }


def _decision_payload(decision: StrategyDecision) -> dict[str, Any]:
    return {
        "timestamp": decision.timestamp.isoformat(),
        "setpoint_w": decision.setpoint_w,
        "soc": decision.soc,
        "net_grid_w": decision.net_grid_w,
        "solar_forecast_w": decision.solar_forecast_w,
        "mode": decision.mode,
        "reason": decision.reason,
        "plan_date": decision.plan_date.isoformat(),
        "in_grid_charge_window": decision.in_grid_charge_window,
        "in_price_discharge_window": decision.in_price_discharge_window,
    }


def _windows_payload(windows: list[tuple[datetime, datetime]]) -> list[dict[str, str]]:
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in windows]


if __name__ == "__main__":
    asyncio.run(main())
