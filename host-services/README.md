
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

## GoodWe bridge dual-protocol mode

`goodwe_bridge.py` now composes two GoodWe clients instead of choosing a single exclusive protocol.
Modbus (`GOODWE_MODBUS_ENABLED`, default `true`) is the source of truth for RS485-reliable control fields: battery voltage (register 35180), battery power (35182), work mode (35187), and actuator writes to charge/discharge limit registers 45565/45566.
The GoodWe API (`GOODWE_API_ENABLED`, default enabled when `GOODWE_API_HOST` is configured) is supplemental telemetry for fields that are not reliable over RS485, such as SOC, SOH, and battery temperature. API outages are logged but do not stop the control loop when Modbus remains available. Use `GOODWE_DRY_RUN=true` to suppress Modbus writes during tests.
