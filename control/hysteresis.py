"""Thread-safe hysteresis and manual override state for battery control."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from time import monotonic

from state import ControlState

LOGGER = logging.getLogger(__name__)


class OverrideMode(Enum):
    """Manual battery control override modes."""

    NONE = "none"
    FORCE_ON = "force_on"
    FORCE_OFF = "force_off"
    FORCE_DISCHARGE = "force_discharge"
    PAUSE = "pause"


class HysteresisController:
    """
    Decides when to start/stop charging or discharging based on sustained grid flow.

    State machines: IDLE → CHARGING → COOLDOWN → IDLE and
    IDLE → DISCHARGING → COOLDOWN → IDLE. Charging and discharging are
    mutually exclusive because both can only start from IDLE. All thresholds
    are supplied by the settings database through the constructor.
    """

    def __init__(
        self,
        *,
        start_w: int,
        stop_w: int,
        discharge_start_w: int,
        discharge_stop_w: int,
        start_duration: int,
        stop_duration: int,
        cooldown: int,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_discharge_start: Callable[[], None] | None = None,
        on_discharge_stop: Callable[[], None] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.start_w = start_w
        self.stop_w = stop_w
        self.discharge_start_w = discharge_start_w
        self.discharge_stop_w = discharge_stop_w
        self.start_duration = start_duration
        self.stop_duration = stop_duration
        self.cooldown = cooldown
        self._on_start = on_start or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_discharge_start = on_discharge_start or (lambda: None)
        self._on_discharge_stop = on_discharge_stop or (lambda: None)
        self._clock = clock
        self._lock = threading.RLock()
        self._state = ControlState.IDLE
        self._start_since: float | None = None
        self._stop_since: float | None = None
        self._cooldown_until: float | None = None
        self._override_mode = OverrideMode.NONE
        self._pause_until: float | None = None

    @property
    def state(self) -> ControlState:
        with self._lock:
            return self._state

    @property
    def override_mode(self) -> OverrideMode:
        with self._lock:
            return self._override_mode

    def set_override(self, mode: OverrideMode, duration_seconds: int | None = None) -> None:
        with self._lock:
            self._override_mode = mode
            self._pause_until = self._clock() + duration_seconds if mode is OverrideMode.PAUSE and duration_seconds else None
            if mode in {OverrideMode.FORCE_OFF, OverrideMode.FORCE_DISCHARGE} and self._state in {ControlState.CHARGING, ControlState.DISCHARGING}:
                self._transition(ControlState.IDLE, f"override {mode.value} stopped active control")
            LOGGER.info("%s override set: %s", self._timestamp(), mode.value)

    def clear_override(self) -> None:
        with self._lock:
            self._override_mode = OverrideMode.NONE
            self._pause_until = None
            LOGGER.info("%s override cleared", self._timestamp())

    def tick(self, surplus_w: int) -> ControlState | None:
        """Evaluate a new surplus sample and return the new state on transition."""
        with self._lock:
            now = self._clock()
            if self._override_mode is OverrideMode.PAUSE and self._pause_until is not None and now >= self._pause_until:
                self.clear_override()
            if self._override_mode is not OverrideMode.NONE:
                LOGGER.info("%s override %s blocks hysteresis tick at surplus=%sW", self._timestamp(), self._override_mode.value, surplus_w)
                return None

            if self._state is ControlState.COOLDOWN:
                if self._cooldown_until is not None and now >= self._cooldown_until:
                    return self._transition(ControlState.IDLE, "cooldown elapsed")
                return None

            if self._state is ControlState.IDLE:
                if surplus_w >= self.start_w:
                    if self._start_since is None:
                        self._start_since = now
                    if now - self._start_since >= self.start_duration:
                        return self._transition(ControlState.CHARGING, f"surplus {surplus_w}W sustained above {self.start_w}W")
                elif surplus_w <= self.discharge_start_w:
                    if self._start_since is None:
                        self._start_since = now
                    if now - self._start_since >= self.start_duration:
                        return self._transition(ControlState.DISCHARGING, f"import {surplus_w}W sustained below {self.discharge_start_w}W")
                else:
                    self._start_since = None
                return None

            if self._state is ControlState.CHARGING:
                if surplus_w < self.stop_w:
                    if self._stop_since is None:
                        self._stop_since = now
                    if now - self._stop_since >= self.stop_duration:
                        self._cooldown_until = now + self.cooldown
                        return self._transition(ControlState.COOLDOWN, f"surplus {surplus_w}W sustained below {self.stop_w}W")
                else:
                    self._stop_since = None
                return None

            if self._state is ControlState.DISCHARGING:
                if surplus_w > self.discharge_stop_w:
                    if self._stop_since is None:
                        self._stop_since = now
                    if now - self._stop_since >= self.stop_duration:
                        self._cooldown_until = now + self.cooldown
                        return self._transition(ControlState.COOLDOWN, f"import {surplus_w}W sustained above {self.discharge_stop_w}W")
                else:
                    self._stop_since = None
            return None

    def _transition(self, new_state: ControlState, reason: str) -> ControlState:
        old_state = self._state
        self._state = new_state
        self._start_since = None
        self._stop_since = None
        LOGGER.info("%s control transition %s -> %s: %s", self._timestamp(), old_state.value, new_state.value, reason)
        if old_state is not ControlState.CHARGING and new_state is ControlState.CHARGING:
            self._on_start()
        if old_state is ControlState.CHARGING and new_state is not ControlState.CHARGING:
            self._on_stop()
        if old_state is not ControlState.DISCHARGING and new_state is ControlState.DISCHARGING:
            self._on_discharge_start()
        if old_state is ControlState.DISCHARGING and new_state is not ControlState.DISCHARGING:
            self._on_discharge_stop()
        return new_state

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
