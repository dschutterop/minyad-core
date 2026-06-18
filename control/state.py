"""Shared state models for Minyad battery control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ControlState(Enum):
    """Battery charge hysteresis controller states."""

    IDLE = "IDLE"
    CHARGING = "CHARGING"
    DISCHARGING = "DISCHARGING"
    COOLDOWN = "COOLDOWN"


@dataclass(slots=True)
class BatteryStatus:
    """Latest bridge telemetry and controller status snapshot."""

    soc: int | None = None
    soh: int | None = None
    power_w: int | None = None
    voltage: float | None = None
    mode: int | None = None
    mode_label: str | None = None
    charge_i: int | None = None
    state: ControlState = ControlState.IDLE
    override_mode: str = "none"

    def as_payload(self) -> dict[str, Any]:
        return {
            "soc": self.soc,
            "soh": self.soh,
            "power_w": self.power_w,
            "voltage": self.voltage,
            "mode": self.mode,
            "mode_label": self.mode_label,
            "charge_i": self.charge_i,
            "state": self.state.value,
            "override_mode": self.override_mode,
        }
