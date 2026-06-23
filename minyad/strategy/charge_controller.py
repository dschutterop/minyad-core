"""Real-time battery charge/discharge strategy for Minyad.

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
DEFAULT_MAX_DISCHARGE_W = 5000
DEFAULT_DEBOUNCE_SECONDS = 30
DEFAULT_JITTER_W = 50
DEFAULT_RAMP_FLOOR_W = 200
DEFAULT_RAMP_CEILING_W = 1000
DEFAULT_RAMP_HOLD_SECONDS = 120
ACK_TIMEOUT_SECONDS = 30

TOPIC_SETPOINT_JSON = "minyad/battery/setpoint"
TOPIC_STRATEGY_ACTIVE = "minyad/strategy/active"
TOPIC_BRIDGE_CHARGE_W = "minyad/control/charge_w"
TOPIC_BRIDGE_DISCHARGE_W = "minyad/control/discharge_w"
TOPIC_BATTERY_PREFIX = "minyad/battery/"
TOPIC_GRID_PREFIX = "minyad/grid/"
TOPIC_DSMR_NET_POWER = "minyad/dsmr/net_power_w"
TOPIC_GRID_NET_POWER = "minyad/grid/net_power_w"
TOPIC_PROMPT_GOODWE_BATTERY = "goodwe/battery"
TOPIC_PROMPT_DSMR_READING = "dsmr/reading"


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
    """A concrete real-time power-balancing setpoint decision.

    apparent_load_at_eval is grid_power + battery_power; solar production is not
    included because it is not tracked here — treat it as a lower bound on actual
    home consumption during daylight hours.
    """

    mode: str
    soc_floor: int
    soc_ceiling: int
    setpoint_w: int | None  # negative = charge, positive = discharge
    discharge_allowed: bool
    reason: str
    valid_until: datetime
    grid_power_at_eval: int
    battery_power_at_eval: int
    apparent_load_at_eval: int
    setpoint_delta: int


class ChargeController:
    """MQTT-only strategy engine built around real-time grid balancing.

    Live broker inspection was attempted with the required ``mosquitto_sub``
    commands before code changes, but this container does not have the binary.
    Repository reconciliation shows actual bridge topics differ from the prompt:
    GoodWe publishes scalar retained topics under ``minyad/battery/`` and
    consumes ``minyad/control/charge_w`` / ``minyad/control/discharge_w``;
    DSMR publishes ``minyad/grid/net_power_w``.  The prompt JSON topics are
    still supported for forward compatibility and observability.
    """

    def __init__(
        self,
        mqtt: Any | None = None,
        *,
        db_session_factory: Any | None = None,
        now: Any | None = None,
        ack_timeout_seconds: int = ACK_TIMEOUT_SECONDS,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
        jitter_w: int = DEFAULT_JITTER_W,
    ) -> None:
        self.mqtt = mqtt or MinyadMqttClient("minyad-strategy")
        self.db_session_factory = db_session_factory if db_session_factory is not None else AsyncSessionLocal
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.ack_timeout_seconds = ack_timeout_seconds
        self.debounce_seconds = debounce_seconds
        self.jitter_w = jitter_w
        self._lock = Lock()
        self._battery_state: dict[str, Any] = {}
        self._grid_power_w: int | None = None
        self._last_apply_monotonic: float | None = None
        self._last_setpoint_w: int = 0
        self._ack_event = Event()
        self._last_ack_latency_ms: int | None = None
        self._last_mode: ModeConfig | None = None
        self._ramp_candidate: dict[str, Any] | None = None
        if hasattr(self.mqtt, "subscribe"):
            for topic in (f"{TOPIC_BATTERY_PREFIX}+", f"{TOPIC_GRID_PREFIX}+", TOPIC_DSMR_NET_POWER, TOPIC_PROMPT_GOODWE_BATTERY, TOPIC_PROMPT_DSMR_READING):
                self.mqtt.subscribe(topic, self.handle_mqtt_message)

    def handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Record incoming MQTT telemetry and wake pending setpoint ACKs."""
        decoded = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        value = self._coerce_payload(decoded)
        with self._lock:
            if topic == TOPIC_PROMPT_GOODWE_BATTERY and isinstance(value, dict):
                self._battery_state.update(value)
                self._ack_event.set()
            elif topic == TOPIC_PROMPT_DSMR_READING and isinstance(value, dict):
                usage = self._w_from_any(value.get("current_electricity_usage", 0))
                delivery = self._w_from_any(value.get("current_electricity_delivery", 0))
                self._grid_power_w = usage - delivery
            elif topic.startswith(TOPIC_BATTERY_PREFIX):
                key = topic.removeprefix(TOPIC_BATTERY_PREFIX)
                self._battery_state[key] = value
                self._ack_event.set()
            elif topic in {TOPIC_GRID_NET_POWER, TOPIC_DSMR_NET_POWER}:
                self._grid_power_w = int(float(value))

    def evaluate(self) -> StrategyDecision:
        """Run the primary grid-balancing loop, then apply SoC boundaries."""
        mode = self.get_active_mode()
        with self._lock:
            soc = self._battery_state.get("soc")
            battery_power = self._battery_power_w_locked()
            grid_power = int(self._grid_power_w or 0)

        grid_target = int(self._float_setting_sync("strategy.grid_target_w", 0))
        raw_delta = grid_power - grid_target
        setpoint_delta, ramp_reason = self._held_ramp_delta(raw_delta)
        requested_sp = battery_power + setpoint_delta
        max_charge = self._max_charge_w_sync()
        max_discharge = self._max_discharge_w_sync()
        new_sp = max(-max_charge, min(max_discharge, requested_sp))
        discharge_allowed = True
        reason = f"balancing grid to {grid_target}W target; {ramp_reason}"

        if isinstance(soc, (int, float)) and soc <= mode.soc_floor:
            if new_sp > 0:
                new_sp = 0
            discharge_allowed = False
            reason = f"SoC floor breach ({soc}% <= {mode.soc_floor}%); discharge blocked after balancing"
        elif isinstance(soc, (int, float)) and soc >= mode.soc_ceiling:
            if new_sp < 0:
                new_sp = 0
            reason = f"SoC ceiling reached ({soc}% >= {mode.soc_ceiling}%); charging blocked after balancing"

        if isinstance(soc, (int, float)) and grid_power < 0 and soc < mode.soc_floor:
            LOGGER.warning("Grid export while battery below floor: soc=%s floor=%s grid_power_w=%s", soc, mode.soc_floor, grid_power)

        if abs(new_sp - self._last_setpoint_w) <= self.jitter_w:
            reason = f"{reason}; jitter suppressed; setpoint change {new_sp - self._last_setpoint_w}W <= {self.jitter_w}W"
            new_sp = self._last_setpoint_w

        return StrategyDecision(
            mode.mode, mode.soc_floor, mode.soc_ceiling, int(new_sp), discharge_allowed, reason, mode.valid_until,
            grid_power, int(battery_power), int(grid_power + battery_power), int(setpoint_delta),
        )

    def apply(self, decision: StrategyDecision) -> None:
        """Publish a setpoint through MQTT and log whether bridge telemetry ACKed it."""
        now_mono = time.monotonic()
        debounce = self._float_setting_sync("strategy.debounce_seconds", self.debounce_seconds)
        if self._last_apply_monotonic is not None and now_mono - self._last_apply_monotonic < debounce:
            LOGGER.info("Suppressing setpoint change inside %ss debounce window", self.debounce_seconds)
            return
        setpoint_w = int(decision.setpoint_w or 0)
        payload = {
            "target_soc": decision.soc_ceiling,
            "soc_floor": decision.soc_floor,
            "setpoint_w": decision.setpoint_w,
            "discharge_allowed": decision.discharge_allowed,
        }
        with self._lock:
            battery_soc = self._battery_state.get("soc")
            self._ack_event.clear()
        started = time.monotonic()
        self._publish(TOPIC_SETPOINT_JSON, json.dumps(payload))
        self._publish(TOPIC_BRIDGE_CHARGE_W, str(abs(setpoint_w) if setpoint_w < 0 else 0))
        self._publish(TOPIC_BRIDGE_DISCHARGE_W, str(setpoint_w if decision.discharge_allowed and setpoint_w > 0 else 0))
        ack_received = self._ack_event.wait(self.ack_timeout_seconds)
        ack_latency = int((time.monotonic() - started) * 1000) if ack_received else None
        self._last_ack_latency_ms = ack_latency
        self._last_apply_monotonic = now_mono
        self._last_setpoint_w = setpoint_w
        self._insert_setpoint_log_sync(decision, battery_soc, ack_received, ack_latency)
        if not ack_received:
            LOGGER.error("Setpoint write was not confirmed by battery telemetry within %ss", self.ack_timeout_seconds)

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


    def _held_ramp_delta(self, raw_delta: int) -> tuple[int, str]:
        """Apply import/export hysteresis before changing inverter setpoint.

        Positive grid power means import from grid and asks for more discharge.
        Negative grid power means export to grid and asks for more charge.  A
        direction must remain outside the configured floor for the hold time
        before we ramp, and every ramp is capped by the configured ceiling.
        """
        floor = int(self._float_setting_sync("strategy.ramp_floor_w", DEFAULT_RAMP_FLOOR_W))
        ceiling = int(self._float_setting_sync("strategy.ramp_ceiling_w", DEFAULT_RAMP_CEILING_W))
        hold_seconds = self._float_setting_sync("strategy.ramp_hold_seconds", DEFAULT_RAMP_HOLD_SECONDS)
        now = self._now()
        if abs(raw_delta) < floor:
            self._ramp_candidate = None
            return 0, f"within ramp floor {floor}W; no setpoint change"
        ceiling = max(1, ceiling)
        if hold_seconds <= 0:
            capped_delta = max(-ceiling, min(ceiling, raw_delta))
            return capped_delta, f"ramp hold disabled; applying {capped_delta}W delta capped by {ceiling}W"
        direction = 1 if raw_delta > 0 else -1
        if not self._ramp_candidate or self._ramp_candidate.get("direction") != direction:
            self._ramp_candidate = {"direction": direction, "started_at": now}
            return 0, f"ramp hold started for {'import' if direction > 0 else 'export'}; waiting {int(hold_seconds)}s"
        elapsed = (now - self._ramp_candidate["started_at"]).total_seconds()
        if elapsed < hold_seconds:
            return 0, f"ramp hold active for {int(elapsed)}s/{int(hold_seconds)}s"
        capped_delta = max(-ceiling, min(ceiling, raw_delta))
        self._ramp_candidate = {"direction": direction, "started_at": now}
        return capped_delta, f"ramp hold satisfied; applying {capped_delta}W delta capped by {ceiling}W"

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

    @staticmethod
    def _w_from_any(value: Any) -> int:
        numeric = float(value or 0)
        return int(round(numeric * 1000)) if abs(numeric) < 100 else int(round(numeric))

    def _battery_power_w_locked(self) -> int:
        for key in ("power_w", "battery_power", "battery_power_w"):
            if key in self._battery_state:
                return int(float(self._battery_state[key]))
        return 0

    def _mode_payload(self, mode: ModeConfig) -> dict[str, Any]:
        return {"mode": mode.mode, "soc_floor": mode.soc_floor, "soc_ceiling": mode.soc_ceiling, "reason": mode.reason, "valid_until": mode.valid_until.isoformat(), "forecast_ghi": mode.forecast_ghi}

    def _max_charge_w_sync(self) -> int:
        return int(self._float_setting_sync("battery.max_charge_w", DEFAULT_MAX_CHARGE_W))

    def _max_discharge_w_sync(self) -> int:
        return int(self._float_setting_sync("battery.max_discharge_w", DEFAULT_MAX_DISCHARGE_W))

    def _float_setting_sync(self, key: str, default: float) -> float:
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

    def _insert_setpoint_log_sync(self, decision: StrategyDecision, battery_soc: Any, ack_received: bool, ack_latency_ms: int | None) -> None:
        row = {
            "timestamp": self._now().isoformat(), "source": "strategy", "soc_floor": decision.soc_floor, "soc_ceiling": decision.soc_ceiling,
            "setpoint_w": decision.setpoint_w, "discharge_allowed": decision.discharge_allowed, "battery_soc_at_time": battery_soc,
            "grid_power_at_time": decision.grid_power_at_eval, "battery_power_at_time": decision.battery_power_at_eval,
            "apparent_load_at_time": decision.apparent_load_at_eval, "setpoint_delta": decision.setpoint_delta,
            "trigger_reason": decision.reason, "ack_received": ack_received, "ack_latency_ms": ack_latency_ms,
        }
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
                        insert into setpoint_log (timestamp, source, soc_floor, soc_ceiling, setpoint_w, discharge_allowed, battery_soc_at_time, grid_power_at_time, battery_power_at_time, apparent_load_at_time, setpoint_delta, trigger_reason, ack_received, ack_latency_ms)
                        values (:timestamp, :source, :soc_floor, :soc_ceiling, :setpoint_w, :discharge_allowed, :battery_soc_at_time, :grid_power_at_time, :battery_power_at_time, :apparent_load_at_time, :setpoint_delta, :trigger_reason, :ack_received, :ack_latency_ms)
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
