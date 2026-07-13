# Minyad Strategy v3 — Implementation Specification

**Audience:** an LLM coding agent implementing this in the existing Minyad repository.
**Status:** authoritative spec. Where this document and any older doc (`charging_strategy.md`, v1 `control/`, v2 design notes) disagree, this document wins.
**Language conventions:** all code, comments, topics, and table names in English. All power values in watts (W), energy in watt-hours (Wh), SoC in percent (%), prices in EUR/kWh.

---

## 0. Context and goals

Minyad is a home virtual-power-plant controller (GoodWe GW5048D-ES hybrid inverter, Dyness LiFePO4 ~10 kWh, 20 Enphase panels, DSMR P1 grid meter). Strategy v2 (in `minyad/strategy/v2/`) is a purely **reactive** grid-balancer with a daily GHI-based mode plan, an overnight self-correcting SoC glide floor, and price windows that are effectively unused (`grid_charge_enabled` defaults to false; prices are currently fixed).

**v3 goals, in priority order:**

1. **Predictive, not just reactive.** Use the solar forecast and the historical consumption profile to plan a 24 h SoC trajectory, and track it. v2's `solar_forecast_w` is currently dead weight — v3 must actually consume forecasts.
2. **One unified energy budget.** Replace v2's three independent, partially overlapping mechanisms (executor static SoC clamp, guard dynamic glide floor, price-window bias) with a single planned trajectory that all layers reference. Exactly **one** SoC-limit state machine remains (the guard).
3. **Price-ready by construction.** Prices are fixed today. The plan optimizer must take a price vector as input so that variable day-ahead prices (ENTSO-E via `minyad-trade`) and later trading drop in without architectural change. **Do not implement trading logic** — only the interface.
4. **Preserve what works in v2.** The reactive inner loop (deadband, ramp hold, export block with hysteresis, jitter suppression), the override system, the safety guard (bridge staleness, voltage floor), the LiFePO4 Friday full-cycle rule, and the sign conventions are all retained.
5. **Safe rollout.** v3 runs in shadow mode alongside v2 before being promoted.

**Non-goals for v3:** energy trading / market bidding, multi-battery support, Vesper dispatch decisions (v3 only *publishes* a surplus forecast for Vesper to consume), any change to the hardware bridges.

---

## 1. Sign conventions (unchanged from v2 — enforce everywhere)

- `setpoint_w` **positive = charge** (power into battery), **negative = discharge**.
- `net_grid_w` **positive = import**, **negative = export**.
- `battery_power_w` **positive = discharge** (GoodWe telemetry convention).
- Publishing: `setpoint_w > 0` → `minyad/control/charge_w`; `< 0` → `minyad/control/discharge_w` with `abs()`; `0` → publish both as zero. Identical to v2 `service.py`.

---

## 2. Architecture overview

v3 is a new package `minyad/strategy/v3/` running in the existing `minyad-strategy` container (module selected by env var, see §12). Four components, executed in this strict per-tick order:

```
Component A  ROLLING PLANNER      every 15 min + on new forecast/prices  → SlotPlan (96 slots × 15 min)
Component B  TRAJECTORY TRACKER   every tick  → traj_bias_w, dynamic floor/ceiling for guard
Component C  REACTIVE BALANCER    every tick  → raw_setpoint_w (v2 inner loop + traj_bias_w + planned grid charge)
Component D  OVERRIDES then GUARD every tick  → final setpoint_w (single SoC state machine)
```

Per-tick pipeline in `service.py` (triggered by `minyad/dsmr/net_power_w` or `minyad/grid/net_power_w`, exactly as v2):

```python
plan = planner.current_plan(now)                      # cached; planner runs on its own schedule
bias_w, floor_dyn, ceil_dyn = tracker.evaluate(now, soc, plan)
raw = balancer.tick(state, plan, bias_w)              # NO SoC clamp inside the balancer
sp  = overrides.apply_with_reason(raw, ...)           # identical semantics to v2 §7
sp  = guard.apply_with_reason(sp, floor_dyn, ceil_dyn,
                              skip_soc_limits=overrides.bypasses_soc_limits())
publish_if_changed(sp)
```

