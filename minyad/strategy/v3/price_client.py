"""Market-signal adapter for strategy v3.

External market/trade systems feed strategy v3 through normalized signals on
``minyad/market/signals``. During rollout we also keep the legacy day-ahead
ENTSO-E payload from ``minyad/trade/prices/da/{day}/full`` as a fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)
MAX_CACHED_DAYS = 4
SUPPORTED_SIGNAL_TYPES = {"price_vector"}
RESERVED_SIGNAL_TYPES = {
    "grid_constraint",
    "soc_reservation",
    "capacity_reservation",
    "activation_request",
    "allocation_hint",
}


@dataclass(frozen=True)
class PlannerMarketInputs:
    price_import: list[float]
    price_export: list[float]
    max_import_w: list[float | None]
    max_export_w: list[float | None]
    min_soc_pct: list[float | None]
    max_soc_pct: list[float | None]
    reserved_charge_headroom_wh: list[float]
    reserved_discharge_wh: list[float]
    objective_adjustments: list[dict[str, Any]]
    signal_ids_by_slot: list[list[str]]
    constraint_reasons_by_slot: list[list[str]]

    @property
    def market_signal_ids(self) -> list[str]:
        return _unique(item for slot in self.signal_ids_by_slot for item in slot)

    @property
    def constraint_reasons(self) -> list[str]:
        return _unique(item for slot in self.constraint_reasons_by_slot for item in slot)


@dataclass(frozen=True)
class _PriceVectorSignal:
    signal_id: str
    source: str
    created_at: datetime
    valid_from: datetime
    valid_until: datetime
    priority: int
    prices_by_start: dict[datetime, tuple[float, float]]

    @property
    def reason(self) -> str:
        return f"price_vector:{self.source}"


@dataclass
class PriceStore:
    _points_by_day: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _price_vector_signals: dict[str, _PriceVectorSignal] = field(default_factory=dict)
    _ignored_signal_types: set[str] = field(default_factory=set)

    def set_from_entsoe(self, day: str, points: list[dict[str, Any]]) -> None:
        self._points_by_day[day] = points
        if len(self._points_by_day) > MAX_CACHED_DAYS:
            oldest = sorted(self._points_by_day)[0]
            del self._points_by_day[oldest]

    def set_market_signal(self, payload: dict[str, Any] | list[dict[str, Any]], *, now: datetime | None = None) -> None:
        signals = payload if isinstance(payload, list) else [payload]
        for signal in signals:
            self._set_one_market_signal(signal, now=now)

    def _set_one_market_signal(self, signal: dict[str, Any], *, now: datetime | None) -> None:
        signal_type = str(signal.get("type") or "")
        if signal_type not in SUPPORTED_SIGNAL_TYPES:
            self._log_ignored_type_once(signal_type or "<missing>")
            return
        if signal_type == "price_vector":
            parsed = self._parse_price_vector_signal(signal)
            if parsed is None:
                return
            if _is_expired(parsed.valid_until, now):
                self._price_vector_signals.pop(parsed.signal_id, None)
                return
            self._price_vector_signals[parsed.signal_id] = parsed

    def _log_ignored_type_once(self, signal_type: str) -> None:
        if signal_type in self._ignored_signal_types:
            return
        self._ignored_signal_types.add(signal_type)
        if signal_type in RESERVED_SIGNAL_TYPES:
            LOGGER.info("Ignoring reserved market signal type=%s", signal_type)
        else:
            LOGGER.warning("Ignoring unknown market signal type=%s", signal_type)

    def _parse_price_vector_signal(self, signal: dict[str, Any]) -> _PriceVectorSignal | None:
        try:
            signal_id = str(signal["id"])
            source = str(signal.get("source") or "unknown")
            created_at = _parse_dt(signal["created_at"])
            valid_from = _parse_dt(signal["valid_from"])
            valid_until = _parse_dt(signal["valid_until"])
            priority = int(signal.get("priority", 50))
            body = signal.get("payload") or {}
            prices_by_start: dict[datetime, tuple[float, float]] = {}
            for slot in body.get("slots") or []:
                start = _parse_dt(slot["start"])
                prices_by_start[start] = (
                    float(slot["price_import_eur_kwh"]),
                    float(slot.get("price_export_eur_kwh", 0.0)),
                )
        except (KeyError, TypeError, ValueError):
            LOGGER.warning("Ignoring invalid price_vector market signal", exc_info=True)
            return None
        if valid_until <= valid_from or not prices_by_start:
            LOGGER.warning("Ignoring empty or invalid price_vector market signal id=%s", signal_id)
            return None
        return _PriceVectorSignal(
            signal_id=signal_id,
            source=source,
            created_at=created_at,
            valid_from=valid_from,
            valid_until=valid_until,
            priority=priority,
            prices_by_start=prices_by_start,
        )

    def planner_inputs_for(
        self,
        horizon_start: datetime,
        horizon_slots: int,
        slot_seconds: int,
        *,
        fixed_import: float,
        fixed_export: float,
        now: datetime | None = None,
    ) -> PlannerMarketInputs:
        import_vec = [fixed_import] * horizon_slots
        export_vec = [fixed_export] * horizon_slots
        signal_ids_by_slot: list[list[str]] = [[] for _ in range(horizon_slots)]
        reasons_by_slot: list[list[str]] = [[] for _ in range(horizon_slots)]

        active_signals = self._active_price_vector_signals(now or horizon_start)
        if active_signals:
            self._apply_normalized_price_vectors(
                active_signals,
                horizon_start,
                horizon_slots,
                slot_seconds,
                import_vec,
                export_vec,
                signal_ids_by_slot,
                reasons_by_slot,
            )
        else:
            self._apply_legacy_prices(horizon_start, horizon_slots, slot_seconds, import_vec)

        return PlannerMarketInputs(
            price_import=import_vec,
            price_export=export_vec,
            max_import_w=[None] * horizon_slots,
            max_export_w=[None] * horizon_slots,
            min_soc_pct=[None] * horizon_slots,
            max_soc_pct=[None] * horizon_slots,
            reserved_charge_headroom_wh=[0.0] * horizon_slots,
            reserved_discharge_wh=[0.0] * horizon_slots,
            objective_adjustments=[{} for _ in range(horizon_slots)],
            signal_ids_by_slot=signal_ids_by_slot,
            constraint_reasons_by_slot=reasons_by_slot,
        )

    def price_vectors_for(
        self,
        horizon_start: datetime,
        horizon_slots: int,
        slot_seconds: int,
        *,
        fixed_import: float,
        fixed_export: float,
    ) -> tuple[list[float], list[float]]:
        inputs = self.planner_inputs_for(
            horizon_start,
            horizon_slots,
            slot_seconds,
            fixed_import=fixed_import,
            fixed_export=fixed_export,
        )
        return inputs.price_import, inputs.price_export

    def _active_price_vector_signals(self, now: datetime) -> list[_PriceVectorSignal]:
        active: list[_PriceVectorSignal] = []
        expired: list[str] = []
        for signal_id, signal in self._price_vector_signals.items():
            if _is_expired(signal.valid_until, now):
                expired.append(signal_id)
            else:
                active.append(signal)
        for signal_id in expired:
            del self._price_vector_signals[signal_id]
        return sorted(active, key=lambda item: (item.priority, item.created_at), reverse=True)

    def _apply_normalized_price_vectors(
        self,
        signals: list[_PriceVectorSignal],
        horizon_start: datetime,
        horizon_slots: int,
        slot_seconds: int,
        import_vec: list[float],
        export_vec: list[float],
        signal_ids_by_slot: list[list[str]],
        reasons_by_slot: list[list[str]],
    ) -> None:
        for index in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * index)
            for signal in signals:
                if not (signal.valid_from <= slot_start < signal.valid_until):
                    continue
                prices = signal.prices_by_start.get(slot_start)
                if prices is None:
                    continue
                import_vec[index], export_vec[index] = prices
                signal_ids_by_slot[index].append(signal.signal_id)
                reasons_by_slot[index].append(signal.reason)
                break

    def _apply_legacy_prices(self, horizon_start: datetime, horizon_slots: int, slot_seconds: int, import_vec: list[float]) -> None:
        for i in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * i)
            price = self._legacy_price_at(slot_start)
            if price is not None:
                import_vec[i] = price

    def _legacy_price_at(self, moment: datetime) -> float | None:
        points = self._points_by_day.get(moment.date().isoformat())
        if not points:
            return None
        target_hour = f"{moment.hour:02d}"
        for point in points:
            starts_at = point.get("starts_at")
            if starts_at:
                try:
                    start = _parse_dt(starts_at)
                except ValueError:
                    start = None
                if start is not None and start <= moment < start + timedelta(hours=1):
                    return float(point["price_eur_kwh"])
            if point.get("hour") == target_hour:
                return float(point["price_eur_kwh"])
        return None


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_expired(valid_until: datetime, now: datetime | None) -> bool:
    return now is not None and valid_until <= now


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
