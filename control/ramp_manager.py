"""Async ramp manager for battery charge setpoints."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from math import floor
from time import monotonic

LOGGER = logging.getLogger(__name__)
STEADY_REEVALUATE_S = 30


class RampManager:
    """Gradually ramps charge setpoints with externally supplied P1 feedback."""

    def __init__(
        self,
        on_write_setpoint: Callable[[int, float], Awaitable[None]],
        ramp_steps: int = 4,
        ramp_interval_s: int = 15,
        write_min_gap_s: int = 15,
        max_charge_a: int = 30,
    ) -> None:
        if ramp_steps <= 0:
            raise ValueError("ramp_steps must be greater than 0")
        if ramp_interval_s < 0:
            raise ValueError("ramp_interval_s must be non-negative")
        if write_min_gap_s < 0:
            raise ValueError("write_min_gap_s must be non-negative")
        if max_charge_a < 0:
            raise ValueError("max_charge_a must be non-negative")

        self._on_write_setpoint = on_write_setpoint
        self._ramp_steps = ramp_steps
        self._ramp_interval_s = ramp_interval_s
        self._write_min_gap_s = write_min_gap_s
        self._max_charge_a = max_charge_a

        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None

        self._original_target_w = 0
        self._current_setpoint_w = 0
        self._surplus_w = 0
        self._vbattery1 = 0.0
        self._last_write_at: float | None = None
        self._is_ramping = False
        self._step_number = 0

    async def start(self, target_w: int) -> None:
        """Begin ramp toward target_w. Cancels any active ramp first."""
        self._loop = asyncio.get_running_loop()
        await self._cancel_task()
        self._wake_event = asyncio.Event()
        target_w = max(0, int(target_w))
        async with self._lock:
            self._original_target_w = target_w
            self._is_ramping = target_w > 0
            self._step_number = 0
            initial_w = self._round_down_to_amp(target_w // self._ramp_steps, self._vbattery1)
            initial_w = self._cap_setpoint(initial_w, target_w, self._vbattery1)
            await self._write_locked(initial_w, step_label="1", reason="ramp_start", enforce_gap=False)
        if target_w > 0:
            self._task = asyncio.create_task(self._run(), name="ramp-manager")

    async def stop(self) -> None:
        """Immediately write 0, cancel ramp, reset state."""
        self._loop = asyncio.get_running_loop()
        await self._cancel_task()
        async with self._lock:
            self._original_target_w = 0
            self._is_ramping = False
            self._step_number = 0
            await self._write_locked(0, step_label="stop", reason="stop", enforce_gap=False)
            self._wake_event = None

    def update_surplus(self, surplus_w: int) -> None:
        """Called externally on every P1 update (~1s). Thread-safe."""
        self._schedule_update("_surplus_w", int(surplus_w))

    def update_voltage(self, voltage: float) -> None:
        """Called externally on every battery poll (~30s). Thread-safe."""
        self._schedule_update("_vbattery1", float(voltage))

    @property
    def current_setpoint_w(self) -> int:
        """Last written setpoint in watts."""
        return self._current_setpoint_w

    @property
    def is_ramping(self) -> bool:
        """True while ramp is in progress, False in steady state or stopped."""
        return self._is_ramping

    async def _run(self) -> None:
        try:
            while True:
                async with self._lock:
                    interval = self._ramp_interval_s if self._is_ramping else STEADY_REEVALUATE_S
                    event = self._wake_event
                if event is None:
                    return
                try:
                    await asyncio.wait_for(event.wait(), timeout=interval)
                except TimeoutError:
                    pass
                event.clear()
                async with self._lock:
                    if self._original_target_w <= 0:
                        return
                    await self._advance_locked()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Ramp manager task failed")
            raise

    async def _advance_locked(self) -> None:
        target_w = min(max(0, self._surplus_w), self._original_target_w)
        reason = None
        increment = target_w // self._ramp_steps
        if self._is_ramping and self._surplus_w > target_w * 1.5:
            increment *= 2
            reason = "skip_ahead"
        if self._is_ramping and self._surplus_w < self._current_setpoint_w:
            reason = "downward_correction"
            next_w = target_w
        elif self._is_ramping:
            next_w = self._current_setpoint_w + increment
        else:
            next_w = target_w
        next_w = self._round_down_to_amp(next_w, self._vbattery1)
        next_w = self._cap_setpoint(next_w, target_w, self._vbattery1)

        tolerance_w = self._one_amp_w(self._vbattery1)
        if self._is_ramping:
            self._step_number += 1
            await self._write_locked(next_w, step_label=str(min(self._step_number + 1, self._ramp_steps)), reason=reason, enforce_gap=True)
            if self._current_setpoint_w + tolerance_w >= target_w:
                self._is_ramping = False
        elif abs(next_w - self._current_setpoint_w) > tolerance_w:
            await self._write_locked(next_w, step_label="steady", reason=reason, enforce_gap=True)

    async def _write_locked(self, setpoint_w: int, *, step_label: str, reason: str | None, enforce_gap: bool) -> None:
        if enforce_gap and self._last_write_at is not None:
            wait_s = self._write_min_gap_s - (monotonic() - self._last_write_at)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
        setpoint_w = max(0, int(setpoint_w))
        voltage = self._vbattery1
        await self._on_write_setpoint(setpoint_w, voltage)
        self._current_setpoint_w = setpoint_w
        self._last_write_at = monotonic()
        LOGGER.info(
            "battery_ramp_write",
            extra={
                "event": "battery_ramp_write",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "step": step_label if step_label == "steady" else f"{step_label}/{self._ramp_steps}",
                "setpoint_w": setpoint_w,
                "surplus_w": self._surplus_w,
                "vbattery1": voltage,
                "reason": reason,
            },
        )

    async def _cancel_task(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def _schedule_update(self, attr: str, value: int | float) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            setattr(self, attr, value)
            return
        loop.call_soon_threadsafe(asyncio.create_task, self._update_locked(attr, value))

    async def _update_locked(self, attr: str, value: int | float) -> None:
        async with self._lock:
            setattr(self, attr, value)
            if attr == "_surplus_w" and self._is_ramping and value < self._current_setpoint_w and self._wake_event is not None:
                self._wake_event.set()

    def _round_down_to_amp(self, watts: int, voltage: float) -> int:
        if voltage <= 0:
            return max(0, int(watts))
        amps = floor(max(0, watts) / voltage)
        return int(amps * voltage)

    def _cap_setpoint(self, watts: int, target_w: int, voltage: float) -> int:
        hardware_cap_w = int(self._max_charge_a * voltage) if voltage > 0 else watts
        return max(0, min(int(watts), int(target_w), hardware_cap_w))

    def _one_amp_w(self, voltage: float) -> int:
        return max(1, int(voltage)) if voltage > 0 else 1
