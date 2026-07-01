"""Trajectory tracker for strategy v3 (Component B)."""

from __future__ import annotations

from datetime import datetime

from .constants import Settings
from .models import SlotPlan, TrackerResult


class TrajectoryTracker:
    """Stateless: every :meth:`evaluate` call re-derives bias/limits from the current plan.

    The 15-min replan is the drift-correction mechanism (spec 4.2/15) — the tracker itself
    keeps no latch state, unlike v2's floor_schedule.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, now: datetime, soc_actual_pct: float, plan: SlotPlan) -> TrackerResult:
        ceiling_effective = 100.0 if plan.friday_full_cycle else float(self.settings.soc_ceiling)

        if plan.solver_status == "FALLBACK":
            return TrackerResult(
                bias_w=0,
                floor_dyn_pct=float(self.settings.soc_floor),
                ceil_dyn_pct=ceiling_effective,
            )

        soc_plan_pct = plan.soc_plan_pct(now)
        error_pct = soc_actual_pct - soc_plan_pct

        if abs(error_pct) < self.settings.traj_deadband_pct:
            bias_w = 0
        else:
            raw_bias_w = -(error_pct / 100.0 * self.settings.capacity_wh / self.settings.traj_tau_hours)
            bias_w = int(_clamp(raw_bias_w, -self.settings.traj_bias_max_w, self.settings.traj_bias_max_w))

        band = self.settings.traj_band_pct
        floor_dyn_pct = max(float(self.settings.soc_floor), soc_plan_pct - band)
        ceil_dyn_pct = min(ceiling_effective, soc_plan_pct + band)
        return TrackerResult(bias_w=bias_w, floor_dyn_pct=floor_dyn_pct, ceil_dyn_pct=ceil_dyn_pct)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
