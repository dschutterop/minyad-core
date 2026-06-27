"""Always-on safety guard for v2 setpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from .constants import Settings
from .models import DayPlan, ExecutorState


class SoCGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._discharge_blocked = False
        self._charge_blocked = False

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
            band = self.settings.soc_hysteresis_pct
            soc = state.battery_soc

            if soc <= plan.effective_soc_floor:
                self._discharge_blocked = True
            elif soc >= plan.effective_soc_floor + band:
                self._discharge_blocked = False

            if soc >= plan.effective_soc_ceiling:
                self._charge_blocked = True
            elif soc <= plan.effective_soc_ceiling - band:
                self._charge_blocked = False

            if self._discharge_blocked:
                setpoint_w = max(0, setpoint_w)
            if self._charge_blocked:
                setpoint_w = min(0, setpoint_w)
        return int(setpoint_w)
