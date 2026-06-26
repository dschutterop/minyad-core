# Battery Charge/Discharge Strategy — Analysis and Rebuild Prompt

## Current Strategy Description

### Architecture Overview

There are four independent layers that can influence battery behavior, from lowest to highest level:

1. **GoodWe Bridge** — hardware actuator (host machine)
2. **HysteresisController + ControlApp** — primary real-time grid-balancing loop (`minyad-control` container)
3. **ChargeController / strategy** — forecast-driven strategy engine (library module, not yet running as a standalone service)
4. **Claude AI Agent** — LLM-driven operator agent (`minyad-agent` container)

---

### Layer 1 — Real-time Hysteresis FSM (the active controller)

**File**: `control/hysteresis.py`

This is the only layer that actually runs and commands the battery in production.

It is a **purely reactive, threshold-hysteresis finite state machine** with four states: `IDLE → CHARGING → COOLDOWN → IDLE` and `IDLE → DISCHARGING → COOLDOWN → IDLE`. The single input signal is `surplus_w = -grid_power_w` (positive = solar export, negative = grid import) read from the P1/DSMR meter.

Transitions (defaults from DB migrations):

| Transition | Trigger | Debounce |
|---|---|---|
| IDLE → CHARGING | `surplus_w ≥ 500 W` | sustained 180 s |
| CHARGING → COOLDOWN | `surplus_w < 150 W` | sustained 300 s |
| IDLE → DISCHARGING | `surplus_w ≤ −300 W` (i.e. 300 W import) | sustained 180 s |
| DISCHARGING → COOLDOWN | `surplus_w > −100 W` | sustained 300 s |
| COOLDOWN → IDLE | — | 180 s fixed wait |

A **cooldown bypass** (`hysteresis.py:130–139`) prevents a 10-minute blind spot: if the opposite trigger is sustained through the cooldown period, it can skip the remaining wait.

### Layer 2 — ControlApp: SoC Guard + Slow Balancer

**File**: `control/main.py`

Sits above the FSM and does two things:

1. **SoC guard** (`main.py:503–517`): Before each FSM tick, it clamps `surplus_w` to mask the charge trigger when SoC ≥ 90 % and the discharge trigger when SoC ≤ 20 %. It also force-idles the FSM if a limit is reached mid-session.

2. **Slow balancer** (`main.py:583–655`): Once the FSM is in CHARGING or DISCHARGING, adjusts the power setpoint every 10 s using proportional control with gain 0.5 and a 150 W deadband. Steps are clamped between 100–500 W per interval.

The setpoint is sent as a watt figure on `minyad/control/charge_w` or `minyad/control/discharge_w`, consumed by the GoodWe bridge on the host which writes it to the inverter via the GoodWe cloud API and also writes ceiling limits to Modbus registers 45565/45566.

### Layer 3 — ChargeController / Strategy Engine (dormant)

**File**: `minyad/strategy/charge_controller.py`

A more sophisticated class that exists but **is not running as any Docker service**. It adds:

- **Daily GHI-based mode selection** (`recalculate_daily()`, line 255): fetches tomorrow's shortwave radiation total from Open-Meteo. Above 4.5 kWh/m²/day → `SOLAR_RICH`, below 1.5 → `SOLAR_POOR`, otherwise `NORMAL`.
- **Ramp-hold hysteresis** (`_held_ramp_delta()`, line 287): imbalance must persist for 120 s before a setpoint change is applied, then capped at 1000 W per step.
- **Jitter suppression**: ignores setpoint deltas ≤ 50 W.
- **Discharge blocking during export**: if grid is already at or below the target (0 W), discharge is blocked.

### Layer 4 — Claude Agent (LLM, currently in DRY_RUN)

**File**: `minyad-agent/agent.py`, `minyad-agent/prompts.py`

Runs every 15 minutes via APScheduler. Instructs the LLM to maintain zero grid flow contextually — it can pre-discharge before large loads if solar will refill before sunset, and should be conservative with uncertain forecasts. A rule-based pre-filter skips the LLM call when SoC ≤ floor with no solar in the next 3 hours.

