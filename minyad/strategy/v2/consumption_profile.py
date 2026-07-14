"""Historical household consumption profile for strategy v2.

Until a real consumption forecast model exists, the floor schedule needs an
estimate of how much the household draws in each 15-minute slot of the day.
This module derives that estimate from the rolling history already captured in
``power_curve_rollups`` (``source='household'``, ``granularity_seconds=900``)
and exposes it as a forecast-shaped object the floor schedule can integrate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SLOT_MINUTES = 15
SLOTS_PER_DAY = (24 * 60) // SLOT_MINUTES


def slot_of(moment: datetime, tz: ZoneInfo) -> int:
    """Return the 0..95 index of the 15-minute slot containing ``moment``."""
    local = moment.astimezone(tz)
    return (local.hour * 60 + local.minute) // SLOT_MINUTES


@dataclass(frozen=True)
class ConsumptionProfile:
    """Average household load (W) per 15-minute slot of the local day."""

    slot_watts: dict[int, float] = field(default_factory=dict)
    tz: ZoneInfo = AMSTERDAM
    fallback_w: float = 0.0

    def expected_w(self, moment: datetime) -> float:
        """Expected average household power for the slot containing ``moment``."""
        return self.slot_watts.get(slot_of(moment, self.tz), self.fallback_w)

    def expected_wh_between(self, start: datetime, end: datetime) -> float:
        """Integrate expected household energy (Wh) over ``[start, end)``.

        The walk slices the interval at 15-minute slot boundaries so partial
        slots at either edge contribute proportionally.
        """
        if end <= start:
            return 0.0
        total = 0.0
        cursor = start
        while cursor < end:
            local = cursor.astimezone(self.tz)
            slot_start_minute = (local.minute // SLOT_MINUTES) * SLOT_MINUTES
            slot_start = local.replace(minute=slot_start_minute, second=0, microsecond=0)
            next_boundary = slot_start + timedelta(minutes=SLOT_MINUTES)
            segment_end = min(end, next_boundary)
            hours = (segment_end - cursor).total_seconds() / 3600.0
            total += self.expected_w(cursor) * hours
            cursor = segment_end
        return total

    @property
    def has_history(self) -> bool:
        return bool(self.slot_watts)


def build_profile_from_rows(
    rows: Iterable[tuple[datetime, Any]],
    *,
    tz: ZoneInfo = AMSTERDAM,
    fallback_w: float = 0.0,
) -> ConsumptionProfile:
    """Average ``(bucket_start, power_w)`` rollup rows into a per-slot profile."""
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for bucket_start, power_w in rows:
        if power_w is None or bucket_start is None:
            continue
        if bucket_start.tzinfo is None:
            bucket_start = bucket_start.replace(tzinfo=UTC)
        slot = slot_of(bucket_start, tz)
        sums[slot] += max(0.0, float(power_w))
        counts[slot] += 1
    slot_watts = {slot: sums[slot] / counts[slot] for slot in sums}
    return ConsumptionProfile(slot_watts=slot_watts, tz=tz, fallback_w=fallback_w)


async def load_consumption_profile(
    session_factory: Any,
    *,
    tz: ZoneInfo = AMSTERDAM,
    lookback_days: int = 14,
    fallback_w: float = 300.0,
    now: datetime | None = None,
) -> ConsumptionProfile:
    """Load the rolling household profile from ``power_curve_rollups``.

    ``fallback_w`` is used for any slot without history (and for every slot
    before the first night of operation), so the floor schedule degrades to a
    flat expectation rather than dividing by zero.
    """
    now = now or datetime.now(UTC)
    start = now - timedelta(days=lookback_days)
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select bucket_start, power_w
                from power_curve_rollups
                where source = 'household'
                  and granularity_seconds = 900
                  and bucket_start >= :start
                """
            ),
            {"start": start},
        )
        rows = [(row.bucket_start, row.power_w) for row in result]
    return build_profile_from_rows(rows, tz=tz, fallback_w=fallback_w)
