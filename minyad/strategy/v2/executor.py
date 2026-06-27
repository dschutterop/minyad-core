"""Real-time executor for strategy v2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .constants import Settings
from .models import DayPlan, ExecutorState, StrategyDecision


class StrategyExecutor:
    def __init__(self, settings: Settings, plan: DayPlan, *, clock: Callable[[], float] | None = None, now: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.plan = plan
        self._clock = clock or __import__("time").monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.current_setpoint_w = 0
        self._direction: int | None = None
        self._first_seen: float | None = None

    def set_plan(self, plan: DayPlan) -> None:
        self.plan = plan

    def tick(self, state: ExecutorState) -> StrategyDecision:
        now = self._now()
        current = state.current_setpoint_w if state.current_setpoint_w is not None else self.current_setpoint_w
        in_grid_charge = self.plan.in_grid_charge_window(now)
        in_price_discharge = self.plan.in_price_discharge_window(now)

        if in_grid_charge and (state.battery_soc is None or state.battery_soc < self.plan.effective_soc_ceiling):
            candidate = self.settings.effective_max_charge_w
            reason = "grid charge window active; forcing max charge"
        else:
            error_w = state.net_grid_w - self.settings.int("strategy.grid_target_w")
            direction = 1 if error_w > 0 else -1 if error_w < 0 else 0
            if abs(error_w) < self.settings.ramp_floor_w:
                candidate = current
                reason = f"within deadband ({error_w}W)"
            elif not self._ramp_hold_satisfied(direction):
                candidate = current
                reason = f"ramp hold active for {'import' if direction > 0 else 'export'}"
            else:
                delta = _clamp(int(error_w * self.settings.balance_gain), -self.settings.ramp_ceiling_w, self.settings.ramp_ceiling_w)
                bias = -self.settings.price_discharge_bias_w if in_price_discharge else 0
                candidate = current - delta + bias
                reason = f"balancing grid to target; grid offset {error_w}W"
                if in_price_discharge:
                    reason += "; price discharge bias applied"
                candidate = _clamp(candidate, -self.settings.max_discharge_w, self.settings.effective_max_charge_w)

        if state.net_grid_w < -self.settings.export_block_threshold_w and candidate < 0:
            candidate = 0
            reason = "discharge blocked during export"
        candidate, limit_reason = self._apply_soc_limits(candidate, state)
        if limit_reason:
            reason = limit_reason
        if abs(candidate - current) < self.settings.jitter_w:
            candidate = current
            reason += f"; jitter suppressed (<{self.settings.jitter_w}W)"
        self.current_setpoint_w = int(candidate)
        return StrategyDecision(now, int(candidate), state.battery_soc, state.net_grid_w, state.solar_forecast_w, self.plan.solar_mode, reason, self.plan.date, in_grid_charge, in_price_discharge)

    def _ramp_hold_satisfied(self, direction: int) -> bool:
        if direction == 0:
            self._direction = None
            self._first_seen = None
            return False
        now = self._clock()
        if self._direction != direction:
            self._direction = direction
            self._first_seen = now
            return self.settings.ramp_hold_seconds <= 0
        assert self._first_seen is not None
        return now - self._first_seen >= self.settings.ramp_hold_seconds

    def _apply_soc_limits(self, candidate: int, state: ExecutorState) -> tuple[int, str | None]:
        if state.battery_soc is None:
            return candidate, None
        if state.battery_soc <= self.plan.effective_soc_floor and candidate < 0:
            return 0, f"SoC floor reached ({state.battery_soc}% <= {self.plan.effective_soc_floor}%); discharge blocked"
        if state.battery_soc >= self.plan.effective_soc_ceiling and candidate > 0:
            return 0, f"SoC ceiling reached ({state.battery_soc}% >= {self.plan.effective_soc_ceiling}%); charge blocked"
        return candidate, None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
