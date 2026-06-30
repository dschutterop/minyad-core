"""Time-aware, self-correcting SoC floor schedule for strategy v2.

The v1 behaviour used a single static ``effective_soc_floor`` per night: the
battery discharged without restraint until that floor was reached, then
discharge was hard-blocked for the rest of the night — a cliff.

This module rations the available discharge budget (``start_soc`` down to the
hard ``effective_floor``) across the night in proportion to *expected*
consumption, producing a floor that glides down smoothly. Every agent tick it
compares actual consumption so far against the expectation and applies a
clamped drift factor, so a heavier-than-forecast evening keeps a higher reserve
(throttling discharge sooner and more gently) instead of cliffing later.

Key invariants:
  * ``horizon_end`` is fixed for the whole cycle; only the distribution of the
    floor between ``horizon_start`` and ``horizon_end`` is recomputed.
  * The floor is monotone non-increasing across the cycle (a descending
    staircase — it never traps charge by rising again).
  * The floor is never below the hard ``effective_floor`` and never above the
    current SoC.

The mapping is capacity-free: the fraction of remaining expected consumption
maps linearly onto the fraction of the SoC budget still to be spent, so no
battery-capacity constant is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .consumption_profile import AMSTERDAM, ConsumptionProfile

DRIFT_MIN = 0.7
DRIFT_MAX = 1.5


@dataclass
class FloorScheduleState:
    """Mutable per-cycle floor schedule.

    Build one at the start of each discharge horizon, call :meth:`observe` with
    household load samples and :meth:`recompute` every agent tick, and read the
    active floor with :meth:`value_at`.
    """

    horizon_start: datetime
    horizon_end: datetime
    effective_floor: float
    start_soc: float
    expected_total_wh: float
    profile: ConsumptionProfile
    current_floor: float
    actual_consumed_wh: float = 0.0
    drift_factor: float = 1.0
    remaining_expected_adjusted_wh: float = 0.0
    _last_observed: datetime | None = None

    def observe(self, now: datetime, household_power_w: float) -> None:
        """Integrate an actual household-load sample into consumed energy.

        Uses the gap since the previous observation as the integration window,
        so callers only need to feed the latest instantaneous load.
        """
        if self._last_observed is not None and now > self._last_observed:
            hours = (now - self._last_observed).total_seconds() / 3600.0
            self.actual_consumed_wh += max(0.0, float(household_power_w)) * hours
        self._last_observed = now

    def recompute(self, now: datetime, current_soc: float) -> float:
        """Recompute and return the floor for ``now`` given the latest SoC."""
        clamped_now = min(max(now, self.horizon_start), self.horizon_end)

        elapsed_expected = self.profile.expected_wh_between(self.horizon_start, clamped_now)
        if elapsed_expected > 0:
            drift = self.actual_consumed_wh / elapsed_expected
        else:
            drift = 1.0
        drift = min(DRIFT_MAX, max(DRIFT_MIN, drift))
        self.drift_factor = drift

        remaining_expected = self.profile.expected_wh_between(clamped_now, self.horizon_end)
        remaining_adjusted = remaining_expected * drift
        self.remaining_expected_adjusted_wh = remaining_adjusted

        if self.expected_total_wh > 0:
            fraction = remaining_adjusted / self.expected_total_wh
        else:
            fraction = 0.0
        fraction = min(1.0, max(0.0, fraction))

        budget = self.start_soc - self.effective_floor
        planned = self.effective_floor + budget * fraction
        # Never above the current SoC, never below the hard floor.
        planned = max(self.effective_floor, min(planned, current_soc))
        # Monotone non-increasing across the cycle.
        planned = min(planned, self.current_floor)
        planned = max(self.effective_floor, planned)

        self.current_floor = planned
        return planned

    def value_at(self, now: datetime) -> float:
        """Active floor at ``now`` (the most recent :meth:`recompute` result)."""
        if now >= self.horizon_end:
            return self.effective_floor
        return self.current_floor


def recompute_floor(state: FloorScheduleState, now: datetime, current_soc: float) -> float:
    """Functional alias for :meth:`FloorScheduleState.recompute`."""
    return state.recompute(now, current_soc)


def build_floor_schedule(
    now: datetime,
    current_soc: float,
    effective_floor: float,
    horizon_start: datetime,
    horizon_end: datetime,
    profile: ConsumptionProfile,
) -> FloorScheduleState:
    """Create a fresh floor schedule for a discharge horizon.

    ``start_soc`` and the initial floor are pinned to the current SoC so the
    glide path begins from where the battery actually is.
    """
    start_soc = max(float(current_soc), float(effective_floor))
    expected_total = profile.expected_wh_between(horizon_start, horizon_end)
    return FloorScheduleState(
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        effective_floor=float(effective_floor),
        start_soc=start_soc,
        expected_total_wh=expected_total,
        profile=profile,
        current_floor=start_soc,
        _last_observed=now,
    )


def night_horizon(
    now: datetime,
    start_local: time,
    end_local: time,
    *,
    tz: ZoneInfo = AMSTERDAM,
) -> tuple[datetime, datetime]:
    """Return the night discharge window (start, end) relevant to ``now``.

    The window runs from ``start_local`` in the evening to ``end_local`` the
    next morning. If ``now`` falls in the early-morning tail of the previous
    night's window, that earlier window is returned.
    """
    local = now.astimezone(tz)
    today: date = local.date()
    start = datetime.combine(today, start_local, tz)
    end = datetime.combine(today + timedelta(days=1), end_local, tz)
    if local < start:
        prev_start = start - timedelta(days=1)
        prev_end = datetime.combine(today, end_local, tz)
        if local < prev_end:
            return prev_start, prev_end
    return start, end


def in_horizon(now: datetime, horizon_start: datetime, horizon_end: datetime) -> bool:
    return horizon_start <= now < horizon_end
