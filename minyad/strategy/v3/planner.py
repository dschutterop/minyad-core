"""Rolling LP planner for strategy v3 (Component A)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pulp
from sqlalchemy import text

from minyad.strategy.v2.planner import is_lifepo4_full_cycle_day

from .constants import Settings
from .consumption_profile import HouseholdLoadProfile
from .models import Slot, SlotPlan
from .price_client import PriceStore
from . import forecast_client
from . import pv_uncertainty

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


class _LpVars:
    """The LP decision variables shared across constraint-builder and extraction helpers."""

    def __init__(self, n: int, max_charge_w: float, max_discharge_w: float, export_cap_w: float, capacity: float) -> None:
        self.ch = [pulp.LpVariable(f"ch_{t}", lowBound=0, upBound=max_charge_w) for t in range(n)]
        self.dis = [pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=max_discharge_w) for t in range(n)]
        self.gimp = [pulp.LpVariable(f"gimp_{t}", lowBound=0) for t in range(n)]
        self.gexp = [pulp.LpVariable(f"gexp_{t}", lowBound=0, upBound=max(0.0, export_cap_w)) for t in range(n)]
        # Free curtailment term: pv_forecast_w is a forecast ceiling, not a commitment. Without this,
        # constraint 1 is infeasible any time forecast PV exceeds load + max_charge_w + export_cap_w
        # (common on a sunny day with a hardware-limited charger and export disabled) — real inverters
        # clip excess PV the same way. Curtailing costs nothing in the objective.
        self.curtail = [pulp.LpVariable(f"curtail_{t}", lowBound=0) for t in range(n)]
        self.soc = [pulp.LpVariable(f"soc_{t}", lowBound=0, upBound=capacity) for t in range(n + 1)]
        self.slack_lo = [pulp.LpVariable(f"slack_lo_{t}", lowBound=0) for t in range(n + 1)]
        self.slack_hi = [pulp.LpVariable(f"slack_hi_{t}", lowBound=0) for t in range(n + 1)]


def _friday_slots_and_sunset(
    horizon_start: datetime, slot_seconds: int, n: int, tz: ZoneInfo, friday_sunset_at: datetime | None
) -> tuple[list[datetime], set[int], int | None]:
    slot_starts = [horizon_start + timedelta(seconds=slot_seconds * t) for t in range(n)]
    friday_slots = {t for t, start in enumerate(slot_starts) if is_lifepo4_full_cycle_day(start.astimezone(tz).date())}

    sunset_index: int | None = None
    if friday_sunset_at is not None:
        for t in range(n + 1):
            boundary = horizon_start + timedelta(seconds=slot_seconds * t)
            if boundary <= friday_sunset_at:
                sunset_index = t
            else:
                break
    return slot_starts, friday_slots, sunset_index


def _add_balance_and_dynamics_constraints(
    prob: pulp.LpProblem,
    lp: _LpVars,
    n: int,
    pv_forecast_w: list[float],
    load_forecast_w: list[float],
    dt_h: float,
    one_way_efficiency: float,
    grid_charge_enabled: bool,
    friday_slots: set[int],
    grid_charge_relax_w: float,
) -> None:
    for t in range(n):
        # 1. power balance (with free curtailment of unusable forecast PV, see _LpVars.curtail)
        prob.addConstraint(lp.curtail[t] <= pv_forecast_w[t], f"curtail_cap_{t}")
        prob.addConstraint(
            (pv_forecast_w[t] - lp.curtail[t]) + lp.dis[t] + lp.gimp[t] == load_forecast_w[t] + lp.ch[t] + lp.gexp[t],
            f"balance_{t}",
        )
        # 2. SoC dynamics
        prob.addConstraint(
            lp.soc[t + 1] == lp.soc[t] + (lp.ch[t] * one_way_efficiency - lp.dis[t] * (1.0 / one_way_efficiency)) * dt_h,
            f"dynamics_{t}",
        )
        # 4. grid-charge gating (forced solar-only on Friday slots regardless of the setting)
        if not grid_charge_enabled or t in friday_slots:
            surplus_cap = max(0.0, pv_forecast_w[t] - load_forecast_w[t]) + grid_charge_relax_w
            prob.addConstraint(lp.ch[t] <= surplus_cap, f"solar_only_{t}")


def _add_soc_band_constraints(
    prob: pulp.LpProblem,
    lp: _LpVars,
    n: int,
    horizon_start: datetime,
    slot_seconds: int,
    tz: ZoneInfo,
    floor_wh: float,
    ceil_wh: float,
    hard_floor_wh: float,
    capacity: float,
) -> None:
    for t in range(n + 1):
        # 3. soft SoC band + hard bounds (hard bound skipped at t=0: soc[0] is pinned to the live reading,
        # which may transiently sit below the hard floor; the LP must stay feasible regardless).
        # The ceiling is Friday-aware (spec 4.2's soc_ceiling_effective): without this, constraint 3
        # would fight the Friday-sunset target the entire day, since exceeding the ordinary ceiling
        # anywhere en route to 99% is soft-penalized — the LP would rather fake-satisfy constraint 5
        # with a single large slack than actually charge using free solar.
        boundary = horizon_start + timedelta(seconds=slot_seconds * t)
        ceil_wh_t = capacity if is_lifepo4_full_cycle_day(boundary.astimezone(tz).date()) else ceil_wh
        prob.addConstraint(lp.soc[t] >= floor_wh - lp.slack_lo[t], f"soft_floor_{t}")
        prob.addConstraint(lp.soc[t] <= ceil_wh_t + lp.slack_hi[t], f"soft_ceiling_{t}")
        if t > 0:
            prob.addConstraint(lp.soc[t] >= hard_floor_wh, f"hard_floor_{t}")


def _add_target_constraints(
    prob: pulp.LpProblem, lp: _LpVars, n: int, sunset_index: int | None, capacity: float, terminal_soc_pct: float
) -> None:
    # 5. Friday full-cycle target at sunset
    if sunset_index is not None:
        target_wh = FRIDAY_SUNSET_HARD_TARGET_PCT / 100.0 * capacity
        prob.addConstraint(lp.soc[sunset_index] >= target_wh - lp.slack_hi[sunset_index], "friday_sunset_target")

    # 6. terminal condition
    terminal_wh = terminal_soc_pct / 100.0 * capacity
    prob.addConstraint(lp.soc[n] >= terminal_wh - lp.slack_lo[n], "terminal_soc")


def _build_objective(
    lp: _LpVars, n: int, price_import: list[float], price_export: list[float], cycle_cost_eur_kwh: float, dt_h: float
) -> pulp.LpAffineExpression:
    return pulp.lpSum(
        price_import[t] * lp.gimp[t] * dt_h / 1000.0
        - price_export[t] * lp.gexp[t] * dt_h / 1000.0
        + cycle_cost_eur_kwh * (lp.ch[t] + lp.dis[t]) * dt_h / 1000.0
        for t in range(n)
    ) + pulp.lpSum(10.0 * (lp.slack_lo[t] + lp.slack_hi[t]) / 1000.0 for t in range(n + 1))


def _extract_slots(
    lp: _LpVars,
    n: int,
    slot_starts: list[datetime],
    pv_forecast_w: list[float],
    load_forecast_w: list[float],
    capacity: float,
    price_source_vec: list[str],
    cloud_cover_vec: list[float | None],
    price_import: list[float],
    price_export: list[float],
) -> list[Slot]:
    slots: list[Slot] = []
    for t in range(n):
        ch_val = lp.ch[t].value() or 0.0
        dis_val = lp.dis[t].value() or 0.0
        pv_minus_load_surplus = max(0.0, pv_forecast_w[t] - load_forecast_w[t])
        planned_grid_charge_w = max(0.0, ch_val - pv_minus_load_surplus)
        slots.append(
            Slot(
                start=slot_starts[t],
                soc_target_pct=(lp.soc[t + 1].value() or 0.0) / capacity * 100.0,
                planned_grid_charge_w=int(round(planned_grid_charge_w)),
                planned_export_w=int(round(lp.gexp[t].value() or 0.0)),
                pv_forecast_w=int(round(pv_forecast_w[t])),
                load_forecast_w=int(round(load_forecast_w[t])),
                charge_w=int(round(ch_val)),
                discharge_w=int(round(dis_val)),
                curtailment_w=int(round(lp.curtail[t].value() or 0.0)),
                price_source=price_source_vec[t],
                cloud_cover_pct=cloud_cover_vec[t],
                price_import=price_import[t],
                price_export=price_export[t],
            )
        )
    return slots


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
    price_source: list[str] | None = None,
    cloud_cover_pct: list[float | None] | None = None,
) -> SlotPlan:
    """Solve the spec-3.5 linear program and return a :class:`SlotPlan`.

    Pure function of its inputs (no I/O) so it can be unit tested directly.
    Raises :class:`PlannerSolveError` if the solver does not reach Optimal.
    """
    n = horizon_slots
    dt_h = slot_seconds / 3600.0
    capacity = capacity_wh

    slot_starts, friday_slots, sunset_index = _friday_slots_and_sunset(horizon_start, slot_seconds, n, tz, friday_sunset_at)
    friday_full_cycle = bool(friday_slots)

    prob = pulp.LpProblem("minyad_v3_plan", pulp.LpMinimize)
    lp = _LpVars(n, max_charge_w, max_discharge_w, export_cap_w, capacity)

    soc0 = soc_now_pct / 100.0 * capacity
    prob += lp.soc[0] == soc0, "initial_soc"

    floor_wh = soc_floor_pct / 100.0 * capacity
    ceil_wh = soc_ceiling_pct / 100.0 * capacity
    hard_floor_wh = 0.05 * capacity

    _add_balance_and_dynamics_constraints(prob, lp, n, pv_forecast_w, load_forecast_w, dt_h, one_way_efficiency, grid_charge_enabled, friday_slots, grid_charge_relax_w)
    _add_soc_band_constraints(prob, lp, n, horizon_start, slot_seconds, tz, floor_wh, ceil_wh, hard_floor_wh, capacity)
    _add_target_constraints(prob, lp, n, sunset_index, capacity, terminal_soc_pct)

    prob += _build_objective(lp, n, price_import, price_export, cycle_cost_eur_kwh, dt_h)

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        raise PlannerSolveError(status)

    price_source_vec = price_source if price_source is not None else ["fallback"] * n
    cloud_cover_vec = cloud_cover_pct if cloud_cover_pct is not None else [None] * n

    slots = _extract_slots(lp, n, slot_starts, pv_forecast_w, load_forecast_w, capacity, price_source_vec, cloud_cover_vec, price_import, price_export)

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
        temperature_fetcher: Any | None = None,
        cloud_cover_fetcher: Any | None = None,
    ) -> None:
        self.settings = settings
        self.db_session_factory = db_session_factory
        self.tz = tz
        self._ghi_fetcher = ghi_fetcher or forecast_client.fetch_ghi_hourly
        self._sunset_fetcher = sunset_fetcher or forecast_client.fetch_sunset
        self._temperature_fetcher = temperature_fetcher or forecast_client.fetch_temperature_hourly
        self._cloud_cover_fetcher = cloud_cover_fetcher or forecast_client.fetch_cloud_cover_hourly
        self.price_store = PriceStore()
        self.consumption_profile: HouseholdLoadProfile | None = None
        self.plan: SlotPlan | None = None
        self._last_fallback_logged = False
        # Bootstrap: flat 24-hour vector from the scalar default until the first
        # daily_calibration() run (or load_pv_calibration_factors() at startup) replaces it
        # with real per-hour data (dashboard_forecast_v1 spec 4.3).
        self.pv_calibration_factors: list[float] = [settings.pv_calibration_factor] * forecast_client.PV_CALIBRATION_HOURS

    def set_consumption_profile(self, profile: HouseholdLoadProfile) -> None:
        self.consumption_profile = profile

    async def load_pv_calibration_factors(self) -> None:
        """Load the most recently computed per-hour factor vector at startup (spec 4.3.4)."""
        if self.db_session_factory is None:
            return
        async with self.db_session_factory() as session:
            latest_date = (
                await session.execute(text("select max(calibration_date) from pv_calibration_history"))
            ).scalar_one_or_none()
            if latest_date is None:
                return
            rows = (
                await session.execute(
                    text("select hour_of_day, factor from pv_calibration_history where calibration_date = :d"),
                    {"d": latest_date},
                )
            ).all()
        factors = list(self.pv_calibration_factors)
        for hour, factor in rows:
            factors[hour] = float(factor)
        self.pv_calibration_factors = factors

    def on_prices(self, day: str, points: list[dict[str, Any]]) -> None:
        self.price_store.set_from_entsoe(day, points)

    def on_market_signal(self, payload: dict[str, Any] | list[dict[str, Any]], *, now: datetime | None = None) -> None:
        self.price_store.set_market_signal(payload, now=now)

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

        # A missed GHI fetch used to fail the whole plan build, forcing a flat-zero FALLBACK
        # plan (which now hides the forecast curves entirely rather than rendering a fake flat
        # line) — degrade to an all-zero PV forecast instead, matching the cloud-cover/temperature
        # fetches below, so a transient Open-Meteo outage doesn't blank the dashboard.
        ghi_points = await self._safe_fetch(
            self._ghi_fetcher(lat=settings.latitude, lon=settings.longitude, past_days=1, forecast_days=2),
            "Unable to fetch GHI forecast; PV forecast will be zero",
        )
        # The P10-P90 band (spec 4.4) is purely informational for the dashboard — a missed
        # cloud-cover fetch should leave cloud_cover_pct unset per slot, not fail the plan.
        cloud_cover_points = await self._safe_fetch(
            self._cloud_cover_fetcher(lat=settings.latitude, lon=settings.longitude, past_days=1, forecast_days=2),
            "Unable to fetch cloud cover forecast; PV uncertainty band will be unavailable",
        )
        pv_forecast = []
        cloud_cover_pct: list[float | None] = []
        for t in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * t)
            hour_local = slot_start.astimezone(self.tz).hour
            ghi_w_m2 = forecast_client.interpolate_ghi(ghi_points, slot_start)
            # Per-hour calibration factor (spec 4.3.1) with an inverter AC clipping guard
            # (spec 4.3.2) — a real inverter can't output more than its rated AC max regardless
            # of how much DC power the panels could otherwise deliver.
            pv_forecast.append(min(ghi_w_m2 * self.pv_calibration_factors[hour_local], settings.inverter_ac_max_w))
            cloud_cover_pct.append(forecast_client.interpolate_ghi(cloud_cover_points, slot_start) if cloud_cover_points else None)

        if self.consumption_profile is not None:
            # Temperature correction (spec 4.2.2) is an enhancement, not a dependency —
            # fall back to the profile's plain per-slot expectation rather than failing the
            # whole plan build over a missed forecast fetch.
            temp_points = await self._safe_fetch(
                self._temperature_fetcher(past_days=1, forecast_days=2),
                "Unable to fetch temperature forecast; skipping temperature correction",
            )
            load_forecast = []
            for t in range(horizon_slots):
                slot_start = horizon_start + timedelta(seconds=slot_seconds * t)
                temperature_c = forecast_client.interpolate_ghi(temp_points, slot_start) if temp_points else None
                load_forecast.append(self.consumption_profile.expected_w(slot_start, temperature_c=temperature_c))
        else:
            load_forecast = [settings.consumption_fallback_w] * horizon_slots

        market_inputs = self.price_store.planner_inputs_for(
            horizon_start,
            horizon_slots,
            slot_seconds,
            fixed_import=settings.fixed_price_import,
            fixed_export=settings.fixed_price_export,
            now=now,
        )

        friday_sunset_at = await self._friday_sunset_in_horizon(horizon_start, slot_seconds, horizon_slots)

        plan = solve_slot_plan(
            horizon_start=horizon_start,
            slot_seconds=slot_seconds,
            horizon_slots=horizon_slots,
            soc_now_pct=soc_now_pct,
            pv_forecast_w=pv_forecast,
            load_forecast_w=load_forecast,
            price_import=market_inputs.price_import,
            price_export=market_inputs.price_export,
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
            # SlotPlan.pv_calibration_factor is now purely a telemetry summary (mean of the
            # per-hour vector actually used above); nothing downstream reads it for forecasting.
            pv_calibration_factor=sum(self.pv_calibration_factors) / len(self.pv_calibration_factors),
            generated_at=now,
            tz=self.tz,
            price_source=market_inputs.price_source_by_slot,
            cloud_cover_pct=cloud_cover_pct,
        )
        if market_inputs.market_signal_ids or market_inputs.constraint_reasons:
            plan = replace(
                plan,
                market_signal_ids=market_inputs.market_signal_ids,
                constraint_reasons=market_inputs.constraint_reasons,
            )
        return plan

    async def _friday_sunset_in_horizon(self, horizon_start: datetime, slot_seconds: int, horizon_slots: int) -> datetime | None:
        seen_dates: set[date] = set()
        for t in range(horizon_slots):
            slot_start = horizon_start + timedelta(seconds=slot_seconds * t)
            local_date = slot_start.astimezone(self.tz).date()
            if local_date in seen_dates or not is_lifepo4_full_cycle_day(local_date):
                continue
            seen_dates.add(local_date)
            try:
                return await self._maybe_await(
                    self._sunset_fetcher(local_date, lat=self.settings.latitude, lon=self.settings.longitude)
                )
            except Exception:  # noqa: BLE001 - fall back to the fixed local sunset estimate
                return forecast_client.fallback_sunset(local_date)
        return None

    async def daily_calibration(self, now: datetime) -> None:
        """Recompute per-hour PV calibration factors from the last 14 days (spec 4.3)."""
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
            ghi_points = await self._maybe_await(
                self._ghi_fetcher(
                    lat=self.settings.latitude,
                    lon=self.settings.longitude,
                    past_days=PV_CALIBRATION_LOOKBACK_DAYS,
                    forecast_days=0,
                )
            )
        except Exception:
            LOGGER.exception("PV calibration: could not fetch historical irradiance; keeping previous factors")
            return

        samples: list[tuple[int, float, float]] = []
        for bucket_start, power_w in rows:
            if power_w is None or bucket_start is None:
                continue
            if bucket_start.tzinfo is None:
                bucket_start = bucket_start.replace(tzinfo=timezone.utc)
            ghi_w_m2 = forecast_client.interpolate_ghi(ghi_points, bucket_start)
            hour_local = bucket_start.astimezone(self.tz).hour
            samples.append((hour_local, max(0.0, float(power_w)), ghi_w_m2))

        new_factors = forecast_client.calibrate_pv_factors(samples, self.pv_calibration_factors)
        self.pv_calibration_factors = new_factors
        await self._persist_pv_calibration(now, new_factors)
        # Keep the scalar settings value in step as a coarse telemetry/debug summary; nothing
        # in the forecasting path reads it anymore (see _build_plan and solve_slot_plan above).
        await self.settings.set("strategy3.pv_calibration_factor", sum(new_factors) / len(new_factors))

        try:
            cloud_cover_points = await self._maybe_await(
                self._cloud_cover_fetcher(
                    lat=self.settings.latitude,
                    lon=self.settings.longitude,
                    past_days=PV_CALIBRATION_LOOKBACK_DAYS,
                    forecast_days=0,
                )
            )
        except Exception:
            LOGGER.warning("PV uncertainty band: could not fetch historical cloud cover; skipping band update", exc_info=True)
            cloud_cover_points = []
        if cloud_cover_points:
            actual_rows = [
                (bucket_start if bucket_start.tzinfo else bucket_start.replace(tzinfo=timezone.utc), max(0.0, float(power_w)))
                for bucket_start, power_w in rows
                if power_w is not None and bucket_start is not None
            ]
            ratios_by_class = pv_uncertainty.collect_pv_ratio_samples(
                actual_rows, ghi_points, cloud_cover_points, new_factors, self.tz
            )
            bands = pv_uncertainty.compute_uncertainty_bands(ratios_by_class)
            await self._persist_pv_uncertainty_bands(now, bands)

    async def _persist_pv_calibration(self, now: datetime, factors: list[float]) -> None:
        if self.db_session_factory is None:
            return
        calibration_date = now.astimezone(self.tz).date()
        async with self.db_session_factory() as session:
            for hour, factor in enumerate(factors):
                await session.execute(
                    text(
                        """
                        insert into pv_calibration_history (calibration_date, hour_of_day, factor)
                        values (:calibration_date, :hour, :factor)
                        on conflict (calibration_date, hour_of_day) do update set factor = excluded.factor
                        """
                    ),
                    {"calibration_date": calibration_date, "hour": hour, "factor": factor},
                )
            # Housekeeping retention; far longer than the 14-28 day lookback this feeds, kept
            # mainly for the debugging use case in spec 4.3.4 ("why does it expect less at 17:00").
            await session.execute(
                text("delete from pv_calibration_history where calibration_date < :cutoff"),
                {"cutoff": calibration_date - timedelta(days=180)},
            )
            await session.commit()

    async def _persist_pv_uncertainty_bands(self, now: datetime, bands: dict[str, dict[str, Any]]) -> None:
        if self.db_session_factory is None or not bands:
            return
        calibration_date = now.astimezone(self.tz).date()
        async with self.db_session_factory() as session:
            for cloud_class, stats in bands.items():
                await session.execute(
                    text(
                        """
                        insert into pv_uncertainty_bands (calibration_date, cloud_class, p10_multiplier, p90_multiplier, sample_count)
                        values (:calibration_date, :cloud_class, :p10, :p90, :sample_count)
                        on conflict (calibration_date, cloud_class) do update set
                          p10_multiplier = excluded.p10_multiplier,
                          p90_multiplier = excluded.p90_multiplier,
                          sample_count = excluded.sample_count
                        """
                    ),
                    {
                        "calibration_date": calibration_date,
                        "cloud_class": cloud_class,
                        "p10": stats["p10_multiplier"],
                        "p90": stats["p90_multiplier"],
                        "sample_count": stats["sample_count"],
                    },
                )
            await session.execute(
                text("delete from pv_uncertainty_bands where calibration_date < :cutoff"),
                {"cutoff": calibration_date - timedelta(days=180)},
            )
            await session.commit()

    async def _persist(self, plan: SlotPlan) -> None:
        if self.db_session_factory is None:
            return
        payload = _plan_to_json(plan)
        async with self.db_session_factory() as session:
            await session.execute(
                text(
                    """
                    insert into slot_plans (generated_at, valid_from, slot_seconds, payload, solver_status, strategy_version)
                    values (:generated_at, :valid_from, :slot_seconds, cast(:payload as jsonb), :solver_status, :strategy_version)
                    """
                ),
                {
                    "generated_at": plan.generated_at,
                    "valid_from": plan.valid_from,
                    "slot_seconds": plan.slot_seconds,
                    "payload": json.dumps(payload),
                    "solver_status": plan.solver_status,
                    "strategy_version": "v3",
                },
            )
            # Retention per dashboard_forecast_v1 spec 5.1 (plan vintages for the history "plan @ tijdstip" view).
            await session.execute(
                text("delete from slot_plans where created_at < now() - interval '90 days'")
            )
            await session.commit()

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value

    async def _safe_fetch(self, fetch: Any, warning: str) -> list:
        """Await a forecast fetch, degrading to an empty list (with a warning) on any error."""
        try:
            return await self._maybe_await(fetch)
        except Exception:
            LOGGER.warning(warning, exc_info=True)
            return []


def _plan_to_json(plan: SlotPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "valid_from": plan.valid_from.isoformat(),
        "slot_seconds": plan.slot_seconds,
        "soc_start_pct": plan.soc_start_pct,
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
                "curtailment_w": slot.curtailment_w,
                "price_source": slot.price_source,
                "cloud_cover_pct": slot.cloud_cover_pct,
                "surplus_w": slot.surplus_w,
                "price_import": slot.price_import,
                "price_export": slot.price_export,
            }
            for slot in plan.slots
        ],
        "friday_full_cycle": plan.friday_full_cycle,
        "solver_status": plan.solver_status,
        "pv_calibration_factor": plan.pv_calibration_factor,
        "plan_schema": plan.plan_schema,
        **({"market_signal_ids": plan.market_signal_ids} if plan.market_signal_ids else {}),
        **({"constraint_reasons": plan.constraint_reasons} if plan.constraint_reasons else {}),
    }
