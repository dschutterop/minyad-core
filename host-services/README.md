
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
