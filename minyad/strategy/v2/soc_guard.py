"""Always-on safety guard for v2 setpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from .constants import Settings
from .floor_schedule import FloorScheduleState
from .models import DayPlan, ExecutorState


class SoCGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._discharge_blocked = False
        self._charge_blocked = False
        self._floor_schedule: FloorScheduleState | None = None

    def set_floor_schedule(self, schedule: FloorScheduleState | None) -> None:
        """Install (or clear) the self-correcting floor schedule.

        When set, the discharge floor comes from ``schedule.value_at(now)``
        instead of the static ``plan.effective_soc_floor``. The schedule glides
        from the start-of-night SoC down to the plan's hard floor, so it is
        always >= the static floor and the guard throttles discharge gradually
        rather than cliffing once the hard floor is hit.
        """
        self._floor_schedule = schedule

    def _active_floor(self, plan: DayPlan, now: datetime) -> float:
        if self._floor_schedule is not None:
            return self._floor_schedule.value_at(now)
        return plan.effective_soc_floor

    def apply(self, setpoint_w: int, state: ExecutorState, plan: DayPlan, now: datetime | None = None) -> int:
        adjusted, _reason = self.apply_with_reason(setpoint_w, state, plan, now)
        return adjusted

    def apply_with_reason(self, setpoint_w: int, state: ExecutorState, plan: DayPlan, now: datetime | None = None) -> tuple[int, str | None]:
        now = now or datetime.now(timezone.utc)
        if state.bridge_last_seen is not None:
            last_seen = state.bridge_last_seen
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            age_seconds = (now - last_seen.astimezone(timezone.utc)).total_seconds()
            if age_seconds > self.settings.bridge_stale_seconds:
                return 0, f"guard: bridge stale ({age_seconds:.0f}s > {self.settings.bridge_stale_seconds}s)"
        if state.battery_voltage is not None and state.battery_voltage < self.settings.voltage_floor_v:
            return 0, f"guard: battery voltage low ({state.battery_voltage:.1f}V < {self.settings.voltage_floor_v:.1f}V)"
        if state.battery_soc is not None:
            band = self.settings.soc_hysteresis_pct
            soc = state.battery_soc
            floor = self._active_floor(plan, now)

            if soc <= floor:
                self._discharge_blocked = True
            elif soc >= floor + band:
                self._discharge_blocked = False

            if soc >= plan.effective_soc_ceiling:
                self._charge_blocked = True
            elif soc <= plan.effective_soc_ceiling - band:
                self._charge_blocked = False

            if self._discharge_blocked:
                adjusted = max(0, setpoint_w)
                if adjusted != setpoint_w:
                    return adjusted, f"guard: SoC floor hold ({soc}% <= {floor + band}%)"
            if self._charge_blocked:
                adjusted = min(0, setpoint_w)
                if adjusted != setpoint_w:
                    return adjusted, f"guard: SoC ceiling hold ({soc}% >= {plan.effective_soc_ceiling - band}%)"
        return int(setpoint_w), None