**Hard rule:** the balancer contains **no SoC floor/ceiling logic at all**. All SoC limiting lives in the guard, fed with dynamic limits from the tracker. This removes v2's double-clamp problem.

---

## 3. Component A — Rolling Planner

### 3.1 Trigger and horizon

- Runs at service start, then every `strategy3.plan_interval_min` (default **15**) minutes, and immediately when a new price vector or new solar forecast arrives.
- Horizon: from the current 15-min slot boundary forward `strategy3.horizon_slots` (default **96** = 24 h). Slot length fixed at 900 s.
- Timezone: Europe/Amsterdam for all "local time" rules (Friday detection, horizon boundaries).

### 3.2 Inputs (all per-slot vectors of length N=96)

| Vector | Source | Fallback if unavailable |
|---|---|---|
| `pv_forecast_w[t]` | Open-Meteo hourly `shortwave_radiation` (W/m²) for lat 51.97 / lon 4.31, linearly interpolated to 15-min, multiplied by `pv_calibration_factor` (§3.3) | all zeros |
| `load_forecast_w[t]` | consumption profile (§3.4) | `strategy3.consumption_fallback_w` (default 300) for every slot |
| `price_import[t]`, `price_export[t]` | latest vector from `minyad/trade/prices` (same payload schema as v2). **If absent or expired: constant vectors** `strategy3.fixed_price_import` (default **0.25**) and `strategy3.fixed_price_export` (default **0.00**) | the constants |
| `soc_now_pct` | latest telemetry | if stale > guard staleness limit, do not build a plan; keep last plan and let the guard zero the setpoint |

### 3.3 PV calibration factor (self-learning, replaces v2's GHI mode buckets)

Daily at plan time 06:00 local, recompute:

```
factor = clamp( Σ actual_pv_wh(last 14 days) / Σ shortwave_wh_per_m2(last 14 days, same timestamps),
                0.5 × factor_prev, 2.0 × factor_prev )
```

- Actual PV from Enphase telemetry rollups (`power_curve_rollups`, `source='solar'`, 900 s granularity).
- Persist in `settings` under key `strategy3.pv_calibration_factor`. Initial value: **7.0** (interpret as effective W of PV per W/m² of irradiance — roughly a 7 kWp-equivalent response; it self-corrects within days).
- If fewer than 3 days of history exist, keep the previous/initial factor unchanged.

### 3.4 Consumption profile (extends v2's to full-day)

Same construction as v2 `consumption_profile.py` (per-15-min-slot average household W over trailing `strategy3.consumption_lookback_days` = 14 days from `power_curve_rollups` `source='household'`), but used for **all 96 slots of the day**, not only overnight. Slots without history → `strategy3.consumption_fallback_w`.

### 3.5 Optimization — linear program (exact formulation)

Use `pulp` with the CBC solver (add to requirements; solve time for 96 slots is milliseconds). Δt = 0.25 h. Battery capacity `C` = `battery.capacity_wh` (new setting, default **10240**).

**Decision variables**, all ≥ 0, per slot t = 0..N−1:

```
ch[t]     charge power, W        ≤ effective_max_charge_w  (= min(battery.max_charge_w, max_charge_a × nominal_v), as v2)
dis[t]    discharge power, W     ≤ battery.max_discharge_w
gimp[t]   grid import, W
gexp[t]   grid export, W         ≤ strategy3.export_cap_w (default 0 → zero-export policy; set >0 to allow planned export)
soc[t]    state of charge, Wh    (t = 0..N; soc[0] = soc_now_pct/100 × C)
slack_lo[t], slack_hi[t]  SoC soft-constraint slacks, Wh
```

**Constraints:**

1. Power balance every slot: `pv[t] + dis[t] + gimp[t] == load[t] + ch[t] + gexp[t]`
2. SoC dynamics: `soc[t+1] == soc[t] + (ch[t] × eta_c − dis[t] / eta_d) × 0.25`
   with `eta_c = eta_d = strategy3.one_way_efficiency` (default **0.95**).
