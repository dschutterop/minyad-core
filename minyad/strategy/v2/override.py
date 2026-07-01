"""Manual override support for strategy v2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from .constants import Settings
from .models import DayPlan, ExecutorState


@dataclass(frozen=True)
class Override:
    mode: str = "none"
    watts: int | None = None
    expires_at: datetime | None = None
    override_soc_limits: bool = False


class OverrideManager:
    def __init__(self, settings: Settings, db_session_factory: Any | None = None, *, now: Any | None = None) -> None:
        self.settings = settings
        self.db_session_factory = db_session_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.current = Override()
        self._cycle_started = False

    async def load(self) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            result = await session.execute(text("""
                select mode, watts, expires_at,
                       coalesce(override_soc_limits, false) as override_soc_limits
                from battery_override
                where id=1
            """))
            row = result.first()
        if row:
            self.current = Override(row.mode, row.watts, row.expires_at, bool(row.override_soc_limits))

    async def apply_payload(self, payload: str | bytes | dict[str, Any]) -> Override:
        data = json.loads(payload.decode() if isinstance(payload, bytes) else payload) if not isinstance(payload, dict) else payload
        mode = _normalize_mode(data.get("mode", "none"))
        duration = data.get("duration_seconds")
        expires_at = _parse_dt(data.get("expires_at")) if data.get("expires_at") else None
        if mode == "pause" and duration:
            expires_at = self._now() + timedelta(seconds=int(duration))
        self.current = Override(
            mode,
            int(data["watts"]) if data.get("watts") is not None else None,
            expires_at,
            _truthy(data.get("override_soc_limits", False)),
        )
        self._cycle_started = False
        await self.persist()
        return self.current

    async def persist(self) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            await session.execute(
                text("""
                    insert into battery_override (id, mode, watts, expires_at, override_soc_limits, updated_at)
                    values (1, :mode, :watts, :expires_at, :override_soc_limits, now())
                    on conflict (id) do update set mode=:mode, watts=:watts, expires_at=:expires_at,
                        override_soc_limits=:override_soc_limits, updated_at=now()
                """),
                {
                    "mode": self.current.mode,
                    "watts": self.current.watts,
                    "expires_at": self.current.expires_at,
                    "override_soc_limits": self.current.override_soc_limits,
                },
            )
            await session.commit()

    async def clear_if_expired(self) -> None:
        if self.current.expires_at and self._now() >= self.current.expires_at:
            self.current = Override()
            self._cycle_started = False
            await self.persist()

    def bypasses_soc_limits(self) -> bool:
        mode = _normalize_mode(self.current.mode)
        return self.current.override_soc_limits and mode in {"force_charge", "grid_charge_now", "force_discharge"}

    async def apply(self, candidate_w: int, state: ExecutorState, plan: DayPlan) -> int:
        adjusted, _reason = await self.apply_with_reason(candidate_w, state, plan)
        return adjusted

    async def apply_with_reason(self, candidate_w: int, state: ExecutorState, plan: DayPlan) -> tuple[int, str | None]:
        await self.clear_if_expired()
        mode = _normalize_mode(self.current.mode)
        if mode in {"none", None}:
            return candidate_w, None
        if self.current.override_soc_limits and self._cycle_complete(mode, state):
            self.current = Override()
            self._cycle_started = False
            await self.persist()
            return candidate_w, "override: expired after one charge/discharge cycle"
        if mode in {"force_idle", "pause"}:
            return 0, f"override: {mode}"
        if mode in {"force_charge", "grid_charge_now"}:
            if not self.current.override_soc_limits and state.battery_soc is not None and state.battery_soc >= plan.effective_soc_ceiling:
                return 0, f"override: {mode} blocked at SoC ceiling ({state.battery_soc}% >= {plan.effective_soc_ceiling}%)"
            adjusted = min(abs(self.current.watts or self.settings.effective_max_charge_w), self.settings.effective_max_charge_w)
            suffix = " (SoC limit override active)" if self.current.override_soc_limits else ""
            return adjusted, f"override: {mode}{suffix}"
        if mode == "force_discharge":
            if not self.current.override_soc_limits and state.battery_soc is not None and state.battery_soc <= plan.effective_soc_floor:
                return 0, f"override: force_discharge blocked at SoC floor ({state.battery_soc}% <= {plan.effective_soc_floor}%)"
            adjusted = -min(abs(self.current.watts or self.settings.max_discharge_w), self.settings.max_discharge_w)
            suffix = " (SoC limit override active)" if self.current.override_soc_limits else ""
            return adjusted, f"override: force_discharge{suffix}"
        return candidate_w, f"override: unknown mode {mode}"

    def _cycle_complete(self, mode: str, state: ExecutorState) -> bool:
        commanded_direction = _mode_direction(mode)
        if commanded_direction == 0:
            return False
        actual_direction = _power_direction(state.battery_power_w, self.settings.jitter_w)
        if actual_direction == commanded_direction:
            self._cycle_started = True
            return False
        return self._cycle_started and actual_direction != commanded_direction


def _normalize_mode(mode: str | None) -> str:
    if mode == "force_on":
        return "force_charge"
    if mode == "force_off":
        return "force_idle"
    return mode or "none"


def _mode_direction(mode: str) -> int:
    if mode in {"force_charge", "grid_charge_now"}:
        return 1
    if mode == "force_discharge":
        return -1
    return 0


def _power_direction(power_w: int, jitter_w: int) -> int:
    if power_w < -jitter_w:
        return 1
    if power_w > jitter_w:
        return -1
    return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
