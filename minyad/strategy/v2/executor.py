"""Real-time executor for strategy v2."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .constants import Settings
from .models import DayPlan, ExecutorState, StrategyDecision


class StrategyExecutor:
    def __init__(self, settings: Settings, plan: DayPlan, *, clock: Callable[[], float] | None = None, now: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self.plan = plan
        self._clock = clock or __import__("time").monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self.current_setpoint_w = 0
        self._direction: int | None = None
        self._first_seen: float | None = None
        self._soc_discharge_blocked = False
        self._soc_charge_blocked = False
        self._export_blocked = False
        self._last_export_trim_sample: tuple[int, int] | None = None
        self._grid_charge_ceiling_reached = False

    def set_plan(self, plan: DayPlan) -> None:
        self.plan = plan

    def tick(self, state: ExecutorState) -> StrategyDecision:
        now = self._now()
        current = state.current_setpoint_w if state.current_setpoint_w is not None else self.current_setpoint_w
        in_grid_charge = self.plan.in_grid_charge_window(now)
        in_price_discharge = self.plan.in_price_discharge_window(now)

        self._update_grid_charge_ceiling(in_grid_charge, state)
        force_grid_charge = in_grid_charge and (state.battery_soc is None or not self._grid_charge_ceiling_reached)

        if force_grid_charge:
            candidate = self.settings.effective_max_charge_w
            reason = "grid charge window active; forcing max charge"
        else:
            candidate, reason = self._balance_candidate(state, current, in_price_discharge)

        candidate, reason = self._apply_export_block(state, current, candidate, reason)

        candidate, limit_reason = self._apply_soc_limits(candidate, state)
        if limit_reason:
            reason = limit_reason
        if abs(candidate - current) < self.settings.jitter_w:
            candidate = current
            reason += f"; jitter suppressed (<{self.settings.jitter_w}W)"
        self.current_setpoint_w = int(candidate)
        return StrategyDecision(now, int(candidate), state.battery_soc, state.net_grid_w, state.solar_forecast_w, self.plan.solar_mode, reason, self.plan.date, in_grid_charge, in_price_discharge)

    def _update_grid_charge_ceiling(self, in_grid_charge: bool, state: ExecutorState) -> None:
        # Track whether we've hit the ceiling inside a grid charge window so we
        # don't oscillate at the boundary when SoC dips a fraction below it.
        if not in_grid_charge:
            self._grid_charge_ceiling_reached = False
            return
        if state.battery_soc is None:
            return
        band = self.settings.soc_hysteresis_pct
        if state.battery_soc >= self.plan.effective_soc_ceiling:
            self._grid_charge_ceiling_reached = True
        elif state.battery_soc <= self.plan.effective_soc_ceiling - band:
            self._grid_charge_ceiling_reached = False

    def _balance_candidate(self, state: ExecutorState, current: int, in_price_discharge: bool) -> tuple[int, str]:
        error_w = state.net_grid_w - self.settings.int("strategy.grid_target_w")
        if error_w > 0:
            direction = 1
        elif error_w < 0:
            direction = -1
        else:
            direction = 0
        if abs(error_w) < self.settings.ramp_floor_w:
            return current, f"within deadband ({error_w}W)"
        if not self._ramp_hold_satisfied(direction):
            return current, f"ramp hold active for {'import' if direction > 0 else 'export'}"
        delta = _clamp(int(error_w * self.settings.balance_gain), -self.settings.ramp_ceiling_w, self.settings.ramp_ceiling_w)
        bias = -self.settings.price_discharge_bias_w if in_price_discharge else 0
        candidate = current - delta + bias
        reason = f"balancing grid to target; grid offset {error_w}W"
        if in_price_discharge:
            reason += "; price discharge bias applied"
        candidate = _clamp(candidate, -self.settings.max_discharge_w, self.settings.effective_max_charge_w)
        return candidate, reason

    def _apply_export_block(self, state: ExecutorState, current: int, candidate: int, reason: str) -> tuple[int, str]:
        # Export block with hysteresis: once export exceeds threshold, block
        # discharge until export falls back by at least hysteresis_w.
        threshold = self.settings.export_block_threshold_w
        hysteresis = self.settings.export_block_hysteresis_w
        if state.net_grid_w < -threshold:
            self._export_blocked = True
        elif state.net_grid_w >= -(threshold - hysteresis):
            self._export_blocked = False
        if not self._export_blocked:
            self._last_export_trim_sample = None
            return candidate, reason

        active_discharge = current < -self.settings.jitter_w or state.battery_power_w > self.settings.jitter_w
        if active_discharge and current < 0:
            return self._trim_discharge_during_export(state, current, candidate)
        if candidate < 0:
            self._last_export_trim_sample = None
            return 0, "discharge blocked during export"
        self._last_export_trim_sample = None
        return candidate, reason

    def _trim_discharge_during_export(self, state: ExecutorState, current: int, candidate: int) -> tuple[int, str]:
        trim_sample = (state.net_grid_w, state.battery_power_w)
        if trim_sample == self._last_export_trim_sample:
            return current, f"waiting for fresh export telemetry before next discharge trim; grid offset {state.net_grid_w}W"
        export_trim = _clamp(int(abs(state.net_grid_w) * self.settings.balance_gain), 0, self.settings.ramp_ceiling_w)
        candidate = min(0, max(candidate, current + export_trim))
        self._last_export_trim_sample = trim_sample
        return candidate, f"trimming discharge during export; grid offset {state.net_grid_w}W"

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
        if now - self._first_seen >= self.settings.ramp_hold_seconds:
            self._first_seen = now  # reset so each ramp step requires a new hold period
            return True
        return False

    def _apply_soc_limits(self, candidate: int, state: ExecutorState) -> tuple[int, str | None]:
        if state.battery_soc is None:
            return candidate, None
        band = self.settings.soc_hysteresis_pct
        soc = state.battery_soc

        if soc <= self.plan.effective_soc_floor:
            self._soc_discharge_blocked = True
        elif soc >= self.plan.effective_soc_floor + band:
            self._soc_discharge_blocked = False

        if soc >= self.plan.effective_soc_ceiling:
            self._soc_charge_blocked = True
        elif soc <= self.plan.effective_soc_ceiling - band:
            self._soc_charge_blocked = False

        if self._soc_discharge_blocked and candidate < 0:
            return 0, f"SoC floor hold ({soc}% <= {self.plan.effective_soc_floor + band}%); discharge blocked"
        if self._soc_charge_blocked and candidate > 0:
            return 0, f"SoC ceiling hold ({soc}% >= {self.plan.effective_soc_ceiling - band}%); charge blocked"
        return candidate, None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