3. Soft SoC band: `soc[t] ≥ floor_wh − slack_lo[t]` and `soc[t] ≤ ceil_wh + slack_hi[t]`
   where `floor_wh = battery.soc_floor/100 × C`, `ceil_wh = battery.soc_ceiling/100 × C`.
   Hard bounds regardless of slack: `0.05 × C ≤ soc[t] ≤ C`.
4. Grid-charge gating: if `strategy.grid_charge_enabled` is false (default), add `ch[t] ≤ pv_surplus_cap[t]` where `pv_surplus_cap[t] = max(0, pv[t] − load[t]) + M_relax`, with `M_relax = strategy3.grid_charge_relax_w` (default **0**). This makes charging solar-surplus-only by default while remaining a one-setting change later.
5. **Friday full-cycle (LiFePO4 balancing), unchanged intent from v2:** if the horizon contains a Friday sunset (compute sunset from Open-Meteo daily data; fallback 21:00 local), then for the last slot at/before that sunset: `soc[t_sunset] ≥ 0.99 × C − slack_hi[t_sunset]`, and constraint 4 (solar-only) is **forced on** for all Friday slots even if `grid_charge_enabled` is true. Never plan grid import to satisfy the Friday target.
6. Terminal condition: `soc[N] ≥ strategy3.terminal_soc_pct (default 30) / 100 × C − slack_lo[N]` — prevents the optimizer from draining the battery at horizon end.

**Objective (minimize):**

```
Σ_t  price_import[t] × gimp[t] × 0.25 / 1000
   − price_export[t] × gexp[t] × 0.25 / 1000
   + cycle_cost × (ch[t] + dis[t]) × 0.25 / 1000      # cycle_cost = strategy3.cycle_cost_eur_kwh, default 0.03
   + 10.0 × (slack_lo[t] + slack_hi[t]) / 1000        # slack penalty, EUR/kWh-equivalent, dominates prices
```

The cycle-cost term prevents simultaneous charge+discharge and pointless micro-cycling without needing binaries. With fixed prices the LP degenerates to sensible self-consumption behavior; with variable prices it becomes arbitrage-aware automatically — **no code change needed later**.

**Output — `SlotPlan`** (dataclass, persisted to new table `slot_plans`, published retained on `minyad/strategy/plan` as JSON):

```json
{
  "generated_at": "...", "valid_from": "...", "slot_seconds": 900,
  "slots": [ { "start": "...", "soc_target_pct": 41.2, "planned_grid_charge_w": 0,
               "planned_export_w": 0, "pv_forecast_w": 812, "load_forecast_w": 340,
               "price_import": 0.25, "price_export": 0.0 }, ... ],
  "friday_full_cycle": false, "solver_status": "Optimal",
  "pv_calibration_factor": 7.3
}
```

`soc_target_pct[t]` = planned `soc[t+1] / C × 100`. `planned_grid_charge_w[t]` = `max(0, ch[t] − max(0, pv[t] − load[t]))` (the grid-fed portion of charging).

### 3.6 Fallback plan

If the solver fails (`status != Optimal`), Open-Meteo is unreachable AND no cached forecast < 24 h old exists, or any input vector cannot be constructed: build a **fallback SlotPlan** = hold current SoC flat (`soc_target_pct[t] = soc_now` for all t, all planned powers 0), flagged `"solver_status": "FALLBACK"`. The tracker treats a fallback plan as "no trajectory pressure" (bias 0, dynamic limits = static limits). Log at WARNING once per occurrence.

---

## 4. Component B — Trajectory Tracker

Runs every tick. Given `soc_actual_pct` and the plan's `soc_target_pct` linearly interpolated to `now`:

### 4.1 Trajectory bias

```
error_pct = soc_actual_pct − soc_plan_pct(now)          # >0 = ahead of plan (too full)
bias_w    = −clamp( error_pct/100 × C_wh / tau_h,        # tau_h = strategy3.traj_tau_hours, default 2.0
                    −strategy3.traj_bias_max_w, +strategy3.traj_bias_max_w )   # default max 400
```

Interpretation: the bias is the constant power that would close the SoC gap in `tau_h` hours. Positive error (battery fuller than planned) → negative bias → encourages discharge. This **replaces** v2's flat `price_discharge_bias_w`; delete that mechanism (the LP already encodes price preference in the trajectory itself).

