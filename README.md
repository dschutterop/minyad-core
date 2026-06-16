# Minyad

Minyad is een home virtual powerplant voor een woning in Nederland. De v1-focus is een harde zero-export strategie en maximale zelfconsumptie met:

- Enphase IQ7/IQ7A via lokale Envoy `/api/v1/production` met digest-authenticatie en curtailment via de lokale IQ Gateway API met bearer-token.
- GoodWe GW5048D-ES met Dyness DL5.0C via lokale GoodWe API, met Modbus/RS485 fallback achter dezelfde `GoodWeClient` interface.
- DSMR P1-reader MQTT-telegrams of JSON-berichten.
- PostgreSQL als service-communicatielaag en opslag.
- Open-Meteo solar forecast zonder API-key.
- Een minimaal custom dashboard op standaard hostpoort `18080`.

## Architectuur

| Service | Verantwoordelijkheid |
| --- | --- |
| `minyad-ingest` | Start de DSMR MQTT consumer, Enphase poller en GoodWe poller in aparte workerprocessen. |
| `minyad-control` | Draait de zero-export/self-consumption control loop. |
| `minyad-forecast` | Haalt Open-Meteo GHI/DNI/cloud-cover op en schrijft `solar_forecast`. |
| `minyad-api` | FastAPI status-, settings- en control-log endpoints. |
| `minyad-dashboard` | Static HTML/JS dashboard. |

Alle timestamps worden UTC opgeslagen. Het dashboard toont lokale tijden met `Europe/Amsterdam`.

## Eerste installatie

1. Kopieer de configuratie:

   ```bash
   cp .env.example .env
   ```

2. Vul minimaal deze waarden in `.env` in:

   - `MQTT_HOST`, `MQTT_PORT`, `DSMR_MQTT_TOPIC`
   - `ENVOY_HOST`, `ENVOY_USERNAME`, `ENVOY_PASSWORD`
   - `ENPHASE_GATEWAY_IP`, `ENPHASE_TOKEN`
   - `GOODWE_HOST`
   - `MINYAD_BIND_IP` (het host-IP-adres waarop Docker alle gepubliceerde services moet binden)
   - `MINYAD_LATITUDE`, `MINYAD_LONGITUDE`, `PV_PEAK_KW`

3. Start de stack:

   ```bash
   docker compose up --build
   ```

4. Open:

   - Dashboard: `http://<MINYAD_BIND_IP>:<MINYAD_DASHBOARD_HOST_PORT>` (standaard `18080`)
   - API: `http://<MINYAD_BIND_IP>:<MINYAD_API_HOST_PORT>/api/status` (standaard `18000`)

## Service-bindings

Alle gepubliceerde Docker-poorten binden expliciet op `MINYAD_BIND_IP` uit `.env`. De host-poorten zijn instelbaar zodat Minyad niet botst met andere stacks op dezelfde machine:

| Service | Host-poort | Container-poort |
| --- | ---: | ---: |
| `postgres` | `MINYAD_POSTGRES_HOST_PORT` (`15432`) | `5432` |
| `minyad-api` | `MINYAD_API_HOST_PORT` (`18000`) | `8000` |
| `minyad-dashboard` | `MINYAD_DASHBOARD_HOST_PORT` (`18080`) | `80` |

Hierdoor publiceert Docker deze services niet op `0.0.0.0`. Zet `MINYAD_BIND_IP` op het host-interfaceadres dat je wilt gebruiken voordat je `docker compose up` draait. Pas `MINYAD_POSTGRES_HOST_PORT`, `MINYAD_API_HOST_PORT` of `MINYAD_DASHBOARD_HOST_PORT` aan als een standaardpoort al bezet is. Het dashboard proxyt `/api/` intern naar `minyad-api`, zodat het dashboard blijft werken wanneer je de API-hostpoort wijzigt. De Compose-poorten gebruiken bewust de korte notatie `${MINYAD_BIND_IP}:hostpoort:containerpoort`, zodat oudere Docker Compose-versies het bind-adres ook correct doorgeven aan Docker.

## Database en runtime settings

