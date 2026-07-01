"""Rolling LP planner for strategy v3 (Component A)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pulp
from sqlalchemy import text

from minyad.strategy.v2.consumption_profile import ConsumptionProfile
from minyad.strategy.v2.planner import is_lifepo4_full_cycle_day

from .constants import Settings
from .models import Slot, SlotPlan
from .price_client import PriceStore
from . import forecast_client

LOGGER = logging.getLogger(__name__)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
PV_CALIBRATION_LOOKBACK_DAYS = 14
PV_CALIBRATION_MIN_DAYS = 3
FRIDAY_SUNSET_HARD_TARGET_PCT = 99.0


class PlannerSolveError(RuntimeError):
    """Raised when the LP does not reach an Optimal solution."""


def _slot_floor(moment: datetime, slot_seconds: int) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    epoch = int(moment.timestamp())
    floored_epoch = epoch - (epoch % slot_seconds)
    return datetime.fromtimestamp(floored_epoch, tz=timezone.utc).astimezone(moment.tzinfo)


def solve_slot_plan(
    *,
    horizon_start: datetime,
    slot_seconds: int,
    horizon_slots: int,
    soc_now_pct: float,
    pv_forecast_w: list[float],
    load_forecast_w: list[float],
    price_import: list[float],
    price_export: list[float],
    capacity_wh: float,
    max_charge_w: float,
    max_discharge_w: float,
    one_way_efficiency: float,
    cycle_cost_eur_kwh: float,
    export_cap_w: float,
    grid_charge_enabled: bool,
    grid_charge_relax_w: float,
    terminal_soc_pct: float,
    soc_floor_pct: float,
    soc_ceiling_pct: float,
    friday_sunset_at: datetime | None,
    pv_calibration_factor: float,
    generated_at: datetime,
    tz: ZoneInfo = AMSTERDAM,
) -> SlotPlan:
    """Solve the spec-3.5 linear program and return a :class:`SlotPlan`.

    Pure function of its inputs (no I/O) so it can be unit tested directly.
    Raises :class:`PlannerSolveError` if the solver does not reach Optimal.
    """
    n = horizon_slots
    dt_h = slot_seconds / 3600.0
    capacity = capacity_wh

    slot_starts = [horizon_start + timedelta(seconds=slot_seconds * t) for t in range(n)]
    friday_slots = {t for t, start in enumerate(slot_starts) if is_lifepo4_full_cycle_day(start.astimezone(tz).date())}
    friday_full_cycle = bool(friday_slots)

    sunset_index: int | None = None
    if friday_sunset_at is not None:
        for t in range(n + 1):
            boundary = horizon_start + timedelta(seconds=slot_seconds * t)
            if boundary <= friday_sunset_at:
                sunset_index = t
            else:
                break

    prob = pulp.LpProblem("minyad_v3_plan", pulp.LpMinimize)

    ch = [pulp.LpVariable(f"ch_{t}", lowBound=0, upBound=max_charge_w) for t in range(n)]
    dis = [pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=max_discharge_w) for t in range(n)]
    gimp = [pulp.LpVariable(f"gimp_{t}", lowBound=0) for t in range(n)]
    gexp = [pulp.LpVariable(f"gexp_{t}", lowBound=0, upBound=max(0.0, export_cap_w)) for t in range(n)]
    # Free curtailment term: pv_forecast_w is a forecast ceiling, not a commitment. Without this,
    # constraint 1 is infeasible any time forecast PV exceeds load + max_charge_w + export_cap_w
    # (common on a sunny day with a hardware-limited charger and export disabled) — real inverters
    # clip excess PV the same way. Curtailing costs nothing in the objective.
    curtail = [pulp.LpVariable(f"curtail_{t}", lowBound=0) for t in range(n)]
    soc = [pulp.LpVariable(f"soc_{t}", lowBound=0, upBound=capacity) for t in range(n + 1)]
    slack_lo = [pulp.LpVariable(f"slack_lo_{t}", lowBound=0) for t in range(n + 1)]
    slack_hi = [pulp.LpVariable(f"slack_hi_{t}", lowBound=0) for t in range(n + 1)]

    soc0 = soc_now_pct / 100.0 * capacity
    prob += soc[0] == soc0, "initial_soc"

    floor_wh = soc_floor_pct / 100.0 * capacity
    ceil_wh = soc_ceiling_pct / 100.0 * capacity
    hard_floor_wh = 0.05 * capacity

    for t in range(n):
        # 1. power balance (with free curtailment of unusable forecast PV, see above)
        prob += curtail[t] <= pv_forecast_w[t], f"curtail_cap_{t}"
        prob += (pv_forecast_w[t] - curtail[t]) + dis[t] + gimp[t] == load_forecast_w[t] + ch[t] + gexp[t], f"balance_{t}"
        # 2. SoC dynamics
        prob += soc[t + 1] == soc[t] + (ch[t] * one_way_efficiency - dis[t] * (1.0 / one_way_efficiency)) * dt_h, f"dynamics_{t}"
        # 4. grid-charge gating (forced solar-only on Friday slots regardless of the setting)
        if not grid_charge_enabled or t in friday_slots:
            surplus_cap = max(0.0, pv_forecast_w[t] - load_forecast_w[t]) + grid_charge_relax_w
            prob += ch[t] <= surplus_cap, f"solar_only_{t}"

    for t in range(n + 1):
        # 3. soft SoC band + hard bounds (hard bound skipped at t=0: soc[0] is pinned to the live reading,
        # which may transiently sit below the hard floor; the LP must stay feasible regardless).
        # The ceiling is Friday-aware (spec 4.2's soc_ceiling_effective): without this, constraint 3
        # would fight the Friday-sunset target the entire day, since exceeding the ordinary ceiling
        # anywhere en route to 99% is soft-penalized — the LP would rather fake-satisfy constraint 5
        # with a single large slack than actually charge using free solar.
        boundary = horizon_start + timedelta(seconds=slot_seconds * t)
        ceil_wh_t = capacity if is_lifepo4_full_cycle_day(boundary.astimezone(tz).date()) else ceil_wh
        prob += soc[t] >= floor_wh - slack_lo[t], f"soft_floor_{t}"
        prob += soc[t] <= ceil_wh_t + slack_hi[t], f"soft_ceiling_{t}"
        if t > 0:
            prob += soc[t] >= hard_floor_wh, f"hard_floor_{t}"

    # 5. Friday full-cycle target at sunset
    if sunset_index is not None:
        target_wh = FRIDAY_SUNSET_HARD_TARGET_PCT / 100.0 * capacity
        prob += soc[sunset_index] >= target_wh - slack_hi[sunset_index], "friday_sunset_target"

    # 6. terminal condition
    terminal_wh = terminal_soc_pct / 100.0 * capacity
    prob += soc[n] >= terminal_wh - slack_lo[n], "terminal_soc"

    objective = pulp.lpSum(
        price_import[t] * gimp[t] * dt_h / 1000.0
        - price_export[t] * gexp[t] * dt_h / 1000.0
        + cycle_cost_eur_kwh * (ch[t] + dis[t]) * dt_h / 1000.0
        for t in range(n)
    ) + pulp.lpSum(10.0 * (slack_lo[t] + slack_hi[t]) / 1000.0 for t in range(n + 1))
    prob += objective

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        raise PlannerSolveError(status)

    slots: list[Slot] = []
    for t in range(n):
        ch_val = ch[t].value() or 0.0
        dis_val = dis[t].value() or 0.0
        pv_minus_load_surplus = max(0.0, pv_forecast_w[t] - load_forecast_w[t])
        planned_grid_charge_w = max(0.0, ch_val - pv_minus_load_surplus)
        slots.append(
            Slot(
                start=slot_starts[t],
                soc_target_pct=(soc[t + 1].value() or 0.0) / capacity * 100.0,
                planned_grid_charge_w=int(round(planned_grid_charge_w)),
                planned_export_w=int(round(gexp[t].value() or 0.0)),
                pv_forecast_w=int(round(pv_forecast_w[t])),
                load_forecast_w=int(round(load_forecast_w[t])),
                charge_w=int(round(ch_val)),
                discharge_w=int(round(dis_val)),
                price_import=price_import[t],
                price_export=price_export[t],
            )
        )

    return SlotPlan(
        generated_at=generated_at,
        valid_from=horizon_start,
        slot_seconds=slot_seconds,
        soc_start_pct=soc_now_pct,
        slots=slots,
        friday_full_cycle=friday_full_cycle,
        solver_status=status,
        pv_calibration_factor=pv_calibration_factor,
    )


def build_fallback_plan(now: datetime, soc_now_pct: float, settings: Settings, *, tz: ZoneInfo = AMSTERDAM) -> SlotPlan:
    """Flat-hold plan used when the LP can't be solved (spec 3.6)."""
    slot_seconds = settings.plan_interval_min * 60
    horizon_start = _slot_floor(now, slot_seconds)
    slots = [
        Slot(
            start=horizon_start + timedelta(seconds=slot_seconds * t),
            soc_target_pct=soc_now_pct,
            planned_grid_charge_w=0,
            planned_export_w=0,
            pv_forecast_w=0,
            load_forecast_w=0,
            price_import=settings.fixed_price_import,
            price_export=settings.fixed_price_export,
        )
        for t in range(settings.horizon_slots)
    ]
    friday_full_cycle = is_lifepo4_full_cycle_day(now.astimezone(tz).date())
    return SlotPlan(
        generated_at=now,
        valid_from=horizon_start,
        slot_seconds=slot_seconds,
        soc_start_pct=soc_now_pct,
        slots=slots,
        friday_full_cycle=friday_full_cycle,
        solver_status="FALLBACK",
        pv_calibration_factor=settings.pv_calibration_factor,
    )


