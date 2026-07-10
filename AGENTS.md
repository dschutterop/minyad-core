# AGENTS.md

Projectcontext voor Codex en andere agents die in deze repository werken.

## Projectprofiel

- Python 3.12 project met Docker Compose services voor Minyad.
- Applicatiecode staat onder `api/`, `control/`, `ingestion/`, `minyad/`, `minyad-agent/`, `minyad-trade/`, `frontend/`, `mobile-frontend/`, `monitoring/` en `host-services/`.
- Tests staan in `tests/` en gebruiken `pytest`.
- CI gebruikt `requirements.txt`, `minyad-trade/requirements.txt` en `host-services/requirements.txt`.

## Installatie voor lokale tests

Gebruik een virtualenv buiten de repo of de bestaande `.venv` als die al door de gebruiker is ingericht.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r minyad-trade/requirements.txt -r host-services/requirements.txt pytest pytest-asyncio pytest-cov ruff
```

## Testcommando's

Volledige test suite:

```bash
PYTHONPATH=. pytest
```

CI-equivalent met coverage:

```bash
PYTHONPATH=. pytest --cov=. --cov-report=xml
```

Gerichte tests tijdens ontwikkeling:

```bash
PYTHONPATH=. pytest tests/test_file.py
PYTHONPATH=. pytest tests/strategy/v3/test_planner.py
PYTHONPATH=. pytest tests/test_file.py::test_name
```

Compose-config validatie:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null
```

Let op: overschrijf geen bestaande `.env`. Als `.env` al bestaat, gebruik die of maak tijdelijk een aparte kopie.

## Lint

CI gebruikt Ruff met een kleine geselecteerde regelset:

```bash
python -m ruff check --preview --select FAST002,RUF029,F841,SIM102 .
```

De CI-job voert dit uit met `--fix --unsafe-fixes`. Gebruik automatische fixes alleen wanneer de wijziging expliciet bedoeld is en controleer de diff daarna zorgvuldig.

## Build en release

Docker images worden in CI gebouwd per service met de Dockerfiles in:

- `migrate/Dockerfile`
- `ingestion/Dockerfile`
- `control/Dockerfile`
- `minyad-strategy/Dockerfile`
- `deadman/Dockerfile`
- `api/Dockerfile`
- `frontend/Dockerfile`
- `mobile-frontend/Dockerfile`
- `forecast/Dockerfile`
- `minyad-agent/Dockerfile`
- `minyad-trade/Dockerfile`
- `reporting/Dockerfile`
- `monitoring/Dockerfile`

Lokale compose-start voor bestaande deployments:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
```

## Harde regels

- Houd diffs minimaal en taakgericht. Geen opportunistische refactors.
- Wijzig tests niet tenzij ze aantoonbaar fout zijn of de gevraagde gedragswijziging expliciet nieuwe/gewijzigde tests vereist.
- Voeg geen nieuwe dependencies toe zonder duidelijke noodzaak en zonder de juiste requirements-bestanden bij te werken.
- Commit geen secrets, tokens, echte `.env`-waarden, coverage-output of lokale caches.
- Respecteer bestaande gebruikerwijzigingen in de worktree. Revert geen code die je niet zelf hebt aangepast.
- Gebruik `rg` voor zoeken en lees bestaande patronen voordat je code wijzigt.
- Prefer gerichte tests voor kleine wijzigingen, maar draai de volledige suite of relevante bredere suites bij gedeelde code, API-contracten, Docker/compose wijzigingen en strategie/planner gedrag.

## Projectconventies

- Houd Python-code simpel, expliciet en standaard-library-first.
- Gebruik bestaande modules en helpers voordat je nieuwe abstracties toevoegt.
- Services lezen configuratie uit environment variables; `.env.example` documenteert lokale/production defaults.
- Containerprocessen die via Docker-poorten bereikbaar moeten zijn binden binnen de container op `0.0.0.0`; host-exposure wordt in Compose geregeld met bind-IP variabelen zoals `MINYAD_METRICS_BIND_IP`.
- Prometheus metrics gebruiken vaste poorten zoals gedocumenteerd in `docs/monitoring.md`.
- Host services onder `host-services/` hebben eigen requirements en systemd-units; behandel die los van container services.
- Docker images draaien waar mogelijk als non-root gebruiker `1000:1000`.
- MQTT-code gebruikt `paho-mqtt` 2.x callback APIs; volg bestaande callback signatures.
- Voor FastAPI/uvicorn services: behoud healthchecks, TLS-volume mounts en interne service-URL patronen.

## Wanneer je klaar bent

- Toon welke bestanden gewijzigd zijn.
- Noem exact welke tests/validaties zijn uitgevoerd.
- Meld expliciet wanneer een relevante test niet is uitgevoerd en waarom.