Running in `DRY_RUN=true` by default — it logs decisions but does not apply setpoints.

### Hardware Path

GoodWe bridge (`host-services/goodwe_bridge.py`) receives charge/discharge targets via MQTT, writes them to the inverter via GoodWe's UDP/AA55 protocol API, and separately writes ceiling limits to Modbus registers 45565/45566.

---

### Key Observations

1. **Electricity prices are collected but ignored.** `minyad-trade` fetches ENTSO-E/EPEX day-ahead prices and publishes them to MQTT and the API, but nothing in the control or hysteresis layers reads them.

2. **The ChargeController is dead code at runtime.** Its GHI-mode differentiation, ramp-hold logic, and discharge-during-export blocking are all dormant.

3. **Sign convention mismatch.** The hysteresis/ControlApp layer uses positive = charge on a dedicated topic. The `ChargeController.evaluate()` and the agent's `set_battery_setpoint` use negative = charge, positive = discharge on a single topic.

4. **No look-ahead in the primary loop.** The FSM responds only to what the meter reads right now. It cannot anticipate a cloud patch, a large load starting, or a price peak.

5. **The SoC ceiling of 90 % is static.** On a sunny day this wastes capacity. On a rainy day it may be too low to bridge the evening.

---

### Suggested Improvements

1. **Wire ENTSO-E prices into the daily strategy** — plan a grid-charge window during cheap overnight hours and protect SoC heading into expensive peaks.
2. **Activate `ChargeController` as a running service** — its GHI-mode logic and `recalculate_daily()` are production-ready but never called.
3. **Make the SoC ceiling dynamic** — lower it on solar-rich days (refill is guaranteed), raise it on solar-poor days (reserve capacity for the evening).
4. **Enable the Claude agent in production** — with a conservative setpoint range while the FSM handles real-time balancing.
5. **Add price-awareness to the agent system prompt** — instruct it to discharge during expensive hours and charge during cheap ones.
6. **Fix the sign convention mismatch** before connecting layers — define one canonical convention in a shared constants module.
7. **Predictive discharge reservation** before large loads — subscribe to a "large load starting" MQTT event and pre-discharge if solar forecast confirms recharge before sunset.

---

## Rebuild Prompt

You are an expert Python engineer and energy systems architect. Your task is to redesign and reimplement the battery charge/discharge strategy for the **Minyad** home energy management system. Below is a complete description of the system, its data sources, its current codebase structure, and the goals for the new strategy. Implement the new strategy as described.

---

### System Context

**Hardware:**
- GoodWe inverter/charger with a 48 V lithium battery bank (max charge 1440 W, max discharge 5000 W, 30 A charge current limit).
- A P1/DSMR smart meter reading grid import/export in real time (net_power_w: positive = importing, negative = exporting).
- Solar PV panels (modelled as ~5000 W peak × 0.80 efficiency at Schipluiden, NL, lat 51.97, lon 4.31).

**Software stack:**
- Python 3.12, asyncio throughout.
- MQTT broker (Mosquitto) as the internal message bus. All inter-service communication is via MQTT.
- PostgreSQL database with a `settings` key-value table (key TEXT, value TEXT) and append-only log tables (`telemetry_log`, `setpoint_log`, `strategy_decisions`, `agent_decisions`).
- Docker Compose, one container per service.
- Services: `minyad-control` (real-time FSM), `minyad-agent` (LLM agent), `minyad-trade` (price fetcher), `forecast` (solar forecast), `goodwe_bridge` (host-level hardware actuator), `api` (FastAPI REST).