Alembic maakt de tabellen aan en seedt de standaardinstellingen. Runtime settings staan in `settings` en worden door de control loop elke cyclus opnieuw gelezen, dus wijzigen kan zonder restart.

Belangrijke defaults:

| Key | Default | Betekenis |
| --- | ---: | --- |
| `export_tolerance_w` | `50` | Maximaal toegestane export in Watt. |
| `min_soc_pct` | `15` | Minimale SOC voor ontladen. |
| `max_soc_pct` | `95` | Maximale SOC voor laden. |
| `charge_threshold_w` | `200` | Minimale solar-overschot drempel. |
| `control_loop_interval_s` | `10` | Control-loop interval. |
| `forecast_lookahead_h` | `36` | Forecast horizon. |
| `strategy` | `zero_export_self_consumption` | Voorbereid op latere strategieën zoals prijsoptimalisatie. |

Voorbeeld instelling aanpassen:

```bash
curl -X PUT http://<MINYAD_BIND_IP>:${MINYAD_API_HOST_PORT:-18000}/api/settings/export_tolerance_w \
  -H 'content-type: application/json' \
  -d '{"value":"25"}'
```

## Enphase curtailment

De Enphase-productiemeting blijft via de Envoy `/api/v1/production` endpoint lopen. Curtailment gebruikt de lokale IQ Gateway API over HTTPS met een bearer-token. Minyad leest de JWT rechtstreeks uit `ENPHASE_TOKEN` in `.env`. Token-vernieuwing hoort buiten deze service te gebeuren; werk de `.env`-waarde bij wanneer het externe vernieuwingsproces een nieuw token oplevert.

De huidige actuator is een harde productie-toggle op `PUT /ivp/mod/603980032/mode/power_status` met `expectedEnergyFlag=0` voor uit en `expectedEnergyFlag=1` voor aan. De status wordt gecontroleerd via `GET /ivp/mod/603980032/mode/power_status` en `powerForcedOff`. Omdat de gateway en microinverters 15–30 minuten latency kunnen hebben, bewaakt `ENPHASE_SWITCH_HYSTERESIS_S` standaard minimaal 600 seconden tussen tegengestelde schakelingen.

`CURTAILMENT_GRANULAR_ENABLED=false` houdt deze harde toggle actief. De control loop roept bewust alleen `set_production_limit(percent)` aan, zodat de toekomstige DRM-route voor procentuele fijnregeling onder dezelfde interface geactiveerd kan worden zonder control-loop refactor.

## GoodWe control

De code gebruikt primair de community `goodwe` Python library voor lokale runtime-data. De control-methodes (`set_charge_power`, `set_discharge_power`, `set_idle`) zitten bewust in `minyad.integrations.goodwe.LocalGoodWeClient`, omdat write-registers en firmwaremogelijkheden per installatie kunnen verschillen. Voor echte actuator-control moet deze adapter worden ingevuld met de gevalideerde registers of commando's voor de GW5048D-ES firmware. De Modbus fallback is als aparte klasse aanwezig zodat dezelfde control loop ongewijzigd blijft.

## DSMR MQTT payloads

De consumer ondersteunt drie vormen:

- Losse numerieke MQTT-topicwaarden, bijvoorbeeld `dsmr/reading/electricity_currently_delivered` of `dsmr/reading/electricity_currently_returned`, waarbij de topicnaam bepaalt of de waarde import of export is.
- Raw DSMR telegram met OBIS-codes `1-0:1.7.0`, `1-0:2.7.0`, `1-0:1.8.1/2`, `1-0:2.8.1/2`.
- JSON met bijvoorbeeld `import_w`, `export_w`, `import_kwh_t1`, `import_kwh_t2`, `export_kwh_t1`, `export_kwh_t2`. De DSMR-parser accepteert ook gangbare P1/Home Assistant-varianten zoals `electricity_currently_delivered`, `electricity_currently_returned`, geneste `{ "value": ..., "unit": "W" }`-velden en `consumption.power`/`production.power`.

## Ontwikkelen

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt ruff pytest
ruff check .
python -m compileall minyad migrations
```