class RollingPlanner:
    """Wires the pure LP solver to live inputs: Open-Meteo, prices, consumption history, DB."""

    def __init__(
        self,
        settings: Settings,
        db_session_factory: Any | None = None,
        *,
        tz: ZoneInfo = AMSTERDAM,
        ghi_fetcher: Any | None = None,
        sunset_fetcher: Any | None = None,
    ) -> None:
        self.settings = settings
        self.db_session_factory = db_session_factory
        self.tz = tz
        self._ghi_fetcher = ghi_fetcher or forecast_client.fetch_ghi_hourly
        self._sunset_fetcher = sunset_fetcher or forecast_client.fetch_sunset
        self.price_store = PriceStore()
        self.consumption_profile: ConsumptionProfile | None = None
        self.plan: SlotPlan | None = None
        self._last_fallback_logged = False

    def set_consumption_profile(self, profile: ConsumptionProfile) -> None:
        self.consumption_profile = profile

    def on_prices(self, day: str, points: list[dict[str, Any]]) -> None:
        self.price_store.set_from_entsoe(day, points)

    def current_plan(self, now: datetime, soc_now_pct: float = 50.0) -> SlotPlan:
        if self.plan is None:
            return build_fallback_plan(now, soc_now_pct, self.settings, tz=self.tz)
        return self.plan

    async def recalculate(self, now: datetime, soc_now_pct: float | None) -> SlotPlan:
        if soc_now_pct is None:
            # Stale/unknown SoC: keep the previous plan rather than solving against a guess.
            if self.plan is not None:
                return self.plan
            soc_now_pct = 50.0
        try:
            plan = await self._build_plan(now, soc_now_pct)
            self._last_fallback_logged = False
        except Exception:
            if not self._last_fallback_logged:
                LOGGER.warning("Rolling planner failed to solve; using FALLBACK plan", exc_info=True)
                self._last_fallback_logged = True
            plan = build_fallback_plan(now, soc_now_pct, self.settings, tz=self.tz)
        self.plan = plan
        await self._persist(plan)
        return plan

    async def _build_plan(self, now: datetime, soc_now_pct: float) -> SlotPlan:
        settings = self.settings
        horizon_slots = settings.horizon_slots
        slot_seconds = settings.plan_interval_min * 60
        horizon_start = _slot_floor(now, slot_seconds)

        ghi_points = await self._maybe_await(self._ghi_fetcher(past_days=1, forecast_days=2))
        pv_forecast = [
            forecast_client.interpolate_ghi(ghi_points, horizon_start + timedelta(seconds=slot_seconds * t))
            * settings.pv_calibration_factor
            for t in range(horizon_slots)
        ]

        if self.consumption_profile is not None:
            load_forecast = [
                self.consumption_profile.expected_w(horizon_start + timedelta(seconds=slot_seconds * t))
                for t in range(horizon_slots)
            ]
        else:
            load_forecast = [settings.consumption_fallback_w] * horizon_slots

        price_import, price_export = self.price_store.price_vectors_for(
            horizon_start,
            horizon_slots,
            slot_seconds,
            fixed_import=settings.fixed_price_import,
            fixed_export=settings.fixed_price_export,
        )

        friday_sunset_at = await self._friday_sunset_in_horizon(horizon_start, slot_seconds, horizon_slots)

        return solve_slot_plan(
            horizon_start=horizon_start,
            slot_seconds=slot_seconds,
            horizon_slots=horizon_slots,
            soc_now_pct=soc_now_pct,
            pv_forecast_w=pv_forecast,
            load_forecast_w=load_forecast,
            price_import=price_import,
            price_export=price_export,
            capacity_wh=settings.capacity_wh,
            max_charge_w=settings.effective_max_charge_w,
            max_discharge_w=settings.max_discharge_w,
            one_way_efficiency=settings.one_way_efficiency,
            cycle_cost_eur_kwh=settings.cycle_cost_eur_kwh,
            export_cap_w=settings.export_cap_w,
            grid_charge_enabled=settings.grid_charge_enabled,
            grid_charge_relax_w=settings.grid_charge_relax_w,
            terminal_soc_pct=settings.terminal_soc_pct,
            soc_floor_pct=settings.soc_floor,
            soc_ceiling_pct=settings.soc_ceiling,
            friday_sunset_at=friday_sunset_at,
            pv_calibration_factor=settings.pv_calibration_factor,
            generated_at=now,
            tz=self.tz,
        )

    async def _friday_sunset_in_horizon(self, horizon_start: datetime, slot_seconds: int, horizon_slots: int) -> datetime | None:
        seen_dates: set[date] = set()
        for t in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * t)
            local_date = slot_start.astimezone(self.tz).date()
            if local_date in seen_dates or not is_lifepo4_full_cycle_day(local_date):
                continue
            seen_dates.add(local_date)
            try:
                return await self._maybe_await(self._sunset_fetcher(local_date))
            except Exception:  # noqa: BLE001 - fall back to the fixed local sunset estimate
                return forecast_client.fallback_sunset(local_date)
        return None

    async def daily_calibration(self, now: datetime) -> None:
        """Recompute strategy3.pv_calibration_factor from the last 14 days (spec 3.3)."""
        if self.db_session_factory is None:
            return
        start = now - timedelta(days=PV_CALIBRATION_LOOKBACK_DAYS)
        async with self.db_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    select bucket_start, power_w
                    from power_curve_rollups
                    where source = 'solar'
                      and granularity_seconds = 900
                      and bucket_start >= :start
                    """
                ),
                {"start": start},
            )
            rows = [(row.bucket_start, row.power_w) for row in result]
        if len(rows) < PV_CALIBRATION_MIN_DAYS * 96:
            return
        try:
            ghi_points = await self._maybe_await(self._ghi_fetcher(past_days=PV_CALIBRATION_LOOKBACK_DAYS, forecast_days=0))
        except Exception:
            LOGGER.exception("PV calibration: could not fetch historical irradiance; keeping previous factor")
            return

        actual_wh = 0.0
        ghi_wh = 0.0
        for bucket_start, power_w in rows:
            if power_w is None or bucket_start is None:
                continue
            if bucket_start.tzinfo is None:
                bucket_start = bucket_start.replace(tzinfo=timezone.utc)
            actual_wh += max(0.0, float(power_w)) * 0.25
            ghi_wh += forecast_client.interpolate_ghi(ghi_points, bucket_start) * 0.25

        new_factor = forecast_client.calibrate_pv_factor(actual_wh, ghi_wh, self.settings.pv_calibration_factor)
        await self.settings.set("strategy3.pv_calibration_factor", new_factor)

    async def _persist(self, plan: SlotPlan) -> None:
        if self.db_session_factory is None:
            return
        payload = _plan_to_json(plan)
        async with self.db_session_factory() as session:
            await session.execute(
                text(
                    """
                    insert into slot_plans (generated_at, valid_from, slot_seconds, payload, solver_status)
                    values (:generated_at, :valid_from, :slot_seconds, cast(:payload as jsonb), :solver_status)
                    """
                ),
                {
                    "generated_at": plan.generated_at,
                    "valid_from": plan.valid_from,
                    "slot_seconds": plan.slot_seconds,
                    "payload": json.dumps(payload),
                    "solver_status": plan.solver_status,
                },
            )
            await session.execute(
                text("delete from slot_plans where created_at < now() - interval '30 days'")
            )
            await session.commit()

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value


def _plan_to_json(plan: SlotPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "valid_from": plan.valid_from.isoformat(),
        "slot_seconds": plan.slot_seconds,
        "slots": [
            {
                "start": slot.start.isoformat(),
                "soc_target_pct": slot.soc_target_pct,
                "planned_grid_charge_w": slot.planned_grid_charge_w,
                "planned_export_w": slot.planned_export_w,
                "pv_forecast_w": slot.pv_forecast_w,
                "load_forecast_w": slot.load_forecast_w,
                "charge_w": slot.charge_w,
                "discharge_w": slot.discharge_w,
                "surplus_w": slot.surplus_w,
                "price_import": slot.price_import,
                "price_export": slot.price_export,
            }
            for slot in plan.slots
        ],
        "friday_full_cycle": plan.friday_full_cycle,
        "solver_status": plan.solver_status,
        "pv_calibration_factor": plan.pv_calibration_factor,
    }