**MQTT topic conventions (current):**
- `minyad/dsmr/net_power_w` — P1 meter net grid power (W, retained, positive = import)
- `minyad/battery/soc` — battery state-of-charge (%, retained)
- `minyad/battery/power_w` — battery power (W, positive = discharging, retained)
- `minyad/battery/voltage` — battery voltage (V, retained)
- `minyad/forecast/power_w` — solar production forecast for the next hour (W)
- `minyad/forecast/hourly` — JSON array of `{hour: ISO8601, power_w: int}` for next 24 h
- `minyad/trade/prices` — JSON array of `{start: ISO8601, end: ISO8601, price_eur_kwh: float}` for next 24–36 h (ENTSO-E day-ahead)
- `minyad/control/charge_w` — target charge power sent to GoodWe bridge (W, 0 = stop)
- `minyad/control/discharge_w` — target discharge power sent to GoodWe bridge (W, 0 = stop)
- `minyad/control/override` — JSON override command from operator or agent
- `minyad/strategy/active` — JSON describing the currently active strategy mode (retained)
- `minyad/strategy/decision` — JSON of the most recent strategy decision (retained)

**Settings keys (PostgreSQL `settings` table):**
- `battery.soc_floor` (default 20) — minimum allowed SoC (%)
- `battery.soc_ceiling` (default 90) — maximum allowed SoC (%)
- `battery.max_charge_w` (default 1440) — hardware charge power cap (W)
- `battery.max_discharge_w` (default 5000) — hardware discharge power cap (W)
- `battery.max_charge_a` (default 30) — hardware charge current cap (A)
- `battery.nominal_v` (default 48) — battery nominal voltage (V)
- `strategy.ghi_solar_rich_threshold` (default 4.5) — GHI above which tomorrow is "solar rich" (kWh/m²/day)
- `strategy.ghi_solar_poor_threshold` (default 1.5) — GHI below which tomorrow is "solar poor" (kWh/m²/day)
- `strategy.grid_target_w` (default 0) — desired steady-state grid net power (W)
- `strategy.price_cheap_threshold_eur_kwh` (default 0.08) — price below which grid charging is worth doing
- `strategy.price_expensive_threshold_eur_kwh` (default 0.25) — price above which discharging is worth doing
- `strategy.grid_charge_enabled` (default false) — whether to allow charging from the grid (not just from solar)
- `strategy.daily_recalculate_local_time` (default "22:00") — when to recalculate tomorrow's strategy

---

### Goals for the New Strategy

The new strategy must replace the existing `HysteresisController`+`ControlApp` loop and the dormant `ChargeController`. It should be a single cohesive service with two cooperating components: a **daily planner** and a **real-time executor**.

**Primary objective:** Keep net grid power as close to zero as possible at all times (self-consumption maximisation).

**Secondary objectives, in priority order:**
1. Respect hardware limits (SoC floor/ceiling, power caps, current cap).
2. Avoid unnecessary battery cycling — only charge or discharge if the benefit exceeds the threshold.
3. On solar-rich days: allow deeper discharge during the day confident that solar will refill before sunset.
4. On solar-poor days: raise the effective reserve so the battery can cover the full evening peak from stored energy.
5. When grid charging is enabled: charge from the grid during cheap price windows and discharge (up to ceiling) during expensive price windows.
6. Never discharge below the SoC floor for any reason other than an explicit operator override.
7. Never export to the grid intentionally (do not over-discharge into export).

---

### Architecture Requirements

#### 1. Unified Sign Convention

Establish one canonical convention for all internal calculations and MQTT messages:

- **Positive watts = power flowing into the battery (charging).**
- **Negative watts = power flowing out of the battery (discharging).**
- `net_grid_w` positive = importing from grid (load exceeds generation).
- `net_grid_w` negative = exporting to grid (generation exceeds load).

Publish the single signed setpoint on `minyad/strategy/setpoint_w` (retained). The bridge adapter translates this to `minyad/control/charge_w` and `minyad/control/discharge_w` as it already does.

#### 2. Daily Planner (`StrategyPlanner`)

Runs once per day at the configured `strategy.daily_recalculate_local_time` (default 22:00 local).

**Inputs:**
- Tomorrow's hourly GHI forecast from Open-Meteo (lat 51.97, lon 4.31).
- Tomorrow's hourly ENTSO-E day-ahead price curve from the `minyad/trade/prices` MQTT topic or the database.
- Current `soc_floor` and `soc_ceiling` from settings.

