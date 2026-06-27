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


class OverrideManager:
    def __init__(self, settings: Settings, db_session_factory: Any | None = None, *, now: Any | None = None) -> None:
        self.settings = settings
        self.db_session_factory = db_session_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.current = Override()

    async def load(self) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            result = await session.execute(text("select mode, watts, expires_at from battery_override where id=1"))
            row = result.first()
        if row:
            self.current = Override(row.mode, row.watts, row.expires_at)

    async def apply_payload(self, payload: str | bytes | dict[str, Any]) -> Override:
        data = json.loads(payload.decode() if isinstance(payload, bytes) else payload) if not isinstance(payload, dict) else payload
        mode = data.get("mode", "none")
        duration = data.get("duration_seconds")
        expires_at = _parse_dt(data.get("expires_at")) if data.get("expires_at") else None
        if mode == "pause" and duration:
            expires_at = self._now() + timedelta(seconds=int(duration))
        self.current = Override(mode, int(data["watts"]) if data.get("watts") is not None else None, expires_at)
        await self.persist()
        return self.current

    async def persist(self) -> None:
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            await session.execute(
                text("""
                    insert into battery_override (id, mode, watts, expires_at, updated_at)
                    values (1, :mode, :watts, :expires_at, now())
                    on conflict (id) do update set mode=:mode, watts=:watts, expires_at=:expires_at, updated_at=now()
                """),
                {"mode": self.current.mode, "watts": self.current.watts, "expires_at": self.current.expires_at},
            )
            await session.commit()

    async def clear_if_expired(self) -> None:
        if self.current.expires_at and self._now() >= self.current.expires_at:
            self.current = Override()
            await self.persist()

    async def apply(self, candidate_w: int, state: ExecutorState, plan: DayPlan) -> int:
        await self.clear_if_expired()
        mode = self.current.mode
        if mode in {"none", None}:
            return candidate_w
        if mode in {"force_idle", "pause"}:
            return 0
        if mode in {"force_charge", "grid_charge_now"}:
            if state.battery_soc is not None and state.battery_soc >= plan.effective_soc_ceiling:
                return 0
            return self.settings.effective_max_charge_w
        if mode == "force_discharge":
            if state.battery_soc is not None and state.battery_soc <= plan.effective_soc_floor:
                return 0
            return -min(abs(self.current.watts or self.settings.max_discharge_w), self.settings.max_discharge_w)
        return candidate_w


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
