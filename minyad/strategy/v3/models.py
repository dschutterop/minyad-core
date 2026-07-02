"""Dataclasses for strategy v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Slot:
    start: datetime
    soc_target_pct: float
    planned_grid_charge_w: int
    planned_export_w: int
    pv_forecast_w: int
    load_forecast_w: int
    price_import: float
    price_export: float
    charge_w: int = 0
    discharge_w: int = 0

    @property
    def surplus_w(self) -> int:
        """Spec 7: energy that would otherwise be exported/curtailed, available for Vesper."""
        return max(0, self.pv_forecast_w - self.load_forecast_w - self.charge_w)


@dataclass(frozen=True)
class SlotPlan:
    generated_at: datetime
    valid_from: datetime
    slot_seconds: int
    soc_start_pct: float
    slots: list[Slot] = field(default_factory=list)
    friday_full_cycle: bool = False
    solver_status: str = "Optimal"
    pv_calibration_factor: float = 0.0
    market_signal_ids: list[str] = field(default_factory=list)
    constraint_reasons: list[str] = field(default_factory=list)

    def slot_containing(self, now: datetime) -> Slot | None:
        for slot in self.slots:
            slot_end = slot.start + timedelta(seconds=self.slot_seconds)
            if slot.start <= now < slot_end:
                return slot
        return None

    def soc_plan_pct(self, now: datetime) -> float:
        """Linearly interpolate the planned SoC (%) at ``now``."""
        if not self.slots:
            return self.soc_start_pct
        if now <= self.valid_from:
            return self.soc_start_pct
        prev_soc = self.soc_start_pct
        prev_t = self.valid_from
        for slot in self.slots:
            slot_end = slot.start + timedelta(seconds=self.slot_seconds)
            if now <= slot_end:
                span = (slot_end - prev_t).total_seconds()
                if span <= 0:
                    return slot.soc_target_pct
                fraction = (now - prev_t).total_seconds() / span
                return prev_soc + (slot.soc_target_pct - prev_soc) * fraction
            prev_soc = slot.soc_target_pct
            prev_t = slot_end
        return self.slots[-1].soc_target_pct


@dataclass(frozen=True)
class TrackerResult:
    bias_w: int
    floor_dyn_pct: float
    ceil_dyn_pct: float


@dataclass(frozen=True)
class ExecutorState:
    net_grid_w: int
    battery_soc: float | None = None
    battery_power_w: int = 0
    pv_now_w: int = 0
    battery_voltage: float | None = None
    bridge_last_seen: datetime | None = None
    current_setpoint_w: int = 0


@dataclass(frozen=True)
class StrategyDecision:
    timestamp: datetime
    setpoint_w: int
    soc: float | None
    net_grid_w: int
    bias_w: int
    floor_dyn_pct: float
    ceil_dyn_pct: float
    reason: str
    solver_status: str
    market_signal_ids: list[str] = field(default_factory=list)
    constraint_reasons: list[str] = field(default_factory=list)
