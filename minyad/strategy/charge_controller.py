"""Forecast-driven battery charge/discharge strategy for Minyad.

The controller only talks to the inverter through MQTT topics consumed by the
host-level ``goodwe_bridge`` service.  It never opens an inverter or Modbus
connection from inside the container.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

try:
    from shared.db import AsyncSessionLocal
except Exception:  # pragma: no cover - allows unit tests without DB_URL
    AsyncSessionLocal = None
from shared.mqtt_client import MinyadMqttClient

LOGGER = logging.getLogger(__name__)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SCHIPLUIDEN_LAT = 51.97
SCHIPLUIDEN_LON = 4.31

MODE_NORMAL = "NORMAL"
MODE_SOLAR_RICH = "SOLAR_RICH"
MODE_SOLAR_POOR = "SOLAR_POOR"
MODE_MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

ABSOLUTE_FLOOR = 10
ABSOLUTE_DAILY_CEILING = 95
ABSOLUTE_OVERRIDE_CEILING = 100
DEFAULT_MAX_CHARGE_W = 1440
DEFAULT_DEBOUNCE_SECONDS = 300
ACK_TIMEOUT_SECONDS = 30

TOPIC_SETPOINT_JSON = "minyad/battery/setpoint"
TOPIC_STRATEGY_ACTIVE = "minyad/strategy/active"
TOPIC_BRIDGE_CHARGE_W = "minyad/control/charge_w"
TOPIC_BRIDGE_DISCHARGE_W = "minyad/control/discharge_w"
TOPIC_BATTERY_PREFIX = "minyad/battery/"
TOPIC_DSMR_NET_POWER = "minyad/dsmr/net_power_w"


@dataclass(frozen=True)
class ModeConfig:
    """Resolved operating constraints for a charge strategy mode."""

    mode: str
    soc_floor: int
    soc_ceiling: int
    charge_rate_w: int | None
    reason: str
    valid_until: datetime
    forecast_ghi: float | None = None


@dataclass(frozen=True)
class StrategyDecision:
    """A concrete setpoint decision produced by :class:`ChargeController`."""

    mode: str
    soc_floor: int
    soc_ceiling: int
    charge_rate_w: int | None
    discharge_allowed: bool
    reason: str
    valid_until: datetime


class ChargeController:
    """Battery strategy engine with MQTT-only inverter control.

    The prompt topic names were checked against the repository bridge code after
    live broker inspection could not run because ``mosquitto_sub`` is absent in
    this container.  Current bridge code consumes ``minyad/control/charge_w`` and
    ``minyad/control/discharge_w`` while publishing battery telemetry below
    ``minyad/battery/``; therefore ``apply`` publishes the requested JSON
    contract for observability and also the bridge-compatible watt topics.
    """

    def __init__(
        self,
        mqtt: Any | None = None,
        *,
        db_session_factory: Any | None = None,
        now: Any | None = None,
        ack_timeout_seconds: int = ACK_TIMEOUT_SECONDS,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        self.mqtt = mqtt or MinyadMqttClient("minyad-strategy")
        self.db_session_factory = db_session_factory if db_session_factory is not None else AsyncSessionLocal
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.ack_timeout_seconds = ack_timeout_seconds
        self.debounce_seconds = debounce_seconds
        self._lock = Lock()
        self._battery_state: dict[str, Any] = {}
        self._grid_power_w: int | None = None
        self._last_apply_monotonic: float | None = None
        self._ack_event = Event()
        self._last_ack_latency_ms: int | None = None
        self._last_mode: ModeConfig | None = None
        if hasattr(self.mqtt, "subscribe"):
            self.mqtt.subscribe(f"{TOPIC_BATTERY_PREFIX}+", self.handle_mqtt_message)
            self.mqtt.subscribe(TOPIC_DSMR_NET_POWER, self.handle_mqtt_message)

    def handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Record incoming MQTT telemetry and wake pending setpoint ACKs."""
        decoded = payload.decode("utf-8", errors="replace")
        with self._lock:
            if topic.startswith(TOPIC_BATTERY_PREFIX):
                key = topic.removeprefix(TOPIC_BATTERY_PREFIX)
                self._battery_state[key] = self._coerce_payload(decoded)
                self._ack_event.set()
            elif topic == TOPIC_DSMR_NET_POWER:
                self._grid_power_w = int(float(decoded))

    def evaluate(self) -> StrategyDecision:
        """Evaluate the active mode against latest telemetry and health limits."""
        mode = self.get_active_mode()
        with self._lock:
            soc = self._battery_state.get("soc")
            grid_power = self._grid_power_w
        charge_rate = mode.charge_rate_w
        discharge_allowed = True
        reason = mode.reason
        if isinstance(soc, (int, float)) and soc <= mode.soc_floor:
            charge_rate = self._max_charge_w_sync()
            discharge_allowed = False
            reason = f"SoC floor breach ({soc}% <= {mode.soc_floor}%); charging re-enabled"
        elif isinstance(soc, (int, float)) and soc >= mode.soc_ceiling:
            charge_rate = 0
            discharge_allowed = True
            reason = f"SoC ceiling reached ({soc}% >= {mode.soc_ceiling}%); charging stopped"
        if isinstance(soc, (int, float)) and grid_power is not None and grid_power < 0 and soc < mode.soc_floor:
            LOGGER.warning("Grid export while battery below floor: soc=%s floor=%s grid_power_w=%s", soc, mode.soc_floor, grid_power)
        return StrategyDecision(mode.mode, mode.soc_floor, mode.soc_ceiling, charge_rate, discharge_allowed, reason, mode.valid_until)

    def apply(self, decision: StrategyDecision) -> None:
        """Publish a setpoint through MQTT and log whether bridge telemetry ACKed it."""
        now_mono = time.monotonic()
        if self._last_apply_monotonic is not None and now_mono - self._last_apply_monotonic < self.debounce_seconds:
            LOGGER.info("Suppressing setpoint change inside %ss debounce window", self.debounce_seconds)
            return
        payload = {
            "target_soc": decision.soc_ceiling,
            "soc_floor": decision.soc_floor,
            "charge_rate_w": decision.charge_rate_w,
            "discharge_allowed": decision.discharge_allowed,
        }
        with self._lock:
            battery_soc = self._battery_state.get("soc")
            grid_power = self._grid_power_w
            self._ack_event.clear()
        started = time.monotonic()
        self._publish(TOPIC_SETPOINT_JSON, json.dumps(payload))
        self._publish(TOPIC_BRIDGE_CHARGE_W, str(max(0, decision.charge_rate_w or 0)))
        if not decision.discharge_allowed:
            self._publish(TOPIC_BRIDGE_DISCHARGE_W, "0")
        ack_received = self._ack_event.wait(self.ack_timeout_seconds)
        ack_latency = int((time.monotonic() - started) * 1000) if ack_received else None
        self._last_ack_latency_ms = ack_latency
        self._last_apply_monotonic = now_mono
        self._insert_setpoint_log_sync(decision, battery_soc, grid_power, ack_received, ack_latency)
        if not ack_received:
            LOGGER.error("Setpoint write was not confirmed by %s within %ss", TOPIC_BATTERY_PREFIX, self.ack_timeout_seconds)

    def get_active_mode(self) -> ModeConfig:
        """Return the DB-selected active mode, or NORMAL if none exists."""
        if self._last_mode and self._last_mode.valid_until > self._now():
            return self._last_mode
        mode = self._load_active_mode_sync() or ModeConfig(MODE_NORMAL, 20, 80, self._max_charge_w_sync(), "default; no forecast data available", self._end_of_next_local_day(), None)
        self._last_mode = self._clamp_mode(mode)
        return self._last_mode

    def override(self, floor: int, ceiling: int, expires_at: datetime) -> None:
        """Activate an audited manual override, constrained to hardware-safe limits."""
        floor = max(ABSOLUTE_FLOOR, int(floor))
        ceiling = min(ABSOLUTE_OVERRIDE_CEILING, int(ceiling))
        if floor >= ceiling:
            raise ValueError("override floor must be lower than ceiling")
        if expires_at > self._now() + timedelta(hours=24):
            expires_at = self._now() + timedelta(hours=24)
        mode = ModeConfig(MODE_MANUAL_OVERRIDE, floor, ceiling, self._max_charge_w_sync(), "manual override activated", expires_at.astimezone(timezone.utc), None)
        self._last_mode = mode
        self._store_active_mode_sync(mode)
        self._insert_strategy_decision_sync(mode, applied=False)

    def recalculate_daily(self) -> ModeConfig:
        """Fetch tomorrow's GHI forecast for Schipluiden and persist selected mode."""
        forecast_ghi = self.fetch_tomorrow_ghi()
        max_charge = self._max_charge_w_sync()
        if forecast_ghi > self._float_setting_sync("strategy.ghi_solar_rich_threshold", 4.5):
            mode = ModeConfig(MODE_SOLAR_RICH, 30, 60, None, "forecast GHI tomorrow above solar-rich threshold", self._end_of_next_local_day(), forecast_ghi)
        elif forecast_ghi < self._float_setting_sync("strategy.ghi_solar_poor_threshold", 1.5):
            mode = ModeConfig(MODE_SOLAR_POOR, 20, 92, max_charge, "forecast GHI tomorrow below solar-poor threshold", self._end_of_next_local_day(), forecast_ghi)
        else:
            mode = ModeConfig(MODE_NORMAL, 20, 80, max_charge, "forecast GHI tomorrow in normal band", self._end_of_next_local_day(), forecast_ghi)
        mode = self._clamp_mode(mode)
        self._last_mode = mode
        self._store_active_mode_sync(mode)
        self._insert_strategy_decision_sync(mode, applied=False)
        self._publish(TOPIC_STRATEGY_ACTIVE, json.dumps(self._mode_payload(mode)))
        return mode

    def fetch_tomorrow_ghi(self) -> float:
        local_now = self._now().astimezone(AMSTERDAM)
        tomorrow = (local_now + timedelta(days=1)).date().isoformat()
        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": SCHIPLUIDEN_LAT, "longitude": SCHIPLUIDEN_LON, "hourly": "shortwave_radiation", "timezone": "Europe/Amsterdam", "start_date": tomorrow, "end_date": tomorrow},
            timeout=20,
        )
        response.raise_for_status()
        watts_per_m2 = response.json().get("hourly", {}).get("shortwave_radiation", [])
        return round(sum(float(v) for v in watts_per_m2) / 1000, 3)

    def _publish(self, topic: str, payload: str) -> None:
        if hasattr(self.mqtt, "client"):
            self.mqtt.client.publish(topic, payload=payload, qos=1, retain=False)
        else:
            self.mqtt.publish(topic, payload)

    def _clamp_mode(self, mode: ModeConfig) -> ModeConfig:
        ceiling_limit = ABSOLUTE_OVERRIDE_CEILING if mode.mode == MODE_MANUAL_OVERRIDE else ABSOLUTE_DAILY_CEILING
        return ModeConfig(mode.mode, max(ABSOLUTE_FLOOR, mode.soc_floor), min(ceiling_limit, mode.soc_ceiling), mode.charge_rate_w, mode.reason, mode.valid_until.astimezone(timezone.utc), mode.forecast_ghi)

    def _end_of_next_local_day(self) -> datetime:
        local = self._now().astimezone(AMSTERDAM) + timedelta(days=1)
        end = datetime(local.year, local.month, local.day, 23, 59, 59, tzinfo=AMSTERDAM)
        return end.astimezone(timezone.utc)

    @staticmethod
    def _coerce_payload(value: str) -> Any:
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value

    def _mode_payload(self, mode: ModeConfig) -> dict[str, Any]:
        return {"mode": mode.mode, "soc_floor": mode.soc_floor, "soc_ceiling": mode.soc_ceiling, "reason": mode.reason, "valid_until": mode.valid_until.isoformat(), "forecast_ghi": mode.forecast_ghi}

    def _max_charge_w_sync(self) -> int:
        return int(self._float_setting_sync("battery.max_charge_w", DEFAULT_MAX_CHARGE_W))

    def _float_setting_sync(self, key: str, default: float) -> float:
        # Tests and deployments may inject a simple mapping instead of a DB.
        if isinstance(self.db_session_factory, dict):
            return float(self.db_session_factory.get(key, default))
        if self.db_session_factory is None:
            return default
        try:
            import asyncio
            async def read_setting() -> float:
                async with self.db_session_factory() as session:
                    result = await session.execute(text("select value from settings where key=:key"), {"key": key})
                    value = result.scalar_one_or_none()
                    return float(value) if value is not None else default
            return asyncio.run(read_setting())
        except RuntimeError:
            return default

    def _load_active_mode_sync(self) -> ModeConfig | None:
        if not isinstance(self.db_session_factory, dict):
            # Active mode is persisted as settings for restart recovery.
            if self.db_session_factory is None:
                return None
            try:
                import asyncio
                async def read_active() -> ModeConfig | None:
                    async with self.db_session_factory() as session:
                        result = await session.execute(text("select key, value from settings where key like 'strategy.active.%'"))
                        values = {row.key.removeprefix("strategy.active."): row.value for row in result}
                    if not values:
                        return None
                    valid_until = datetime.fromisoformat(values["valid_until"])
                    return ModeConfig(values["mode"], int(values["soc_floor"]), int(values["soc_ceiling"]), int(values["charge_rate_w"]) if values.get("charge_rate_w") else None, values.get("reason", "configured active mode"), valid_until, float(values["forecast_ghi"]) if values.get("forecast_ghi") else None)
                return asyncio.run(read_active())
            except RuntimeError:
                return None
        row = self.db_session_factory.get("strategy.active")
        if not row:
            return None
        valid_until = row.get("valid_until")
        if isinstance(valid_until, str):
            valid_until = datetime.fromisoformat(valid_until)
        return ModeConfig(row["mode"], int(row["soc_floor"]), int(row["soc_ceiling"]), row.get("charge_rate_w"), row.get("reason", "configured active mode"), valid_until, row.get("forecast_ghi"))

    def _store_active_mode_sync(self, mode: ModeConfig) -> None:
        if isinstance(self.db_session_factory, dict):
            self.db_session_factory["strategy.active"] = self._mode_payload(mode) | {"charge_rate_w": mode.charge_rate_w}
            return
        if self.db_session_factory is None:
            return
        try:
            import asyncio
            async def write_active() -> None:
                values = self._mode_payload(mode) | {"charge_rate_w": mode.charge_rate_w}
                async with self.db_session_factory() as session:
                    for key, value in values.items():
                        await session.execute(text("""
                            insert into settings (key, value, encrypted, updated_at) values (:key, :value, false, now())
                            on conflict (key) do update set value=:value, updated_at=now()
                        """), {"key": f"strategy.active.{key}", "value": "" if value is None else str(value)})
                    await session.commit()
            asyncio.run(write_active())
        except RuntimeError:
            LOGGER.warning("Unable to persist active strategy mode from a running event loop")

    def _insert_strategy_decision_sync(self, mode: ModeConfig, *, applied: bool) -> None:
        if isinstance(self.db_session_factory, dict):
            self.db_session_factory.setdefault("strategy_decisions", []).append(self._mode_payload(mode) | {"timestamp": self._now().isoformat(), "applied_at": self._now().isoformat() if applied else None})
            return
        if self.db_session_factory is None:
            return
        try:
            import asyncio
            async def insert_row() -> None:
                async with self.db_session_factory() as session:
                    await session.execute(text("""
                        insert into strategy_decisions (timestamp, mode, soc_floor, soc_ceiling, forecast_ghi, trigger_reason, applied_at)
                        values (:timestamp, :mode, :soc_floor, :soc_ceiling, :forecast_ghi, :trigger_reason, :applied_at)
                    """), {"timestamp": self._now(), "mode": mode.mode, "soc_floor": mode.soc_floor, "soc_ceiling": mode.soc_ceiling, "forecast_ghi": mode.forecast_ghi, "trigger_reason": mode.reason, "applied_at": self._now() if applied else None})
                    await session.commit()
            asyncio.run(insert_row())
        except RuntimeError:
            LOGGER.warning("Unable to insert strategy decision from a running event loop")

    def _insert_setpoint_log_sync(self, decision: StrategyDecision, battery_soc: Any, grid_power: Any, ack_received: bool, ack_latency_ms: int | None) -> None:
        row = {"timestamp": self._now().isoformat(), "source": "strategy", "soc_floor": decision.soc_floor, "soc_ceiling": decision.soc_ceiling, "charge_rate_w": decision.charge_rate_w, "discharge_allowed": decision.discharge_allowed, "battery_soc_at_time": battery_soc, "grid_power_at_time": grid_power, "trigger_reason": decision.reason, "ack_received": ack_received, "ack_latency_ms": ack_latency_ms}
        if isinstance(self.db_session_factory, dict):
            self.db_session_factory.setdefault("setpoint_log", []).append(row)
            return
        if self.db_session_factory is None:
            return
        try:
            import asyncio
            async def insert_row() -> None:
                async with self.db_session_factory() as session:
                    await session.execute(text("""
                        insert into setpoint_log (timestamp, source, soc_floor, soc_ceiling, charge_rate_w, discharge_allowed, battery_soc_at_time, grid_power_at_time, trigger_reason, ack_received, ack_latency_ms)
                        values (:timestamp, :source, :soc_floor, :soc_ceiling, :charge_rate_w, :discharge_allowed, :battery_soc_at_time, :grid_power_at_time, :trigger_reason, :ack_received, :ack_latency_ms)
                    """), row)
                    await session.commit()
            asyncio.run(insert_row())
        except RuntimeError:
            LOGGER.warning("Unable to insert setpoint log from a running event loop")


class ReplaySession:
    """Scaffold for future no-hardware strategy replay/backtesting."""

    def __init__(self, start: datetime, end: datetime) -> None:
        self.start = start
        self.end = end

    def run(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Replay simulation will load telemetry_log and setpoint_log in a future implementation")
