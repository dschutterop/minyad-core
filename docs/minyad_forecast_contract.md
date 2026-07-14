# Minyad forecast contract

**Status:** authoritative, implemented.
**Endpoint:** `GET /api/v1/surplus` (and its legacy alias `GET /api/surplus` — same handler).
**No separate forecast endpoint exists or should be added.** This document describes the
`minyad_forecast` extension to that one response, plus the freshness rules and a placeholder
design for a future reservation contract.

## Ownership boundary

- **Minyad owns:** household energy forecasting, battery dispatch and battery targets, the
  authoritative battery SoC trajectory, and the uncertainty model behind the P50/P25 forecasts.
  All of that is produced by Minyad's own rolling LP planner (private, not part of this
  repository) and surfaced here.
- Minyad has no appliance-switching logic and must never gain any — `minyad_forecast` is a
  read-only forecast/budget signal, not a command channel. Nothing in this response starts or
  stops anything.
- **A downstream consumer's job with this response:** subtract its own current-tick realtime
  device reservations from `surplus_p50_w`/`surplus_p25_w` itself. Minyad's numbers already
  exclude fixed household base load and Minyad's own planned battery charge/discharge; they do
  **not** know about any consumer's own reservations (see
  [Known-load and reservation semantics](#known-load-and-reservation-semantics)).

## Response shape

Existing fields (`api_version`, `timestamp`, `surplus_w`, `gross_surplus_w`, `has_surplus`,
`has_gross_surplus`, `grid`, `solar`, the pre-existing `battery.*` fields, `minyad.*`) are
unchanged — see `build_surplus_payload()` in `api/main.py`. Two things are added:

### `battery` additions (LP metadata + trajectory)

| Field | Meaning |
|---|---|
| `battery.capacity_kwh` | Configured usable battery capacity (`battery.capacity_wh` / 1000), as used by the LP. |
| `battery.charge_efficiency` | Round-trip one-way efficiency the LP assumes (`strategy3.one_way_efficiency`). |
| `battery.max_charge_w` | Effective max charge power the LP respects (`min(max_charge_w, max_charge_a × nominal_v)`). |
| `battery.max_discharge_w` | Configured max discharge power. |
| `battery.soc_trajectory_pct` | **Compatibility field.** Same 96-value array as `minyad_forecast.soc_pct` below. Downstream consumers may read this field for slot-level SoC decisions; it is populated alongside `minyad_forecast.soc_pct` for as long as that's needed. Present only when the forecast is valid — never a copy of the current SoC. |

These are the real configured values, not synthetic defaults substituted for missing config —
if a value isn't configured, the LP's own default is used (same default the planner itself
uses), never a value invented for this endpoint.

### `minyad_forecast` (new top-level key)

```json
{
  "minyad_forecast": {
    "source": "minyad_lp",
    "quality": "authoritative_lp",
    "generated_at": "2026-07-14T10:00:05Z",
    "starts_at": "2026-07-14T10:00:00Z",
    "slot_duration_s": 900,
    "slot_count": 96,
    "surplus_p50_w": [850, 900, 1200, "... 96 values"],
    "surplus_p25_w": [650, 700, 850, "... 96 values"],
    "pv_p25_w": [1800, 1900, 2100, "... 96 values"],
    "soc_pct": [68.0, 68.2, 68.5, "... 96 values"],
    "scenario_count": 100,
    "model_version": "strategy-v3-lp",
    "validation": { "status": "valid", "reason": null, "age_s": 5, "scenario_count": 100 }
  }
}
```

**Slot contract:**

- Exactly 96 slots, each 15 minutes (`slot_duration_s: 900`).
- `starts_at` is UTC, ISO-8601, aligned to the current 15-minute boundary; array index `0`
  corresponds to `starts_at`, index `1` to `starts_at + 15min`, etc.
- All timestamps carry an explicit UTC offset (`+00:00`/`Z`) regardless of the process's own
  timezone — Minyad never relies on the container/host timezone for these (see
  `test_surplus_payload_forecast_timestamps_are_explicit_utc_regardless_of_process_tz`).
- All numeric values are finite. All power values are watts. SoC values are 0–100 percent.

**Field meaning:**

- `surplus_p50_w[t]` / `surplus_p25_w[t]` — available incremental household power for
  discretionary loads at slot `t`, **after** fixed household base load and Minyad's planned
  battery charge/discharge, clamped to `≥ 0`. They exclude any downstream consumer's own
  realtime reservations, imaginary appliance loads, and double-counted battery power.
  `surplus_p25_w ≤ surplus_p50_w` always (see
  [Quantile/scenario method](#quantilescenario-method)).
- `pv_p25_w[t]` — the 25th-percentile **PV generation** forecast alone: no household load,
  battery charging, appliance consumption, or downstream reservations folded in. Intended for a
  consumer's own battery-first recharge guard. Computed from the PV scenario distribution
  independently of the surplus numbers — it is not derived from `surplus_p25_w`.
- `soc_pct[t]` — Minyad's planned SoC trajectory at the *start* of slot `t` (so `soc_pct[0]` is
  the LP's own `soc_start_pct`, matching "index 0 = now"), straight from the LP's real solution.
  Never a synthetic/simulated trajectory and never a flat copy of the current SoC.
- `scenario_count` — how many Monte Carlo scenarios backed the percentiles for this response.
- `model_version` — identifies the forecasting model/strategy version, for downstream logging
  and any future forecast-accuracy comparison.

## Freshness and failure behavior

A forecast is only published as `"quality": "authoritative_lp"` when **all** of the following
hold (checked by Minyad's private forecast-building logic, not part of this repository):

1. An LP plan exists and completed successfully (`solver_status == "Optimal"`, not `FALLBACK`).
2. The plan has a `generated_at` and is not stale (age ≤ `PLAN_STALE_MINUTES`, currently 30 min).
3. The plan has exactly 96 slots of 900 s each.
4. `starts_at` is UTC and aligned to a 15-minute boundary.
5. `surplus_p50_w`, `surplus_p25_w`, `pv_p25_w`, `soc_pct` all have exactly 96 finite values.
6. All `soc_pct` values are within `[0, 100]`.
7. `surplus_p25_w[t] ≤ surplus_p50_w[t]` for every slot.
8. A usable PV scenario distribution exists for every slot's cloud-cover class.

If **any** check fails, the endpoint still returns 200 with all the live fields intact
(`surplus_w`, `battery.soc`, `solar.power_w`, etc. are computed independently of the forecast
and are never affected by a forecast failure) — `minyad_forecast` becomes:

```json
{
  "minyad_forecast": {
    "source": "minyad_lp",
    "quality": "unavailable",
    "validation": { "status": "invalid", "reason": "stale_plan", "age_s": 5412.0, "scenario_count": null }
  }
}
```

`battery.soc_trajectory_pct` is omitted entirely in this case — never a partial array, never a
copied current SoC presented as if it were a trajectory. The failure is logged at `WARNING`
with the model version and timestamp (`api/main.py::build_surplus_payload`).

Minyad Core itself (this repository, standalone) always reports `minyad_forecast` as
`"quality": "unavailable"` with `"reason": "strategy_module_unavailable"`, since the forecast
planner that produces `"authoritative_lp"` results lives outside this repository — see
`_strategy_module_unavailable_outcome()` in `api/main.py`.

`validation.reason` values currently in use:

| Reason | Meaning |
|---|---|
| `missing_plan` | No LP plan exists yet. |
| `stale_plan` | Latest usable plan's `generated_at` is older than the staleness window. |
| `solver_fallback` | The LP did not reach `Optimal` (solver failure/timeout produced a flat-hold `FALLBACK` plan instead). |
| `unexpected_slot_count` / `unexpected_slot_duration` | The plan's horizon doesn't match the 96×900s contract. |
| `unaligned_start` / `start_not_utc` | `starts_at` isn't a UTC, 15-minute-aligned timestamp. |
| `invalid_slot_data` | The persisted plan payload is malformed. |
| `insufficient_scenario_data` | A slot's cloud-cover class has no calibrated PV ratio history yet (or a slot has no cloud-cover reading at all) — see below. |
| `array_length_mismatch` / `non_finite_values` / `negative_power` / `soc_out_of_bounds` / `p25_exceeds_p50` | Structural/numeric validation of the built candidate failed — should not happen given the checks above, kept as a defense-in-depth guard. |
| `strategy_module_unavailable` | This deployment doesn't have Minyad's private forecast-building module available (the normal, expected state for a standalone Minyad Core checkout). |

No calibration/accuracy claim is made about `surplus_p25_w`: it is a coherent 25th-percentile
statistic from real scenario sampling, but it is **not** described as "calibrated" anywhere in
this contract, and shouldn't be represented that way downstream, until Minyad has run a
reliability evaluation of its forecasts against observed outcomes (not yet implemented).

## Quantile/scenario method

Minyad does not multiply the point forecast by a fixed discount to get P25 — that would not be
a real uncertainty model. Instead (private implementation, not part of this repository):

1. **Historical calibration**, run daily by the rolling planner: for each past PV measurement,
   compute the ratio of actual to predicted PV output, bucketed by that moment's cloud-cover
   class (`clear` / `partly` / `cloudy`). A class needs ≥ 14 days × 4 samples/day of history
   before it's used at all — below that, the class is simply omitted (never a fabricated
   distribution). The result is a compact empirical quantile grid per class (9 points: P1, P5,
   P10, P25, P50, P75, P90, P95, P99), persisted to `pv_uncertainty_bands`.
2. **Scenario generation**: for each of the 96 slots, using that slot's own cloud-cover class,
   draw `scenario_count` (default 100) independent samples from the class's empirical
   distribution via inverse-CDF interpolation over the quantile grid, and multiply each by the
   slot's point PV forecast to get a PV scenario.
3. **Reduction to the contract's fields**, per slot:
   - `surplus_w` per scenario = `max(0, pv_scenario_w − load_forecast_w − charge_w)`, where
     `load_forecast_w` and `charge_w` are Minyad's own fixed household-load forecast and the
     LP's own planned battery charge for that slot (held constant across scenarios — the
     battery dispatch itself is not re-optimized per scenario).
   - `surplus_p50_w` / `surplus_p25_w` = the empirical 50th/25th percentile of that slot's
     `scenario_count` surplus samples.
   - `pv_p25_w` = the empirical 25th percentile of that slot's PV scenario samples alone.

Because P25 and P50 both come from percentiles of the same sampled distribution, `P25 ≤ P50`
holds by construction, not by a post-hoc clamp.

**Known scope limitation:** each slot draws its scenarios independently from that slot's own
marginal cloud-class distribution. This is *not* a temporally-correlated weather-path model —
scenario 7 at slot 3 and scenario 7 at slot 4 do not represent "the same coherent future
day." That's sufficient for the per-slot marginal P50/P25 this contract asks for, but a
consumer must not treat scenarios as coherent trajectories across slots.

## SoC trajectory

`battery.soc_trajectory_pct` and `minyad_forecast.soc_pct` are the same array, straight from
the LP's own solved `soc_target_pct` per slot, never a synthetic simulation and never a flat
copy of the current SoC. Both fields are populated together during the compatibility period
noted above; once a consumer reads `minyad_forecast.soc_pct` directly, `battery.soc_trajectory_pct`
can be retired.

## Known-load and reservation semantics

Minyad's `load_forecast_w` includes all known fixed household loads from its own consumption
profile. It must **not** include a downstream consumer's own appliance jobs unless there's an
explicit, acknowledged reservation — otherwise the same load gets counted twice (once in
Minyad's forecast, once in whatever the consumer adds on top). **No reservation contract exists
in Minyad today**, and none of the `minyad_forecast` fields carry any reservation/device/
acknowledgement data — this is deliberate; an unacknowledged reservation must never be silently
treated as accepted.

### Future reservation contract (design placeholder, not implemented)

If/when a downstream consumer needs to tell Minyad about a planned device dispatch so Minyad
can fold it into `load_forecast_w` without double-counting, that would need its own explicit
acknowledgement-based contract — sketched here for future design, deliberately out of scope for
this change:

| Field | Purpose |
|---|---|
| `reservation_id` | Unique ID for the reservation. |
| `owner` | Which system created it. |
| `device_id` / `job_id` | What's being dispatched. |
| `start_time` / `end_time` | Reservation window. |
| `expected_power_curve` | The load the consumer expects to add, per slot. |
| `acknowledgement_status` | Whether Minyad has accepted it into its own forecast — an unacknowledged reservation must not be treated as accepted. |
| `expiration_time` | When an unacknowledged/unrenewed reservation lapses. |
| `rejection_reason` | Why Minyad declined it, if it did. |

## Testing

- `tests/test_api_status_payloads.py` — `build_surplus_payload()` backward compatibility
  (no `minyad_forecast` key when `attempt_forecast` isn't set), live-field survival on forecast
  failure, explicit-UTC timestamps regardless of process timezone (skipped in a standalone
  checkout — see `strategy_module_unavailable` above).
- `tests/test_api_surplus_integration.py` — the full `/api/v1/surplus` route, including a real
  HTTP round trip via `TestClient` (same skip condition).
