# Minyad

Minyad is een home virtual-power-plant controller voor een hybride thuisinstallatie
met batterij, PV, DSMR/P1-meter en dynamische marktinformatie. De stack combineert
MQTT-telemetrie, een FastAPI-backend, webfrontends, batterijstrategieen, forecast-
en prijscollectie, host-side hardware bridges en Prometheus-monitoring.

De applicatie draait primair via Docker Compose. Hardwarekoppelingen die direct met
lokale apparatuur praten, zoals GoodWe, DSMR en Enphase, staan onder
`host-services/` en kunnen als systemd-units naast de containers draaien.

## Inhoud

- `api/` - FastAPI backend, dashboarddata, settings, health en Dryad endpoints.
- `frontend/` - desktop webinterface op poort `8084`.
- `mobile-frontend/` - compacte mobiele webinterface op poort `8085`.
- `minyad/strategy/v2/` en `minyad/strategy/v3/` - batterijstrategieen.
- `control/` - reactieve control-loop en MQTT-aansturing.
- `ingestion/` - sensor-ingestion, momenteel DSMR.
- `forecast/` - Open-Meteo/PV forecast publisher.
- `minyad-trade/` - day-ahead prijscollectie via ENTSO-E.
- `minyad-agent/` - operator-agent met API-tools, standaard in dry-run.
- `host-services/` - GoodWe, DSMR en Enphase bridges voor systemd.
- `monitoring/`, `prometheus/` en `docs/monitoring.md` - metrics, alerts en scrape-config.
- `migrate/` - Alembic database-migraties.
- `tests/` - pytest-suite.

## Vereisten

- Python 3.12 voor lokale ontwikkeling en tests.
- Docker en Docker Compose voor de applicatiestack.
- Een `.env` gebaseerd op `.env.example`.
- Voor productie: toegang tot GHCR-images of lokale builds, plus hostconfiguratie
  voor de hardware bridges.

## Installatie

Maak eerst een lokale configuratie:

```bash
cp .env.example .env
```

Vervang daarna minimaal de secrets en lokale adressen in `.env`:

- `DB_URL`
- `MQTT_USER` en `MQTT_PASS`
- `MINYAD_API_SECRET`
- `ENCRYPTION_KEY`
- `MINYAD_METRICS_BIND_IP`
- `MINYAD_TLS_IP_SANS`
- `ENTSOE_API_KEY` wanneer `minyad-trade` prijzen moet ophalen

Start de lokale Docker-stack met builds uit de checkout:

```bash
docker compose up -d --build
```

Controleer de status:

```bash
docker compose ps
docker compose logs -f minyad-api
```

Belangrijke lokale endpoints:

- Frontend: `http://localhost:8084`
- Mobiele frontend: `http://localhost:8085`
- API: `https://localhost:8002`
- MQTT hostpoort: `${MINYAD_MQTT_BIND_IP}:1884`

De interne API gebruikt een self-signed certificaat dat door
`minyad-tls-init` in het Compose-volume `minyad-internal-tls` wordt gemaakt.

## Productie draaien

Voor productie gebruikt `docker-compose.prod.yml` gepubliceerde images in plaats
van lokale builds:

```bash
MINYAD_IMAGE_TAG=latest docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
MINYAD_IMAGE_TAG=latest docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
```

Standaard image-prefix:

```text
ghcr.io/dschutterop/minyad
```

Overschrijf dit met `MINYAD_IMAGE_PREFIX` wanneer je eigen images gebruikt.

De GitHub Actions workflows bouwen images, draaien tests, voeren optioneel Trivy
scans uit en deployen vanaf `main` naar de self-hosted runner. De productieomgeving
verwacht onder andere:

- `DEPLOY_PATH`
- `MINYAD_METRICS_BIND_IP`
- optioneel `MINYAD_PROMETHEUS_SOURCE`
- optioneel `HOST_SERVICE_UNITS`

## Configuratie

De belangrijkste configuratie staat in `.env` en wordt door Compose in vrijwel
alle services geladen.

