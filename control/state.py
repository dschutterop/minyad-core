"""Shared state models for Minyad battery control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ControlState(Enum):
    """Battery charge hysteresis controller states."""

    IDLE = "IDLE"
    CHARGING = "CHARGING"
    COOLDOWN = "COOLDOWN"


@dataclass(slots=True)
class BatteryStatus:
    """Latest bridge telemetry and controller status snapshot."""

    soc: int | None = None
    power_w: int | None = None
    voltage: float | None = None
    state: ControlState = ControlState.IDLE
    override_mode: str = "none"

    def as_payload(self) -> dict[str, Any]:
        return {
            "soc": self.soc,
            "power_w": self.power_w,
            "voltage": self.voltage,
            "state": self.state.value,
            "override_mode": self.override_mode,
        }