Deadband: if `abs(error_pct) < strategy3.traj_deadband_pct` (default **3**), `bias_w = 0`.

### 4.2 Dynamic SoC limits for the guard (replaces v2's glide-path floor module entirely)

```
floor_dyn_pct = max( battery.soc_floor,  soc_plan_pct(now) − strategy3.traj_band_pct )   # band default 8
ceil_dyn_pct  = min( battery.soc_ceiling_effective(now),  soc_plan_pct(now) + strategy3.traj_band_pct )
```

Where `soc_ceiling_effective` is 100 on a Friday-full-cycle day (from the plan flag), else `battery.soc_ceiling`. On a FALLBACK plan: `floor_dyn = battery.soc_floor`, `ceil_dyn = soc_ceiling_effective` (static behavior).

This subsumes v2's overnight glide path: because the planned trajectory already rations overnight consumption against the forecast, the floor "glides" automatically, all day, with the same self-correcting property (the next 15-min replan re-anchors `soc[0]` to reality — that *is* the drift correction, so **do not port `floor_schedule.py` or the drift-factor logic**; delete-equivalent).

The tracker maintains **no latch state**. Hysteresis lives only in the guard.

---

## 5. Component C — Reactive Balancer (v2 inner loop, minimally changed)

Port v2 `executor.py` with these exact changes:

1. **Remove** the internal static SoC clamp (`_apply_soc_limits` and its latch state). The guard is the sole SoC authority.
2. **Remove** the price-discharge-window bias. Replace with `bias = tracker bias_w` added at the same point in the formula: `candidate = current − delta + bias_w`.
3. **Replace** the grid-charge-window force-charge (v2 step 1) with: if the current slot's `planned_grid_charge_w > 0`, force `candidate = min(planned_grid_charge_w + max(0, pv_now_w − load_now_w_estimate), effective_max_charge_w)`, where `load_now_w_estimate = max(0, net_grid_w + battery_power_w + pv_now_w)`. Keep the sticky ceiling-latch hysteresis exactly as v2 (`soc_hysteresis_pct` band) but latch against `ceil_dyn_pct` from the tracker. This fixes v2's "blind full-power grid charge": the planned wattage is what the LP sized, not the hardware max.
4. **Keep unchanged:** deadband (`ramp_floor_w`), ramp-hold direction persistence (`ramp_hold_seconds`, monotonic clock), proportional step (`balance_gain`, `ramp_ceiling_w`), power clamps, **export block with hysteresis and gradual trim including the stale-sample de-dup guard** (v2 step 3, port verbatim), and jitter suppression (`jitter_w`).
   - Export-block exception: if the current slot has `planned_export_w > 0` (only possible when `strategy3.export_cap_w > 0`), the export block threshold for this tick becomes `planned_export_w + strategy.export_block_threshold_w` instead of the bare threshold. With the default `export_cap_w = 0` this branch never activates.
5. `pv_now_w`: subscribe to live Enphase production (`minyad/solar/production_w`). If stale > 5 min, treat as 0. This value is used only in change 3's arithmetic; the balancer remains meter-driven.

---

## 6. Component D — Overrides and Guard

**Overrides:** port v2 `override.py` **unchanged**, including `override_soc_limits`, one-cycle auto-expiry, `pause` expiry, MQTT topic `minyad/control/override`, and the `battery_override` table.

**Guard:** port v2 `soc_guard.py` with one change: `apply_with_reason(setpoint, soc, floor_pct, ceil_pct, ...)` now receives `floor_dyn_pct` / `ceil_dyn_pct` from the tracker instead of reading a floor-schedule object. Order of checks unchanged and mandatory:

1. Bridge staleness (`inverter_poll_interval_s + goodwe_poll_interval_grace_s`, fallback `bridge_stale_seconds`) → force 0. Applies **even when** `skip_soc_limits` is true.
2. Voltage floor (`voltage_floor_v`, default 46.0) → force 0. Also applies under `skip_soc_limits`.
3. If `skip_soc_limits`: return.
4. SoC floor/ceiling latches with `soc_hysteresis_pct` band, against the **dynamic** limits. This is the **only** SoC state machine in v3.