| Variabele | Doel |
|---|---|
| `DB_URL` | PostgreSQL connectiestring voor app en migraties. |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS` | Interne MQTT brokerconfiguratie. |
| `MINYAD_API_SECRET` | API key voor beschermde endpoints en frontends. |
| `MINYAD_CORS_ORIGINS` | Toegestane browser-origins voor de API. |
| `ENCRYPTION_KEY` | Fernet key voor versleutelde waarden. |
| `MINYAD_CONTAINER_BIND_ADDR` | Bind-adres voor frontend containers. |
| `MINYAD_MQTT_BIND_IP` | Host-IP waarop Mosquitto wordt gepubliceerd. |
| `MINYAD_TLS_IP_SANS` | IP-SANs voor het interne TLS-certificaat. |
| `MINYAD_HOST_DNS` | Hostnaam in het interne TLS-certificaat. |
| `MINYAD_METRICS_BIND_IP` | Interface/IP voor gepubliceerde metrics. |
| `FORECAST_LATITUDE`, `FORECAST_LONGITUDE`, `SOLAR_PEAK_W` | PV forecast parameters. |
| `STRATEGY_V2_PRIMARY` | Laat v2 primary control leveren wanneer `true`. |
| `STRATEGY3_SHADOW_MODE` | Laat v3 meedraaien zonder primaire sturing wanneer `true`. |
| `ENTSOE_API_KEY` | API key voor day-ahead prijzen. |
| `SONAR_HOST`, `SONAR_TOKEN` | SonarQube configuratie voor CI. |

Veel runtime-instellingen zijn daarnaast via de API en frontend instelbaar en
worden in de database en/of retained MQTT topics vastgelegd, bijvoorbeeld
batterijlimieten, strategieparameters en trade settings.

## Host services

De host services praten met apparatuur of externe lokale brokers en publiceren
naar Minyad MQTT:

- `goodwe_bridge.py` - GoodWe API-telemetrie en Modbus charge/discharge limit actuator.
- `dsmr_bridge.py` - DSMR/P1 MQTT-bron naar Minyad grid topics.
- `enphase_bridge.py` - Enphase Envoy productie- en invertertelemetrie.
- `enphase_token_refresh.py` - periodieke Enphase token-refresh.
- `minyad-explain` - read-only CLI om batterij-setpointbeslissingen uit te leggen.

Installeer host dependencies in een aparte virtualenv:

```bash
python3.12 -m venv host-services/venv
host-services/venv/bin/python -m pip install --upgrade pip
host-services/venv/bin/python -m pip install -r host-services/requirements.txt
```

Zie `host-services/README.md` voor details over `minyad-explain`, Dryad,
GoodWe Modbus-limit mode en charge target ceilings.

## Ontwikkeling

Installeer testdependencies in een virtualenv buiten de repo of in de bestaande
`.venv`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r minyad-trade/requirements.txt -r host-services/requirements.txt pytest pytest-asyncio pytest-cov ruff
```

Gerichte tests:

```bash
PYTHONPATH=. pytest tests/test_api_auth.py
PYTHONPATH=. pytest tests/strategy/v3/test_planner.py
PYTHONPATH=. pytest tests/test_api_auth.py::test_missing_api_key_rejected
```

Volledige suite:

```bash
PYTHONPATH=. pytest
```

CI-equivalent met coverage:

```bash
PYTHONPATH=. pytest --cov=. --cov-report=xml
```

Ruff-check die CI gebruikt:

```bash
python -m ruff check --preview --select FAST002,RUF029,F841,SIM102 .
```

Compose-config valideren zonder bestaande `.env` te overschrijven:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
```

Wanneer je nog geen `.env` hebt:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
```

## Maintenance

Dagelijkse checks:

```bash
docker compose ps
docker compose logs --tail=200 minyad-api
docker compose logs --tail=200 minyad-control
docker compose logs --tail=200 minyad-strategy-v3
```

Database-migraties draaien automatisch via `minyad-migrate` voordat afhankelijke
services starten. Handmatig opnieuw draaien kan met:

```bash
docker compose run --rm minyad-migrate
```

Services herstarten:

```bash
docker compose restart minyad-api minyad-frontend minyad-control minyad-strategy-v3
```

Productie-images verversen:

```bash
MINYAD_IMAGE_TAG=<tag-of-sha> docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
MINYAD_IMAGE_TAG=<tag-of-sha> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
docker image prune -f
```

Host services na een deploy herstarten:

```bash
sudo systemctl daemon-reload
sudo systemctl restart dsmr_bridge.service goodwe_bridge.service enphase_bridge.service enphase_token_refresh.timer
```

Metrics worden gepubliceerd op poorten `9101` t/m `9111`. Zie
`docs/monitoring.md` en `prometheus/minyad-scrape.yml` voor scrape targets,
alerts en recording rules.

## Strategie en sign conventions

De actuele strategie-specificatie staat in `strategy_v3.md`. De belangrijkste
power-conventies:

- `setpoint_w`: positief is laden, negatief is ontladen.
- `net_grid_w`: positief is import, negatief is export.
- `battery_power_w`: positief is batterijontlading, negatief is laden.

`charging_strategy.md` is alleen nog historisch; `strategy_v3.md` is leidend.

## Nuttige documentatie

- `strategy_v3.md` - autoritatieve specificatie voor de predictive LP-planner.
- `forecast_strategy.md` - analyse van dashboardforecast versus strategy v3.
- `docs/monitoring.md` - metrics, poorten en alerting.
- `docs/prometheus-handoff.md` - Prometheus overdracht/configuratie.
- `host-services/README.md` - host bridge en uitleghulpmiddelen.

## Veiligheid

- Commit nooit echte `.env`-waarden, tokens, coverage-output of lokale caches.
- Bind metrics en MQTT in productie aan interne/VPN-interfaces.
- Gebruik `GOODWE_DRY_RUN=true` bij host-side GoodWe-tests zonder writes.
- Controleer bij wijzigingen aan batterijlimieten altijd inverter-, bekabelings-
  en BMS-grenzen voordat je hogere waarden toepast.
