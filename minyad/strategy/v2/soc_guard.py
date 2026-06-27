"""Always-on safety guard for v2 setpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from .constants import Settings
from .models import DayPlan, ExecutorState


class SoCGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def apply(self, setpoint_w: int, state: ExecutorState, plan: DayPlan, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        if state.bridge_last_seen is not None:
            last_seen = state.bridge_last_seen
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if (now - last_seen.astimezone(timezone.utc)).total_seconds() > self.settings.bridge_stale_seconds:
                return 0
        if state.battery_voltage is not None and state.battery_voltage < self.settings.voltage_floor_v:
            return 0
        if state.battery_soc is not None:
            if state.battery_soc <= plan.effective_soc_floor:
                setpoint_w = max(0, setpoint_w)
            if state.battery_soc >= plan.effective_soc_ceiling:
                setpoint_w = min(0, setpoint_w)
        return int(setpoint_w)