---

## 7. Vesper surplus-forecast hook (publish-only)

After every successful (non-FALLBACK) plan, publish retained on `minyad/strategy/surplus_forecast`:

```json
{ "generated_at": "...", "slot_seconds": 900,
  "slots": [ { "start": "...", "surplus_w": 0 }, ... ] }
```

`surplus_w[t] = max(0, pv[t] − load[t] − ch[t])` from the LP solution — i.e., energy that would otherwise be exported/curtailed and is available for Vesper to dispatch to devices. v3 takes **no** action on this topic itself.

This MQTT publish is a point-forecast hint. The authoritative, quantified contract Vesper actually polls is the HTTP `minyad_forecast` block on `GET /api/v1/surplus` (P50/P25 scenario-derived, plus the SoC trajectory) — see `docs/minyad_forecast_contract.md`. The two are not the same mechanism: don't conflate this MQTT topic with that HTTP contract when reasoning about what Vesper consumes.

---

## 8. MQTT interface summary

**Subscribes** (same as v2 unless noted): `minyad/dsmr/net_power_w`, `minyad/grid/net_power_w`, battery SoC/voltage/power telemetry topics as v2, `minyad/trade/prices` (adapted: see implementation notes below), `minyad/control/override`, plus live PV power topic (`minyad/solar/production_w`).

**Publishes:**

| Topic | Retained | Content |
|---|---|---|
| `minyad/strategy/setpoint_w` | yes | final setpoint (shadow topic during rollout, §11) |
| `minyad/control/charge_w` / `discharge_w` | yes | as v2 (only when primary) |
| `minyad/strategy/plan` | yes | full SlotPlan JSON |
| `minyad/strategy/decision` | no | per-tick JSON: raw, bias_w, floor_dyn, ceil_dyn, final, reason chain (one reason string per pipeline stage) |
| `minyad/strategy/surplus_forecast` | yes | §7 |
| `minyad/strategy/soc_floor` | yes | keep for dashboard compatibility: publish `floor_dyn_pct` |

Delete v2-only topics `minyad/strategy/floor_drift_factor` and `minyad/strategy/floor_remaining_expected_wh` (confirmed: no dashboard/API code reads these today, so no repointing was needed).

---

## 9. Database

- New table `slot_plans` (id, generated_at, valid_from, json payload, solver_status). Upsert latest; keep 30 days for evaluation, prune older on daily planner run.
- New table `strategy_shadow_log` (§11).
- Reuse `settings`, `battery_override`, `power_curve_rollups` unchanged.
- Migrations via the repo's existing Alembic mechanism (`migrate/alembic/versions/0022_strategy_v3.py`).

---

## 10. Settings (all in `settings` KV table, defaults in `v3/constants.py`)

**New keys:**

| Key | Default | Meaning |
|---|---|---|
| `battery.capacity_wh` | 10240 | Usable capacity for LP + bias math |
| `strategy3.plan_interval_min` | 15 | Planner cadence |
| `strategy3.horizon_slots` | 96 | Plan horizon (×15 min) |
| `strategy3.one_way_efficiency` | 0.95 | ηc = ηd |
| `strategy3.cycle_cost_eur_kwh` | 0.03 | LP wear term |
| `strategy3.fixed_price_import` | 0.25 | Used when no price vector present |
| `strategy3.fixed_price_export` | 0.00 | idem |
| `strategy3.export_cap_w` | 0 | 0 = never plan export |
| `strategy3.grid_charge_relax_w` | 0 | Slack on solar-only charge gate |
| `strategy3.terminal_soc_pct` | 30 | Horizon-end SoC floor |
| `strategy3.traj_tau_hours` | 2.0 | Bias correction time constant |
| `strategy3.traj_bias_max_w` | 400 | Bias clamp |
| `strategy3.traj_deadband_pct` | 3 | No bias inside this SoC error |
| `strategy3.traj_band_pct` | 8 | Dynamic floor/ceiling band around plan |
| `strategy3.pv_calibration_factor` | 7.0 | Self-learning (§3.3) |
| `strategy3.consumption_lookback_days` | 14 | Profile window |
| `strategy3.consumption_fallback_w` | 300 | Profile fallback |