**Outputs — a `DayPlan` dataclass persisted to the DB and published on `minyad/strategy/active`:**

```python
@dataclass
class DayPlan:
    date: date                        # the calendar day this plan covers
    solar_mode: str                   # SOLAR_RICH | NORMAL | SOLAR_POOR
    forecast_ghi_kwh_m2: float        # total GHI for the day
    effective_soc_floor: int          # may be lower than configured floor on solar-rich days
    effective_soc_ceiling: int        # may be higher than configured ceiling on solar-poor days
    grid_charge_windows: list[tuple[datetime, datetime]]  # cheap hours to charge from grid
    price_discharge_windows: list[tuple[datetime, datetime]]  # expensive hours to prefer discharge
    planned_soc_at_sunset: int        # target SoC at end of solar production
    valid_until: datetime             # end of the calendar day (23:59:59 local)
    reason: str
```

**Planning rules:**

- **Solar mode selection:**
  - `SOLAR_RICH` if GHI > `ghi_solar_rich_threshold`: lower `effective_soc_floor` by up to 10 pp (but never below `abs_floor = 10 %`) — the battery can be drawn down more aggressively because solar will refill it. Set `effective_soc_ceiling = soc_ceiling`.
  - `SOLAR_POOR` if GHI < `ghi_solar_poor_threshold`: raise `effective_soc_ceiling` to min(`soc_ceiling + 10`, 95) so that a grid-charge window fills the reserve. Set `effective_soc_floor = soc_floor`.
  - `NORMAL` otherwise: use configured floor/ceiling unchanged.

- **Grid charge windows** (only if `strategy.grid_charge_enabled = true`):
  - Find contiguous hour blocks where `price_eur_kwh < price_cheap_threshold`.
  - Only include windows between 22:00 and 08:00 local (overnight only — avoid daytime grid charging that competes with solar).
  - If a cheap window exists and tomorrow is `SOLAR_POOR` or `NORMAL`, plan to fill to `effective_soc_ceiling` during the cheapest contiguous block.

- **Price discharge windows:**
  - Find hour blocks where `price_eur_kwh > price_expensive_threshold`.
  - Mark these as periods where the executor should prefer discharge up to the grid target even if grid flow is balanced (proactive arbitrage).

- **Planned SoC at sunset:**
  - On `SOLAR_RICH`: target sunset SoC ≥ `effective_soc_floor + 20`.
  - On `SOLAR_POOR`: target sunset SoC ≥ `effective_soc_ceiling − 5` (i.e. arrive at sunset nearly full from solar + grid charge).
  - On `NORMAL`: target sunset SoC ≥ `soc_floor + 30`.

#### 3. Real-time Executor (`StrategyExecutor`)

Runs on every P1 meter event (typically every 1–5 s). This replaces the `HysteresisController` + `ControlApp` slow balancer.

**Inputs on each tick:**
- `net_grid_w` (from MQTT `minyad/dsmr/net_power_w`)
- `battery_soc` (from MQTT `minyad/battery/soc`)
- `battery_power_w` (from MQTT `minyad/battery/power_w`, positive = discharging)
- `solar_forecast_w` — next-hour production estimate (from MQTT `minyad/forecast/power_w`)
- Current `DayPlan` (loaded from DB on startup, refreshed at midnight)
- Current `override` if any (from DB or MQTT)

**Algorithm:**

