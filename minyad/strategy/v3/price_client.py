"""Price feed adapter for strategy v3.

The v3 spec's on-paper interface is a ``minyad/trade/prices`` topic with a
``{start, end, price_eur_kwh}`` schema — but nothing in this repo publishes
that topic/schema (v2's planner reads it too, and has always fallen back to
fixed prices as a result). The real ``minyad-trade`` service publishes
ENTSO-E day-ahead prices on ``minyad/trade/prices/da/{day}/full`` as
``[{"date", "hour", "starts_at", "price_eur_kwh"}, ...]``. v3 adapts to that
real feed so the price vector is actually live, per the price-ready-by-
construction goal. There is no export-price feed today, so ``price_export``
is always the fixed settings constant.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

MAX_CACHED_DAYS = 4


class PriceStore:
    def __init__(self) -> None:
        self._points_by_day: dict[str, list[dict[str, Any]]] = {}

    def set_from_entsoe(self, day: str, points: list[dict[str, Any]]) -> None:
        self._points_by_day[day] = points
        if len(self._points_by_day) > MAX_CACHED_DAYS:
            oldest = sorted(self._points_by_day)[0]
            del self._points_by_day[oldest]

    def _price_at(self, moment: datetime) -> float | None:
        points = self._points_by_day.get(moment.date().isoformat())
        if not points:
            return None
        target_hour = f"{moment.hour:02d}"
        for point in points:
            if point.get("hour") == target_hour:
                return float(point["price_eur_kwh"])
        return None

    def price_vectors_for(
        self,
        horizon_start: datetime,
        horizon_slots: int,
        slot_seconds: int,
        *,
        fixed_import: float,
        fixed_export: float,
    ) -> tuple[list[float], list[float]]:
        import_vec: list[float] = []
        export_vec: list[float] = []
        for i in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * i)
            price = self._price_at(slot_start)
            import_vec.append(price if price is not None else fixed_import)
            export_vec.append(fixed_export)
        return import_vec, export_vec