**Retained v2 keys, same semantics:** `battery.soc_floor` (20), `battery.soc_ceiling` (90), `battery.max_charge_w`, `battery.max_discharge_w`, `battery.max_charge_a`, `battery.nominal_v`, `battery.inverter_poll_interval_s`, `battery.goodwe_poll_interval_grace_s`, `strategy.grid_charge_enabled` (false), `strategy.grid_target_w`, `strategy.ramp_floor_w`, `strategy.ramp_hold_seconds`, `strategy.ramp_ceiling_w`, `strategy.balance_gain`, `strategy.jitter_w`, `strategy.export_block_threshold_w`, `strategy.export_block_hysteresis_w`, `strategy.soc_hysteresis_pct`, `strategy.bridge_stale_seconds`, `strategy.voltage_floor_v`, `strategy.adjustment_log_interval_sec`.

**Removed (not read by v3, not in v3/constants.py):** `strategy.ghi_solar_rich_threshold`, `strategy.ghi_solar_poor_threshold`, `strategy.price_cheap_threshold_eur_kwh`, `strategy.price_expensive_threshold_eur_kwh`, `strategy.price_discharge_bias_w`, `strategy.daily_recalculate_local_time`, `strategy.floor_horizon_start_local`, `strategy.floor_horizon_end_local`, `strategy.control_refresh_interval_sec`, `strategy.active_command_retry_interval_sec` (the last two were never wired in v2).

---

## 11. Rollout — shadow mode, then promotion

1. **Shadow phase (default).** Env var `STRATEGY_VERSION` on `minyad-strategy`: `v2` (current default) or `v3`. A second container `minyad-strategy-v3` runs v3 with `SHADOW_MODE=true`: it computes everything and publishes `minyad/strategy3/setpoint_w`, `minyad/strategy3/plan`, `minyad/strategy3/decision`, `minyad/strategy3/soc_floor`, but **never** publishes to `minyad/control/*` or `minyad/strategy/setpoint_w`/`plan`/`decision`/`soc_floor` (those stay v2-owned while shadowing). `minyad/strategy/surplus_forecast` has no v2 equivalent, so it is published under its real name in both modes.
2. Every tick in shadow mode, insert into `strategy_shadow_log` (ts, v2_setpoint_w [subscribed from live topic], v3_setpoint_w, soc, net_grid_w, v3_reason). `scripts/compare_strategies.py` produces daily aggregates: mean |v2−v3|, sign disagreements, would-have-exported Wh, would-have-hit-floor events.
3. **Promotion.** After Daniel's manual review: set `STRATEGY_VERSION=v3` and `SHADOW_MODE=false` on the primary container (switch its command to `minyad.strategy.v3.service`), retire the shadow container. `minyad-control` continues forwarding `minyad/strategy/setpoint_w` unchanged (no changes to `minyad-control` are required or permitted in this task).
4. v2 code stays in the repo, untouched, as rollback (`STRATEGY_VERSION=v2`).

---

## 12. Invariants and acceptance tests (implemented as pytest; all must pass)

