"""Strategy v2 service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.logging_utils import configure_container_logging
from shared.mqtt_client import MinyadMqttClient

from .constants import Settings
from .executor import StrategyExecutor
from .models import DayPlan, ExecutorState, StrategyDecision
from .override import OverrideManager
from .planner import AMSTERDAM, StrategyPlanner, default_day_plan
from .soc_guard import SoCGuard

configure_container_logging(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
LOGGER = logging.getLogger(__name__)

TOPIC_SETPOINT = "minyad/strategy/setpoint_w"
TOPIC_ACTIVE = "minyad/strategy/active"
TOPIC_DECISION = "minyad/strategy/decision"


class StrategyService:
    def __init__(self) -> None:
        self.settings = Settings(AsyncSessionLocal)
        self.mqtt = MinyadMqttClient("minyad-strategy")
        self.planner = StrategyPlanner(self.settings, AsyncSessionLocal)
        self.plan: DayPlan | None = None
        self.executor: StrategyExecutor | None = None
        self.guard = SoCGuard(self.settings)
        self.overrides = OverrideManager(self.settings, AsyncSessionLocal)
        self.state = ExecutorState(net_grid_w=0)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_decision: StrategyDecision | None = None
        self.scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.settings.load()
        await self.overrides.load()
        self.plan = await self.planner.load_plan(datetime.now(AMSTERDAM).date()) or default_day_plan(self.settings)
        self.executor = StrategyExecutor(self.settings, self.plan)
        self.publish_active_plan()
        self._start_scheduler()
        for topic in (
            "minyad/dsmr/net_power_w",
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
        if topic == "minyad/dsmr/net_power_w":
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
        if self.executor is None or self.plan is None:
            return
        decision = self.executor.tick(self.state)
        setpoint = await self.overrides.apply(decision.setpoint_w, self.state, self.plan)
        setpoint = self.guard.apply(setpoint, self.state, self.plan, decision.timestamp)
        if setpoint != decision.setpoint_w:
            decision = StrategyDecision(
                decision.timestamp,
                setpoint,
                decision.soc,
                decision.net_grid_w,
                decision.solar_forecast_w,
                decision.mode,
                f"{decision.reason}; guard/override adjusted setpoint",
                decision.plan_date,
                decision.in_grid_charge_window,
                decision.in_price_discharge_window,
            )
        if self.last_decision is None or setpoint != self.last_decision.setpoint_w:
            self.publish_setpoint(setpoint)
            self.publish_decision(decision)
            await self.log_setpoint(decision)
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

    def publish_decision(self, decision: StrategyDecision) -> None:
        self.mqtt.publish(TOPIC_DECISION, json.dumps(_decision_payload(decision)), retain=True)

    async def log_setpoint(self, decision: StrategyDecision) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    insert into setpoint_log (
                        source, soc_floor, soc_ceiling, charge_rate_w, discharge_allowed,
                        battery_soc_at_time, grid_power_at_time, battery_power_at_time,
                        setpoint_delta, trigger_reason, ack_received
                    ) values (
                        'strategy_v2', :floor, :ceiling, :charge_rate, :discharge_allowed,
                        :soc, :grid, :battery_power, :delta, :reason, true
                    )
                """),
                {
                    "floor": self.plan.effective_soc_floor if self.plan else 0,
                    "ceiling": self.plan.effective_soc_ceiling if self.plan else 100,
                    "charge_rate": max(0, decision.setpoint_w),
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
        self.publish_active_plan()

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