```
function compute_setpoint(state, plan, now) -> int:

    # 1. Hard limits: SoC boundaries always win
    if state.soc <= plan.effective_soc_floor and setpoint < 0:
        return 0   # block discharge, do not charge either unless surplus exists
    if state.soc >= plan.effective_soc_ceiling and setpoint > 0:
        return 0   # block charge

    # 2. Grid charge window: if we are inside a planned grid charge window
    #    and SoC < effective_soc_ceiling, force charge at max_charge_w regardless
    #    of current grid flow. Grid import is intentional here.
    if plan.in_grid_charge_window(now) and state.soc < plan.effective_soc_ceiling:
        return min(max_charge_w, effective_cap_w)

    # 3. Price discharge window: if inside a price discharge window,
    #    add a proactive discharge bias so the battery contributes even if
    #    the meter is momentarily balanced.
    discharge_bias_w = PRICE_DISCHARGE_BIAS_W if plan.in_price_discharge_window(now) else 0

    # 4. Primary balancing: compute the setpoint needed to hit grid_target
    #    (default 0 W). Positive error = importing too much → discharge.
    #    Negative error = exporting too much → charge.
    error_w = state.net_grid_w - plan.grid_target_w

    # 5. Apply ramp hold: only act if the error has persisted for hold_seconds
    #    and exceeds the ramp floor. This suppresses noise and chattering.
    if abs(error_w) < RAMP_FLOOR_W:
        return state.current_setpoint   # within deadband, hold current setpoint

    if not ramp_hold_satisfied(error_w, hold_seconds=RAMP_HOLD_SECONDS):
        return state.current_setpoint   # direction not yet sustained

    # 6. Compute candidate setpoint
    delta = clamp(error_w * BALANCE_GAIN, -RAMP_CEILING_W, RAMP_CEILING_W)
    candidate = clamp(
        state.current_setpoint + delta + discharge_bias_w,
        -plan.effective_max_discharge_w,
        plan.effective_max_charge_w,
    )

    # 7. Block discharge during export (never intentionally export)
    if state.net_grid_w < -EXPORT_BLOCK_THRESHOLD_W and candidate < 0:
        candidate = 0

    # 8. Clamp by SoC boundaries again after all adjustments
    if state.soc <= plan.effective_soc_floor:
        candidate = max(0, candidate)
    if state.soc >= plan.effective_soc_ceiling:
        candidate = min(0, candidate)

    # 9. Jitter suppression
    if abs(candidate - state.current_setpoint) < JITTER_W:
        return state.current_setpoint

    return candidate
```

**Constants (all DB-overridable via `settings`):**

| Constant | Default | Description |
|---|---|---|
| `RAMP_FLOOR_W` | 200 W | Minimum error before acting |
| `RAMP_HOLD_SECONDS` | 90 s | Error must persist before setpoint changes |
| `RAMP_CEILING_W` | 800 W | Max setpoint change per ramp step |
| `BALANCE_GAIN` | 0.6 | Proportional gain: delta = error × gain |
| `JITTER_W` | 50 W | Minimum setpoint change to publish |
| `EXPORT_BLOCK_THRESHOLD_W` | 100 W | Export below this does not block discharge |
| `PRICE_DISCHARGE_BIAS_W` | 200 W | Extra discharge added during expensive price windows |
| `CONTROL_REFRESH_INTERVAL_SEC` | 300 s | Force-republish active setpoint even without change |
| `ACTIVE_COMMAND_RETRY_INTERVAL_SEC` | 60 s | Retry if battery not responding to setpoint |

**Ramp hold implementation:**
Track `{direction: +1|-1, first_seen: monotonic}` per direction. Reset when direction flips. Fire when `monotonic() - first_seen >= RAMP_HOLD_SECONDS`.

**Ineffective command detection:**
If the current setpoint is non-zero but `battery_power_w` has not changed by more than 150 W in the last `ACTIVE_COMMAND_RETRY_INTERVAL_SEC` seconds, re-publish the same setpoint (the GoodWe bridge may have missed it or the inverter dropped the command).

#### 4. SoC Guard (always-on safety layer)

Implement as a thin wrapper around `compute_setpoint()` that applies hard limits before any setpoint is published:

- If `battery_soc <= effective_soc_floor`: force setpoint ≥ 0 (no discharge).
- If `battery_soc >= effective_soc_ceiling`: force setpoint ≤ 0 (no charge).
- If bridge last-seen > 60 s: suppress all setpoints (hardware safety).
- If `battery_voltage` drops below 46.0 V: force setpoint = 0 regardless of SoC reading (voltage guard against BMS inaccuracy).

