# Minyad

Minyad is een home virtual powerplant voor een woning in Nederland. De v1-focus is een harde zero-export strategie en maximale zelfconsumptie met:

- Enphase IQ7/IQ7A via lokale Envoy `/api/v1/production` met digest-authenticatie.
- GoodWe GW5048D-ES met Dyness DL5.0C via lokale GoodWe API, met Modbus/RS485 fallback achter dezelfde `GoodWeClient` interface.
- DSMR P1-reader MQTT-telegrams of JSON-berichten.
- PostgreSQL als service-communicatielaag en opslag.
- Open-Meteo solar forecast zonder API-key.
- Een minimaal custom dashboard op poort `8080`.

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
   - `GOODWE_HOST`
   - `MINYAD_BIND_IP` (het host-IP-adres waarop Docker alle gepubliceerde services moet binden)
   - `MINYAD_LATITUDE`, `MINYAD_LONGITUDE`, `PV_PEAK_KW`

3. Start de stack:

   ```bash
   docker compose up --build
   ```

4. Open:

   - Dashboard: `http://<MINYAD_BIND_IP>:8080`
   - API: `http://<MINYAD_BIND_IP>:8000/api/status`

## Service-bindings

Alle gepubliceerde Docker-poorten binden expliciet op `MINYAD_BIND_IP` uit `.env`:

| Service | Host-poort | Container-poort |
| --- | ---: | ---: |
| `postgres` | `5432` | `5432` |
| `minyad-api` | `8000` | `8000` |
| `minyad-dashboard` | `8080` | `80` |

Hierdoor publiceert Docker deze services niet op `0.0.0.0`. Zet `MINYAD_BIND_IP` op het host-interfaceadres dat je wilt gebruiken voordat je `docker compose up` draait. De Compose-poorten gebruiken bewust de korte notatie `${MINYAD_BIND_IP}:hostpoort:containerpoort`, zodat oudere Docker Compose-versies het bind-adres ook correct doorgeven aan Docker.

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
curl -X PUT http://<MINYAD_BIND_IP>:8000/api/settings/export_tolerance_w \
  -H 'content-type: application/json' \
  -d '{"value":"25"}'
```

## GoodWe control

De code gebruikt primair de community `goodwe` Python library voor lokale runtime-data. De control-methodes (`set_charge_power`, `set_discharge_power`, `set_idle`) zitten bewust in `minyad.integrations.goodwe.LocalGoodWeClient`, omdat write-registers en firmwaremogelijkheden per installatie kunnen verschillen. Voor echte actuator-control moet deze adapter worden ingevuld met de gevalideerde registers of commando's voor de GW5048D-ES firmware. De Modbus fallback is als aparte klasse aanwezig zodat dezelfde control loop ongewijzigd blijft.

## DSMR MQTT payloads

De consumer ondersteunt twee vormen:

- Raw DSMR telegram met OBIS-codes `1-0:1.7.0`, `1-0:2.7.0`, `1-0:1.8.1/2`, `1-0:2.8.1/2`.
- JSON met bijvoorbeeld `import_w`, `export_w`, `import_kwh_t1`, `import_kwh_t2`, `export_kwh_t1`, `export_kwh_t2`.

## Ontwikkelen

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt ruff pytest
ruff check .
python -m compileall minyad migrations
```
