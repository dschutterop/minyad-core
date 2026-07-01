"""Always-on safety guard for v3 setpoints (Component D — the sole SoC state machine)."""

from __future__ import annotations

from datetime import datetime, timezone

from .constants import Settings
from .models import ExecutorState


class SoCGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._discharge_blocked = False
        self._charge_blocked = False

    def apply(
        self,
        setpoint_w: int,
        state: ExecutorState,
        floor_dyn_pct: float,
        ceil_dyn_pct: float,
        now: datetime | None = None,
        *,
        skip_soc_limits: bool = False,
    ) -> int:
        adjusted, _reason = self.apply_with_reason(setpoint_w, state, floor_dyn_pct, ceil_dyn_pct, now, skip_soc_limits=skip_soc_limits)
        return adjusted

    def apply_with_reason(
        self,
        setpoint_w: int,
        state: ExecutorState,
        floor_dyn_pct: float,
        ceil_dyn_pct: float,
        now: datetime | None = None,
        *,
        skip_soc_limits: bool = False,
    ) -> tuple[int, str | None]:
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
        if skip_soc_limits:
            return int(setpoint_w), None
        if state.battery_soc is not None:
            band = self.settings.soc_hysteresis_pct
            soc = state.battery_soc

            if soc <= floor_dyn_pct:
                self._discharge_blocked = True
            elif soc >= floor_dyn_pct + band:
                self._discharge_blocked = False

            if soc >= ceil_dyn_pct:
                self._charge_blocked = True
            elif soc <= ceil_dyn_pct - band:
                self._charge_blocked = False

            if self._discharge_blocked:
                adjusted = max(0, setpoint_w)
                if adjusted != setpoint_w:
                    return adjusted, f"guard: SoC floor hold ({soc}% <= {floor_dyn_pct + band}%)"
            if self._charge_blocked:
                adjusted = min(0, setpoint_w)
                if adjusted != setpoint_w:
                    return adjusted, f"guard: SoC ceiling hold ({soc}% >= {ceil_dyn_pct - band}%)"
        return int(setpoint_w), None