#### 5. Override Modes

Support the following override modes via `minyad/control/override` MQTT or API:

| Mode | Behaviour |
|---|---|
| `none` | Normal strategy runs |
| `force_charge` | Charge at `max_charge_w` regardless of grid or solar, respecting SoC ceiling |
| `force_discharge` | Discharge at specified wattage, respecting SoC floor |
| `force_idle` | Stop all battery activity; hold at current SoC |
| `pause` | Same as `force_idle` but for a timed duration (seconds); auto-expires |
| `grid_charge_now` | Same as `force_charge` but limited to cheap price windows check skipped |

Overrides are persisted to the `battery_override` DB table with `expires_at`. The executor checks on every tick whether the override has expired and clears it automatically.

---

### Implementation Requirements

#### File Structure

Create the new strategy as a standalone Python package `minyad/strategy/v2/` (so the existing `charge_controller.py` is not overwritten). The package contains:

```
minyad/strategy/v2/
    __init__.py
    constants.py        # all tuneable constants with DB-override support
    models.py           # DayPlan, StrategyDecision, ExecutorState dataclasses
    planner.py          # StrategyPlanner class
    executor.py         # StrategyExecutor class
    soc_guard.py        # SoCGuard wrapper
    override.py         # OverrideManager class
    service.py          # main() entry point wiring planner + executor + MQTT
```

#### `service.py` entry point

- Connect to MQTT and PostgreSQL on startup.
- Load `DayPlan` from DB for today (or generate a `NORMAL` default plan if none exists).
- Subscribe to: `minyad/dsmr/net_power_w`, `minyad/battery/+`, `minyad/forecast/power_w`, `minyad/trade/prices`, `minyad/control/override`.
- On each `net_power_w` message: call `executor.tick(state)` → `soc_guard.apply(setpoint)` → publish to `minyad/strategy/setpoint_w` if changed.
- Schedule `planner.recalculate()` at the configured daily time using `apscheduler.schedulers.asyncio.AsyncIOScheduler`.
- Publish `minyad/strategy/decision` (retained, JSON) after every setpoint change with: `timestamp`, `setpoint_w`, `soc`, `net_grid_w`, `solar_forecast_w`, `mode`, `reason`, `plan_date`, `in_grid_charge_window`, `in_price_discharge_window`.
- Log every setpoint change to the `setpoint_log` table.
- Expose a `/health` HTTP endpoint (port 8080) returning `{"status": "ok", "state": ...}`.

#### `constants.py`

All constants must be loadable from the PostgreSQL `settings` table at startup and refreshable via a `SIGHUP` handler or a `minyad/strategy/reload` MQTT command, without restarting the service. Define a `Settings` class that:
- Reads all keys from DB on init.
- Falls back to hardcoded Python defaults if a key is absent.
- Exposes typed properties (e.g. `settings.ramp_floor_w -> int`).
- Re-reads from DB on `reload()`.

#### Sign convention

**Adopt throughout without exception:**
- Setpoint positive = charge (battery absorbing power).
- Setpoint negative = discharge (battery supplying power).
- Grid positive = importing (load > generation).
- Grid negative = exporting (generation > load).
- Battery power positive = discharging (matching the GoodWe MQTT output).

When publishing to the bridge:
```python
if setpoint_w > 0:
    mqtt.publish("minyad/control/charge_w", str(setpoint_w))
    mqtt.publish("minyad/control/discharge_w", "0")
elif setpoint_w < 0:
    mqtt.publish("minyad/control/charge_w", "0")
    mqtt.publish("minyad/control/discharge_w", str(abs(setpoint_w)))
else:
    mqtt.publish("minyad/control/charge_w", "0")
    mqtt.publish("minyad/control/discharge_w", "0")
```

#### Tests

Write `pytest` unit tests in `tests/strategy/v2/` covering:

