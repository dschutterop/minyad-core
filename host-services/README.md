
## minyad-explain

`minyad-explain` is a standalone, read-only PostgreSQL CLI for explaining each
battery setpoint change without manually digging through database rows or logs.
It is intended to run on the host next to `goodwe_bridge.py` and
`dsmr_bridge.py`, using the same environment style (`DB_URL`/`DATABASE_URL`) as your systemd unit
or `.env` file. The CLI automatically loads `/opt/minyad/.env` and
`/opt/minyad/host-services/.env` if present. The `./minyad-explain`
launcher creates/updates a local `.venv-minyad-explain` virtualenv from
`host-services/minyad-explain.requirements.txt` before executing the Python CLI,
so host packages do not need to be installed globally. Set
`MINYAD_EXPLAIN_REQUIREMENTS` if your deployment wants to pin a different
requirements file.

```bash
cd /opt/minyad/host-services
./minyad-explain --range day
./minyad-explain --range week --summary
./minyad-explain --range 2026-06-19 --verbose --format table
./minyad-explain --range 14:00-16:00 --format json
./minyad-explain --why
```

Supported ranges are `day`, `week`, `month`, an explicit `YYYY-MM-DD`, or a
same-day local-time `HH:MM-HH:MM` window. `--why` prints the most recent
setpoint decision with a factor breakdown and the live/default thresholds read
from the actual control implementation (`control/main.py`,
`control/hysteresis.py`, and `minyad/strategy/charge_controller.py`).

## Dryad read-only aggregation API

Dryad can poll the existing Minyad API service without any extra systemd unit:

```bash
curl http://pknpapp001:8081/api/v1/dryad
curl "http://pknpapp001:8081/api/v1/dryad/history?days=30"
```

`GET /api/v1/dryad` returns one JSON object with:

* `ts` - ISO8601 timestamp for the aggregation run.
* `autarky` - rolling 60 minute self-sufficiency, `1 - P1 import / total consumption`.
* `trajectory_deviation` - absolute current SoC versus LP planned SoC, normalized by `strategy3.traj_band_pct`.
* `dispatch_hitrate` - acknowledged versus planned Strategy/Kairos/Vesper dispatches over the last 24 hours; no planned dispatches returns `1.0`.
* `import_price_penalty` - weighted penalty for import during hours at least `dryad.import_price_penalty_pct` percent above the cheapest coming six-hour price; default threshold is 30 percent.
* `soc` - current GoodWe/Dyness SoC as a 0.0-1.0 fraction.
* `sources` - per field source name, data age in seconds, and stale flag. Stale inputs make only the affected field `null`.

`GET /api/v1/dryad/history?days=N` returns up to 400 local-day solar generation sums from the existing Enphase-backed `power_curve_rollups` history.

## GoodWe bridge API telemetry + Modbus limit actuator mode

`goodwe_bridge.py` uses the GoodWe API as the primary telemetry source. It publishes
SOC/SOH, battery power/voltage/temperature/mode, inverter temperature, and grid power
from API runtime data when available. If the API is unavailable, telemetry is marked
degraded/unknown instead of falling back to Modbus as source of truth.

P1/DSMR grid power remains the primary decision input for import/export behavior.
Modbus over RS485 is only used as the actuator for battery charge/discharge limit
ceilings. Live tests proved only these writes are supported on this inverter:

* `45565` — battery charge limit in watts
* `45566` — battery discharge limit in watts

The tested 475xx EMS force-control registers are not available on this inverter, so
these Modbus limits are **not** active force-charge or force-discharge setpoints. A
charge limit means the maximum the inverter may use if it independently decides to
charge; a discharge limit means the maximum it may use if it independently decides to
discharge. Use `GOODWE_DRY_RUN=true` to suppress Modbus writes during tests.

Key environment variables:

```text
GOODWE_API_ENABLED=true
GOODWE_MODBUS_LIMITS_ENABLED=true
GOODWE_MODBUS_HOST=192.168.1.201
GOODWE_MODBUS_PORT=502
GOODWE_MODBUS_DEVICE_ID=247
GOODWE_DRY_RUN=false
GOODWE_LIMIT_WRITE_INTERVAL_SEC=10
GOODWE_LIMIT_MIN_CHANGE_W=150
GOODWE_DEFAULT_CHARGE_LIMIT_W=6000
GOODWE_DEFAULT_DISCHARGE_LIMIT_W=6000
GOODWE_CONSERVATIVE_CHARGE_LIMIT_W=1500
GOODWE_CONSERVATIVE_DISCHARGE_LIMIT_W=1500
```

## Charge target ceilings and slow-balance trimming

The control service logs slow-balance charge decisions before and after target
clamping. For `CHARGING`, export trimming first computes
`raw_target_power_w = previous_target_power_w + balance_adjustment_w`; it then
clamps that raw target to the effective charge cap.

Charge caps that can appear in the slow-balance log are:

* `configured_max_charge_w` — the database setting `battery.max_charge_w`. The
  schema migrations seed this to `1440`, so a target stuck at exactly `1440W`
  is normally the configured default unless the setting has been raised.
* `env_default_max_charge_power_w` — the control-service `MAX_CHARGE_POWER_W`
  fallback used only when `battery.max_charge_w` is absent.
* `battery_max_charge_a` and `battery_nominal_v` — when both settings are
  present, their product is logged as `battery_hardware_charge_cap_w` and is
  also the Modbus/API-style hardware cap.
* `api_max_charge_w` and `modbus_charge_limit_cap_w` — the control-service view
  of the API and Modbus actuator ceilings involved in the charge command path.
* `safety_min_charge_power_w` — the lower safety clamp of `0W`.

The final cap is logged as `effective_charge_cap_w`, and `clamp_reason` names
which input caused the clamp. Conceptually, the charge command path is capped as:

```text
effective_charge_cap_w = min(
    battery.max_charge_w,
    battery.max_charge_a * battery.nominal_v,
    bridge.MAX_CHARGE_A * battery.nominal_v  # when the GoodWe bridge amp cap applies
)
```

Both the control-service database settings and the host-side GoodWe bridge
environment can limit charging. The database values `battery.max_charge_a` and
`battery.nominal_v` are configurable via `/api/battery/settings` and the settings
UI. The bridge reads `MAX_CHARGE_A` as the requested amp limit and
`MAX_ALLOWED_CHARGE_A` (or `GOODWE_MAX_ALLOWED_CHARGE_A`) as the explicit safety
ceiling; it logs `bridge_max_charge_a`, `bridge_max_allowed_charge_a`, and a
clamp reason when the requested bridge current is reduced. For two supported
parallel battery packs, operators may intentionally raise both the database amp
setting and the bridge environment ceiling after verifying inverter, wiring, and
BMS limits.

For example, with the seeded defaults `battery.max_charge_w=1440`,
`battery.max_charge_a=30`, and `battery.nominal_v=48`, a slow-balance export
that computes a raw target of `1940W` will remain at `1440W` and log
`clamp_reason=battery.max_charge_w+battery.max_charge_a*battery.nominal_v`.
Raise `battery.max_charge_w` (and, if present, the amp/voltage hardware limit)
to allow upward slow-balance trimming above `1440W`.