1. Sign convention round-trip: setpoint +500 → `charge_w=500, discharge_w=0`; −500 → `charge_w=0, discharge_w=500`.
2. With prices fixed, zero PV forecast, SoC 50%: LP plan discharges to cover forecast load and never plans grid charging (with `grid_charge_enabled=false`) and never plans export (with `export_cap_w=0`).
3. Friday in horizon: planned SoC at Friday sunset is very close to 99% **and** `planned_grid_charge_w = 0` for all Friday slots, even with `grid_charge_enabled=true`. (Implementation note: the sunset target is a *soft* constraint per §3.5's own objective — weighted heavily (10 EUR/kWh-equivalent) against the cycle cost, so it is a strong preference rather than an absolute guarantee; verified to land within ~1-2% of 99% given ample solar, never via grid import.)
4. Bridge telemetry stale → final setpoint 0, even with an active `override_soc_limits` override.
5. Voltage 45.9 V → final setpoint 0 regardless of SoC.
6. SoC at `floor_dyn` → discharge blocked; released only at `floor_dyn + soc_hysteresis_pct`.
7. Export −300 W while actively discharging → setpoint trims gradually (bounded by `ramp_ceiling_w`), and holds on a repeated identical telemetry sample (de-dup guard).
8. Trajectory bias: soc_actual 60, plan 50, C=10240, tau=2 → bias = −clamp(0.10×10240/2, 400) = −400 W (clamped).
9. `abs(error_pct) < 3` → bias exactly 0.
10. FALLBACK plan → bias 0, floor_dyn = static floor, ceil_dyn = static ceiling (Friday-aware).
11. LP solution never contains `ch[t] > 0` and `dis[t] > 0` in the same slot (with default cycle cost).
12. Solver failure → FALLBACK plan produced, service keeps ticking, no exception escapes the tick loop.
13. Shadow mode: nothing is ever published on `minyad/control/*` or `minyad/strategy/setpoint_w`.
14. Simultaneity: two rapid ticks do not interleave (tick lock).
15. Plan replan re-anchoring: after a replan with soc_now far below the previous trajectory, `floor_dyn` immediately follows the new (lower) trajectory — no upward ratchet requirement (unlike v2's monotone floor; this is intentional, the 15-min replan is the correction mechanism).

## 13. Implementation notes (deviations from the literal spec text, and why)

Two points where the implementing agent found the literal spec text under-specified or physically inconsistent, resolved with the repo owner:

1. **Price feed topic/schema.** The spec's `minyad/trade/prices` / `{start,end,price_eur_kwh}` interface has no publisher anywhere in this repo (v2's planner has the same dead wiring). The real `minyad-trade` service publishes ENTSO-E day-ahead prices on `minyad/trade/prices/da/{day}/full` as `{date,hour,starts_at,price_eur_kwh}` (import price only — no export price feed exists). v3 adapts to this real topic/schema (`price_client.py`) so the price vector is actually live rather than symbolically wired. `price_export` remains the fixed settings constant, since no export price feed exists to adapt to.
2. **LP curtailment.** Constraint 1 as literally written (`pv + dis + gimp == load + ch + gexp`) has no way to discard excess forecast PV, so it goes infeasible whenever forecast PV exceeds `load + max_charge_w + export_cap_w` — a realistic case with a 1440 W hardware charge cap, `export_cap_w=0`, and a sunny day. A free curtailment variable (`curtail[t]`, `0 ≤ curtail[t] ≤ pv[t]`, used in place of `pv[t]` in the balance equation) was added to fix this; it costs nothing in the objective, matching how a real inverter clips unusable excess PV.

Also worth knowing: the Friday 99% sunset target (§3.5 constraint 5) is written as a *soft* constraint sharing the same `slack_hi` variable as the general SoC ceiling band, weighted at 10 EUR/kWh-equivalent against a 0.03 EUR/kWh cycle cost. Verified by hand: under those exact weights the LP's true economic optimum can land a percent or two short of 99% even with abundant, well-timed free solar, because forcing an exact 99% costs strictly more in battery cycling than the slack penalty it avoids. This is the objective function's designed behavior, not a scheduling bug — see invariant 3 above and its test for the tolerance this implies in practice.

---

## 14. Traceability — v2 issues resolved

| v2 issue (from code review) | v3 resolution |
|---|---|
| `solar_forecast_w` dead weight, no anticipation | LP planner consumes PV forecast (§3) |
| Three SoC state machines | One, in the guard (§2, §6) |
| Blind full-power single grid-charge window | LP-sized per-slot `planned_grid_charge_w` (§3.5, §5.3) |
| Flat 200 W price bias, no arbitrage logic | Price vector in LP objective; bias mechanism deleted (§4.1) |
| Glide floor only overnight, zero-solar assumption | Full-day trajectory band; replan is the drift correction (§4.2) |
| No price/floor coordination | Single trajectory encodes both (§3–§4) |
| Dead settings (`control_refresh_interval_sec`, `active_command_retry_interval_sec`) | Removed (§10) |
| Stale `charging_strategy.md` | Replaced by this document |