1. `TestSoCGuard`: verify discharge is blocked at floor, charge is blocked at ceiling, both independently; verify bridge-stale and voltage-guard paths.
2. `TestExecutor`:
   - Steady export (−600 W) → charge setpoint ramps up after hold.
   - Steady import (+600 W) → discharge setpoint ramps up after hold.
   - Discharge blocked when `net_grid_w < −EXPORT_BLOCK_THRESHOLD_W`.
   - Jitter suppression: 30 W change is not published.
   - Price discharge window adds bias.
   - Grid charge window ignores grid flow and forces max charge.
3. `TestPlanner`:
   - Solar-rich GHI lowers `effective_soc_floor`.
   - Solar-poor GHI raises `effective_soc_ceiling`.
   - Cheap price windows are correctly identified and limited to overnight hours.
   - Expensive price windows are identified.
   - Plan is idempotent: calling `recalculate()` twice produces the same `DayPlan`.
4. `TestOverrideManager`:
   - `force_idle` suppresses all setpoints.
   - `pause` auto-expires after its duration.
   - `force_charge` overrides a discharge decision.
5. `TestIntegration`: mock MQTT + in-memory settings; run a sequence of 60 ticks simulating a morning solar ramp and verify the setpoint trajectory looks correct (charging kicks in, ramps up with solar, stops at ceiling).

All tests must be runnable with `pytest tests/strategy/v2/` with no external dependencies (use `unittest.mock` for MQTT and DB).

---

### Migration Notes

- The new service runs as a **separate Docker container** `minyad-strategy` that runs alongside `minyad-control` initially. `minyad-control` continues to run unchanged.
- `minyad-strategy` publishes to `minyad/strategy/setpoint_w` (new topic). The `minyad-control` container publishes to `minyad/control/charge_w` and `minyad/control/discharge_w` as before.
- Add an env var `STRATEGY_V2_PRIMARY=false` to `minyad-control`. When `true`, `minyad-control` reads its setpoints from `minyad/strategy/setpoint_w` instead of running its own FSM, effectively delegating control to the new service.
- This allows a zero-downtime cutover: run both, observe `minyad/strategy/decision` in parallel for several days, then flip `STRATEGY_V2_PRIMARY=true`.
- After cutover is validated, `minyad-control`'s FSM code can be removed or the container deprecated.
- The existing `ChargeController` in `minyad/strategy/charge_controller.py` should be retired but not deleted until the new service has been live for 30 days.

---

### What to Deliver

1. The complete `minyad/strategy/v2/` Python package as described above.
2. A `minyad-strategy/Dockerfile` (Python 3.12-slim, non-root user, same pattern as existing Dockerfiles in this repo).
3. A `docker-compose.yml` addition for `minyad-strategy` with env vars for `DB_URL`, `MQTT_HOST`, `MQTT_PORT`, `TZ=Europe/Amsterdam`, and `STRATEGY_V2_PRIMARY=false`.
4. DB migration in `migrate/migrations/` (same Alembic/raw-SQL pattern used in the repo) adding a `day_plans` table:

```sql
create table day_plans (
    id serial primary key,
    plan_date date not null unique,
    solar_mode text not null,
    forecast_ghi_kwh_m2 real,
    effective_soc_floor int not null,
    effective_soc_ceiling int not null,
    grid_charge_windows jsonb,
    price_discharge_windows jsonb,
    planned_soc_at_sunset int,
    valid_until timestamptz not null,
    reason text,
    created_at timestamptz not null default now()
);
```

5. The `pytest` test suite under `tests/strategy/v2/`.
6. Updated `minyad-agent/prompts.py` system prompt to include:
   - The agent is aware of the active `DayPlan` (published on `minyad/strategy/active`).
   - It should read `effective_soc_floor`, `effective_soc_ceiling`, `in_price_discharge_window`, `in_grid_charge_window` before making decisions.
   - During price discharge windows, prefer discharge bias even if grid is momentarily balanced.
   - During grid charge windows, do not override the forced charge unless SoC is already at ceiling.
   - Mention when price arbitrage is the reason for a setpoint change in `log_decision`.
