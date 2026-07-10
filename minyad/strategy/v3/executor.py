"""Reactive balancer for strategy v3 (Component C).

Port of v2's ``StrategyExecutor`` with the changes from spec 5: no SoC clamp at all (the guard
is the sole SoC authority), the tracker's ``bias_w`` replaces the flat price-discharge bias, and
the grid-charge-window force-charge is sized to the plan's ``planned_grid_charge_w`` instead of
blindly forcing hardware-max charge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .constants import Settings
from .models import ExecutorState, SlotPlan, StrategyDecision, TrackerResult


class StrategyExecutor:
    def __init__(self, settings: Settings, *, clock: Callable[[], float] | None = None, now: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self._clock = clock or __import__("time").monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.current_setpoint_w = 0
        self._direction: int | None = None
        self._first_seen: float | None = None
        self._export_blocked = False
        self._last_export_trim_sample: tuple[int, int] | None = None
        self._grid_charge_ceiling_reached = False

    def tick(self, state: ExecutorState, plan: SlotPlan, tracker: TrackerResult) -> StrategyDecision:
        now = self._now()
        current = state.current_setpoint_w if state.current_setpoint_w is not None else self.current_setpoint_w
        slot = plan.slot_containing(now)
        planned_grid_charge_w = slot.planned_grid_charge_w if slot else 0
        planned_export_w = slot.planned_export_w if slot else 0

        in_grid_charge = planned_grid_charge_w > 0
        self._update_grid_charge_ceiling(in_grid_charge, state, tracker)
        force_grid_charge = in_grid_charge and (state.battery_soc is None or not self._grid_charge_ceiling_reached)

        if force_grid_charge:
            candidate, reason = self._forced_grid_charge_candidate(state, planned_grid_charge_w)
        else:
            candidate, reason = self._balance_candidate(state, tracker, current)

        candidate, reason = self._apply_export_block(state, planned_export_w, current, candidate, reason)

        if abs(candidate - current) < self.settings.jitter_w:
            candidate = current
            reason += f"; jitter suppressed (<{self.settings.jitter_w}W)"

        self.current_setpoint_w = int(candidate)
        return StrategyDecision(
            now,
            int(candidate),
            state.battery_soc,
            state.net_grid_w,
            tracker.bias_w,
            tracker.floor_dyn_pct,
            tracker.ceil_dyn_pct,
            reason,
            plan.solver_status,
        )

    def _update_grid_charge_ceiling(self, in_grid_charge: bool, state: ExecutorState, tracker: TrackerResult) -> None:
        # Sticky ceiling latch, exactly as v2, but against the tracker's dynamic ceiling so we
        # don't oscillate at the boundary when SoC dips a fraction below it.
        if not in_grid_charge:
            self._grid_charge_ceiling_reached = False
            return
        if state.battery_soc is None:
            return
        band = self.settings.soc_hysteresis_pct
        if state.battery_soc >= tracker.ceil_dyn_pct:
            self._grid_charge_ceiling_reached = True
        elif state.battery_soc <= tracker.ceil_dyn_pct - band:
            self._grid_charge_ceiling_reached = False

    def _forced_grid_charge_candidate(self, state: ExecutorState, planned_grid_charge_w: int) -> tuple[float, str]:
        load_now_w_estimate = max(0.0, state.net_grid_w + state.battery_power_w + state.pv_now_w)
        candidate = min(
            planned_grid_charge_w + max(0.0, state.pv_now_w - load_now_w_estimate),
            self.settings.effective_max_charge_w,
        )
        return candidate, f"planned grid charge active ({planned_grid_charge_w}W); forcing charge"

    def _balance_candidate(self, state: ExecutorState, tracker: TrackerResult, current: int) -> tuple[float, str]:
        error_w = state.net_grid_w - self.settings.grid_target_w
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
        candidate = current - delta + tracker.bias_w
        reason = f"balancing grid to target; grid offset {error_w}W"
        if tracker.bias_w:
            reason += f"; trajectory bias {tracker.bias_w}W applied"
        candidate = _clamp(candidate, -self.settings.max_discharge_w, self.settings.effective_max_charge_w)
        return candidate, reason

    def _apply_export_block(
        self, state: ExecutorState, planned_export_w: int, current: int, candidate: float, reason: str
    ) -> tuple[float, str]:
        # Export block with hysteresis: once export exceeds threshold, block discharge until
        # export falls back by at least hysteresis_w. The threshold widens by planned_export_w
        # when the plan intends to export this slot (only possible with export_cap_w > 0).
        threshold = self.settings.export_block_threshold_w + (planned_export_w if planned_export_w > 0 else 0)
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

    def _trim_discharge_during_export(self, state: ExecutorState, current: int, candidate: float) -> tuple[float, str]:
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


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
