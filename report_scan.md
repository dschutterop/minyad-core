# Minyad Security & Freshness Audit

**Date:** 2026-06-25
**Scope:** All services in the Minyad monorepo
**Services audited:** api, control, deadman, forecast, frontend, ingestion, migrate, minyad-agent, minyad-trade, mobile-frontend, reporting, host-services (dsmr\_bridge, enphase\_bridge, goodwe\_bridge)

---

## Executive Summary

| Category | Status | Top Finding |
|---|---|---|
| Security | 🔴 Critical | Unauthenticated MQTT broker publicly exposed; zero API authentication on all 40+ endpoints |
| Deprecation | 🟡 Warning | Host-services use paho-mqtt v1 callback API; `anthropic` SDK 72 minor versions stale |
| Module Freshness | 🟡 Warning | `cryptography` 7 majors behind with known CVEs; `anthropic` extremely stale |

---

## Section 1 — Security Findings

### SEC-01 | Critical | MQTT broker is unauthenticated and network-accessible

**Files:** `mosquitto/mosquitto.conf`, `docker-compose.yml`

```
listener 1883 0.0.0.0
allow_anonymous true
```

```yaml
ports:
  - "0.0.0.0:1884:1883"
networks: [minyad-internal, minyad-public]
```

The MQTT broker is bound to all interfaces and allows anonymous connections from any client. Any device on the LAN (or beyond, if port 1884 is forwarded) can publish to `minyad/control/setpoint_w` and command battery charge/discharge without any authentication.

**Recommended fix:**
```
# mosquitto/mosquitto.conf
allow_anonymous false
password_file /mosquitto/config/passwd
```
Add `MQTT_USER`/`MQTT_PASS` to `.env` and pass them to `MinyadMqttClient`. Restrict the published port to `127.0.0.1:1884:1883` if external access is not required.

---

### SEC-02 | High | No authentication on any API endpoint

**File:** `api/main.py` — all 40+ endpoints

Every route, including control endpoints, accepts requests from any source without credentials:

```python
@app.post("/api/control/battery")    # Sets battery setpoint
@app.post("/battery/override")        # Forces battery mode
@app.put("/battery/settings")         # Changes SoC limits
@app.put("/asset-steering/settings")  # Changes strategy
@app.put("/claude-agent/settings")    # Enables/disables AI agent
```

No `HTTPBearer`, `APIKey`, session middleware, or IP allowlist is configured. Port 8002 is on the `minyad-public` network.

**Recommended fix:** Add a shared-secret header dependency to all mutating (and optionally read) endpoints:
```python
from fastapi.security import APIKeyHeader
from fastapi import Security

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_key(key: str = Security(api_key_header)):
    if not secrets.compare_digest(key, os.environ["MINYAD_API_SECRET"]):
        raise HTTPException(status_code=401, detail="Unauthorized")
```
Add `MINYAD_API_SECRET` to `.env` and inject the dependency on mutating routes.

---

### SEC-03 | High | SSL verification disabled in Enphase bridge

**File:** `host-services/enphase_bridge.py:151-157`

```python
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger.warning("Envoy uses a self-signed TLS certificate; verify=False is enabled")
response = self.session.get(url, timeout=self.timeout, verify=False)
```

`verify=False` disables all certificate validation on the session, making the connection vulnerable to MITM attacks on the local network. The Enphase Envoy does use a self-signed certificate, but the correct mitigation is certificate pinning, not disabling all validation.

**Recommended fix:**
```python
# Download the Envoy cert once:
# openssl s_client -connect <ENPHASE_ENVOY_HOST>:443 </dev/null 2>/dev/null \
#   | openssl x509 > /opt/minyad/host-services/envoy.crt

ENVOY_CA_BUNDLE = os.getenv("ENPHASE_ENVOY_CA_BUNDLE", "/opt/minyad/host-services/envoy.crt")
response = self.session.get(url, timeout=self.timeout, verify=ENVOY_CA_BUNDLE)
```
Add `ENPHASE_ENVOY_CA_BUNDLE` to `host-services/.env.example`.

---

### SEC-04 | Medium | SSRF risk via user-configurable `entsoe_api_url`

**Files:** `api/main.py:692-698`, `minyad-trade/epex_collector.py:157`

The ENTSO-E URL can be changed via the unauthenticated `PUT /trade/settings` endpoint. The validator only checks that the value is a syntactically valid HTTP/HTTPS URL:

```python
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    raise ValueError("entsoe_api_url must be an absolute HTTP(S) URL")
```

An attacker can redirect this to an internal address (`http://169.254.169.254/`, `http://minyad-db:5432/`) and cause the trade container to probe internal services.

**Recommended fix:** Lock the allowed domain in the validator:
```python
ALLOWED_ENTSOE_HOST = "web-api.tp.entsoe.eu"

if parsed.netloc != ALLOWED_ENTSOE_HOST:
    raise ValueError(f"entsoe_api_url must point to {ALLOWED_ENTSOE_HOST}")
```
Note: fixing SEC-02 (API authentication) also mitigates this issue.

---

### SEC-05 | Low | All containers run as root

**Files:** All 10 Dockerfiles

No Dockerfile contains a `USER` directive. Every service process runs as `uid=0` inside its container. A container escape or path traversal would yield root on the host.

**Recommended fix:** Add to each Dockerfile before the final `CMD`:
```dockerfile
RUN adduser --disabled-password --no-create-home --uid 1000 minyad
USER minyad
```
Verify the application does not need to bind to ports below 1024 (it does not — all services use 8000+ or are non-binding).

---

### SEC-06 | Low | Physical installation coordinates hardcoded in source

**Files:** `forecast/main.py:19-20`, `api/main.py:153-154`

```python
LATITUDE = 51.9788    # Rotterdam area
LONGITUDE = 4.3158
SOLAR_PEAK_W = 5000
```

These constants identify the physical location and system capacity of the installation and are committed to the git repository.

**Recommended fix:** Move to environment variables:
```python
FORECAST_LATITUDE = float(os.getenv("FORECAST_LATITUDE", "51.9788"))
FORECAST_LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", "4.3158"))
SOLAR_PEAK_W = int(os.getenv("SOLAR_PEAK_W", "5000"))
```
Add them to `.env.example` with placeholder values.

---

## Section 2 — Deprecation Warnings

### DEP-01 | High | Host-services use paho-mqtt v1 callback API

**Files:** `host-services/dsmr_bridge.py:147,177,192,197,210`, `enphase_bridge.py:221`, `goodwe_bridge.py:220`

All three host-service bridges use the paho-mqtt **v1 constructor and 4-argument callback signatures**, which are deprecated in paho-mqtt 2.x and will become errors in a future release:

```python
# v1 constructor — deprecated in paho-mqtt 2.0
mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)

# v1 callback signatures — deprecated in paho-mqtt 2.0
def on_connect(self, client, _userdata, _flags, rc: int):   # 4 args
def on_disconnect(self, _client, _userdata, rc: int):        # 3 args
```

The shared `mqtt_client.py` already uses the correct v2 API (`CallbackAPIVersion.VERSION2` + 5-argument signatures). The host-services lag behind, and the unpinned requirement `paho-mqtt>=1.6` allows installing paho-mqtt 2.x — at which point DeprecationWarnings fire on every connection.

**Recommended fix:** Migrate to the v2 API, matching `shared/mqtt_client.py`:
```python
from paho.mqtt.client import CallbackAPIVersion

self.mqtt_client = mqtt.Client(
    CallbackAPIVersion.VERSION2,
    client_id=CLIENT_ID,
    clean_session=False,
)

def on_connect(self, client, userdata, flags, reason_code, properties):
    ...

def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
    ...
```
Also pin `paho-mqtt==2.1.0` in `host-services/requirements.txt`.

---

### DEP-02 | Medium | `anthropic==0.40.0` — `cache_control.ttl` may be silently ignored

**Files:** `minyad-agent/agent.py:238-248`, `minyad-agent/tools.py` (last entry in `TOOLS`)

```python
SYSTEM_PROMPT_CACHE_TTL = "1h"

system=[{
    "type": "text",
    "text": SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral", "ttl": SYSTEM_PROMPT_CACHE_TTL},
}]
```

The `"ttl"` field in `cache_control` is a newer Anthropic API feature that was introduced after `anthropic==0.40.0`. If the SDK does not forward this field, the prompt cache will reset every 5 minutes (the default) instead of every hour, significantly increasing cache-creation token spend across 96 daily cycles.

The SDK is also 72 minor versions behind current (0.40.0 → 0.112.0), spanning many bug fixes, new model capabilities, and changed response schemas.

**Recommended fix:** Upgrade to the latest stable release:
```
anthropic==0.112.0
```

---

### DEP-03 | Low | APScheduler 3.10.4 — two patch releases behind 3.11.2

**Files:** `minyad-agent/requirements.txt`, `forecast/main.py`

The project uses the APScheduler 3.x API (`BlockingScheduler`, `add_job`). The pinned version 3.10.4 is behind 3.11.2, which contains bug fixes for job coalescing and misfire handling that can affect the agent's 15-minute scheduling interval.

APScheduler 4.x is a complete rewrite with an incompatible import path and is a separate upgrade track — no migration needed here, just a patch bump within 3.x.

**Recommended fix:**
```
apscheduler==3.11.2
```

---

### DEP-04 | Info | Host-services dependencies are fully unpinned

**File:** `host-services/requirements.txt`

```
goodwe
paho-mqtt>=1.6
python-dotenv
pymodbus>=3.6
requests>=2.32
psycopg2-binary>=2.9
```

Floating lower-bounds mean each Docker image rebuild may install a different version. This already causes the paho-mqtt v1/v2 split (DEP-01). Unpinned builds are not reproducible and make it impossible to audit exactly what is running in production.

**Recommended fix:** Run `pip freeze` in a clean venv after validating a working build and commit the result as `host-services/requirements.txt`.

---

### DEP-05 | Info | No deprecated Python language patterns found

A full search for `typing.List`, `typing.Dict`, `typing.Optional`, `asyncio.get_event_loop()`, `@asyncio.coroutine`, `pkg_resources`, and `distutils` found **zero hits**. All code uses modern Python 3.10+ union syntax (`X | None`, `list[str]`, `dict[str, Any]`). No action needed.

---

## Section 3 — Module Freshness

### Root `requirements.txt` (shared by 8 containerised services)

| Package | Pinned | Latest | Delta | Notes |
|---|---|---|---|---|
| `cryptography` | 42.0.8 | **49.0.0** | +7 majors | 🔴 CVE-2024-6119, CVE-2024-12797 in intermediate versions |
| `fastapi` | 0.111.0 | 0.138.0 | +27 minors | Lifespan fixes, security middleware additions |
| `uvicorn[standard]` | 0.30.1 | 0.49.0 | +19 minors | h11 security patches bundled |
| `alembic` | 1.13.2 | 1.18.4 | +5 minors | Autogenerate and batch-op bug fixes |
| `asyncpg` | 0.29.0 | 0.31.0 | +2 minors | Python 3.13 support, protocol fixes |
| `sqlalchemy` | 2.0.31 | 2.0.51 | +20 patches | Same major; many bug fixes |
| `httpx` | 0.27.0 | 0.28.1 | +1 minor | HTTP/2 fixes |
| `jinja2` | 3.1.4 | 3.1.6 | +2 patches | CVE-2024-56201 sandbox escape (low risk in this usage) |
| `psycopg[binary]` | 3.2.1 | 3.3.4 | +1 minor | Pipeline mode fixes |
| `paho-mqtt` | 2.1.0 | 2.1.0 | ✅ Current | |

### `minyad-agent/requirements.txt`

| Package | Pinned | Latest | Delta | Notes |
|---|---|---|---|---|
| `anthropic` | **0.40.0** | 0.112.0 | +72 minors | 🔴 Extremely stale; `ttl` cache may not work — see DEP-02 |
| `apscheduler` | 3.10.4 | 3.11.2 | +2 patches | Bug fixes |
| `httpx` | 0.27.0 | 0.28.1 | +1 minor | |

### `minyad-trade/requirements.txt`

| Package | Pinned | Latest | Delta | Notes |
|---|---|---|---|---|
| `paho-mqtt` | 2.1.0 | 2.1.0 | ✅ Current | |
| `requests` | 2.32.3 | 2.34.2 | +2 minors | Minor fixes |

### `host-services/requirements.txt` (all unpinned — see DEP-04)

| Package | Min bound | Latest stable | Notes |
|---|---|---|---|
| `goodwe` | unpinned | 0.4.10 | Active project; no known CVEs |
| `paho-mqtt` | `>=1.6` | 2.1.0 | Will install v2, breaking v1 callbacks (DEP-01) |
| `pymodbus` | `>=3.6` | 3.13.1 | Large gap; 3.7+ has async API changes worth reviewing |
| `requests` | `>=2.32` | 2.34.2 | Minor fixes only |
| `psycopg2-binary` | `>=2.9` | 2.9.12 | OK |
| `python-dotenv` | unpinned | 1.2.2 | OK |

### CVE detail: `cryptography==42.0.8`

| CVE | Fixed in | Severity | Description |
|---|---|---|---|
| CVE-2024-26130 | 42.0.5 | High | PKCS12 null-deref — already fixed in 42.0.8 ✅ |
| CVE-2024-6119 | 43.0.0 | High | X.509 general name parsing DoS |
| CVE-2024-12797 | 44.0.1 | Medium | RSA PSS signature malleability |

The Fernet encryption used in `shared/db.py` for settings values is symmetric and not directly affected by RSA/X.509 CVEs, but upgrading is still recommended as defence-in-depth.

---

## Mitigation Roadmap

The roadmap is organised into four sprints. Each sprint can be run as a focused pull request. P0 items should be addressed before any new feature work.

---

### Sprint 1 — Critical Security (do first, ~1 day)

**Goal:** Close the two most impactful attack surfaces: unauthenticated battery control via MQTT and the REST API.

#### Task 1.1 — Enable MQTT authentication (SEC-01)

1. Generate a password file:
   ```bash
   docker run --rm eclipse-mosquitto:2 \
     mosquitto_passwd -c -b /tmp/passwd minyad <strong-password>
   cat /tmp/passwd  # copy output
   ```
2. Save the output to `mosquitto/passwd` (add to `.gitignore`).
3. Update `mosquitto/mosquitto.conf`:
   ```
   listener 1883 0.0.0.0
   allow_anonymous false
   password_file /mosquitto/config/passwd
   ```
4. Mount the file in `docker-compose.yml`:
   ```yaml
   volumes:
     - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
     - ./mosquitto/passwd:/mosquitto/config/passwd:ro
   ```
5. Add `MQTT_USER` and `MQTT_PASS` to `.env` and `.env.example`.
6. Update `shared/mqtt_client.py` `MqttConfig` to read them:
   ```python
   username: str | None = os.getenv("MQTT_USER")
   password: str | None = os.getenv("MQTT_PASS")
   ```
   And in `connect_forever`:
   ```python
   if self.config.username:
       self.client.username_pw_set(self.config.username, self.config.password)
   ```
7. Verify each bridge service also passes credentials (they already read `MQTT_USER`/`MQTT_PASS`).

#### Task 1.2 — Add API authentication (SEC-02)

1. Add `MINYAD_API_SECRET` to `.env` (generate with `python -c "import secrets; print(secrets.token_hex(32))"`).
2. Add to `api/main.py`:
   ```python
   import secrets
   from fastapi.security import APIKeyHeader
   from fastapi import Security

   _api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

   async def _require_key(key: str = Security(_api_key_header)) -> None:
       expected = os.environ.get("MINYAD_API_SECRET", "")
       if not expected or not secrets.compare_digest(key, expected):
           raise HTTPException(status_code=401, detail="Unauthorized")
   ```
3. Apply the dependency to all mutating and control routes. At minimum:
   - `POST /api/control/battery`
   - `POST /battery/override`, `DELETE /battery/override`
   - `PUT /battery/settings`, `PUT /api/battery/settings`
   - `PUT /trade/settings`, `PUT /asset-steering/settings`
   - `PUT|PATCH /claude-agent/settings`
   - `PUT /system-settings`
4. Update `frontend/main.py` and `mobile-frontend/main.py` to pass `X-API-Key: <secret>` in proxied requests.
5. Update `minyad-agent/minyad_client.py` to include the header.

#### Task 1.3 — Restrict MQTT port binding (SEC-01 follow-up)

Change the published port in `docker-compose.yml` to localhost-only unless external access is required:
```yaml
ports:
  - "127.0.0.1:1884:1883"
```

---

### Sprint 2 — High Security + Critical Dependency Upgrades (~half a day)

**Goal:** Fix the SSL bypass, plug the SSRF hole, and upgrade the two packages with active CVEs.

#### Task 2.1 — Replace `verify=False` with cert pinning (SEC-03)

1. Add `ENPHASE_ENVOY_CA_BUNDLE` env var to `host-services/.env.example`.
2. Provide a script or README step to export the Envoy cert:
   ```bash
   openssl s_client -connect "$ENPHASE_ENVOY_HOST:443" </dev/null 2>/dev/null \
     | openssl x509 > /opt/minyad/host-services/envoy.crt
   ```
3. In `host-services/enphase_bridge.py`, replace the `verify=False` block:
   ```python
   ca_bundle = os.getenv("ENPHASE_ENVOY_CA_BUNDLE")
   verify: str | bool = ca_bundle if ca_bundle else False
   if not ca_bundle:
       logger.warning("ENPHASE_ENVOY_CA_BUNDLE not set; falling back to verify=False")
   response = self.session.get(url, timeout=self.timeout, verify=verify)
   ```
   Remove the `urllib3.disable_warnings` call once the cert is pinned.

#### Task 2.2 — Lock `entsoe_api_url` domain (SEC-04)

In `api/main.py`, tighten the validator in `TradeSettingsUpdate`:
```python
_ALLOWED_ENTSOE_HOST = "web-api.tp.entsoe.eu"

@field_validator("entsoe_api_url")
@classmethod
def validate_entsoe_api_url(cls, value: str | None) -> str | None:
    if value is None:
        return value
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("entsoe_api_url must be an absolute HTTP(S) URL")
    if parsed.netloc != _ALLOWED_ENTSOE_HOST:
        raise ValueError(f"entsoe_api_url host must be {_ALLOWED_ENTSOE_HOST}")
    return url
```

#### Task 2.3 — Upgrade `cryptography` and `jinja2` (CVE fixes)

In `requirements.txt`:
```
cryptography==49.0.0
jinja2==3.1.6
```
Run the test suite after the upgrade: `pytest tests/`.

#### Task 2.4 — Upgrade `anthropic` SDK (DEP-02 + freshness)

In `minyad-agent/requirements.txt`:
```
anthropic==0.112.0
```
After upgrading, verify the `cache_control` TTL is accepted by running one manual cycle:
```bash
docker compose run --rm minyad-agent python -c "
from anthropic import Anthropic
import os
c = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
r = c.messages.create(
    model='claude-haiku-4-5-20251001',
    max_tokens=10,
    system=[{'type':'text','text':'hi',
             'cache_control':{'type':'ephemeral','ttl':'1h'}}],
    messages=[{'role':'user','content':'ping'}]
)
print(r.usage)
"
```
Confirm `cache_creation_input_tokens` appears in the response.

---

### Sprint 3 — Deprecation Fixes (~half a day)

**Goal:** Eliminate deprecated paho-mqtt v1 callbacks in host-services and pin all dependencies.

#### Task 3.1 — Migrate host-service paho callbacks to v2 API (DEP-01)

Apply the following changes to `dsmr_bridge.py`, `enphase_bridge.py`, and `goodwe_bridge.py`.

**Constructor change:**
```python
# Before
mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)

# After
mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, clean_session=False)
```

**Callback signature changes:**
```python
# Before
def on_connect(self, client, _userdata, _flags, rc: int):
    if rc == 0:
        ...

# After
def on_connect(self, client, _userdata, _flags, reason_code, _properties):
    if reason_code.is_failure:
        return
    ...

# Before
def on_disconnect(self, _client, _userdata, rc: int):

# After
def on_disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties):
```

#### Task 3.2 — Pin all host-services dependencies (DEP-04)

```bash
cd host-services
python -m venv .venv-pin
.venv-pin/bin/pip install goodwe paho-mqtt==2.1.0 python-dotenv pymodbus requests psycopg2-binary
.venv-pin/bin/pip freeze > requirements.txt
```
Review the output and commit.

#### Task 3.3 — Bump `apscheduler` (DEP-03)

In `minyad-agent/requirements.txt`:
```
apscheduler==3.11.2
```

---

### Sprint 4 — Housekeeping & Hardening (~1 day)

**Goal:** Add defence-in-depth measures and reduce operational risk.

#### Task 4.1 — Add non-root users to all Dockerfiles (SEC-05)

Add to each of the 10 Dockerfiles, before the final `CMD` or `ENTRYPOINT`:
```dockerfile
RUN adduser --disabled-password --no-create-home --uid 1000 minyad
USER minyad
```

#### Task 4.2 — Move hardcoded coordinates to env vars (SEC-06)

**`forecast/main.py`:**
```python
LATITUDE = float(os.getenv("FORECAST_LATITUDE", "51.9788"))
LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", "4.3158"))
PEAK_W = int(os.getenv("SOLAR_PEAK_W", "5000"))
```

**`api/main.py`:**
```python
FORECAST_LATITUDE = float(os.getenv("FORECAST_LATITUDE", "51.9788"))
FORECAST_LONGITUDE = float(os.getenv("FORECAST_LONGITUDE", "4.3158"))
SOLAR_PEAK_W = int(os.getenv("SOLAR_PEAK_W", "5000"))
```

Add to `.env.example`:
```
FORECAST_LATITUDE=
FORECAST_LONGITUDE=
SOLAR_PEAK_W=5000
```

#### Task 4.3 — Upgrade remaining stale dependencies

In `requirements.txt`, bump the remaining out-of-date packages:
```
alembic==1.18.4
asyncpg==0.31.0
psycopg[binary]==3.3.4
fastapi==0.138.0
uvicorn[standard]==0.49.0
sqlalchemy==2.0.51
httpx==0.28.1
```

Run the full test suite after each bump, or all at once:
```bash
pip install -r requirements.txt
pytest tests/ -x
```

#### Task 4.4 — Add CORS restriction to the API

Confirm the API is intended to be accessed only from the frontend containers. If so, lock `allow_origins`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8084",
        "http://localhost:8085",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)
```

---

## Sprint Summary

| Sprint | Effort | Risk reduced | Findings addressed |
|---|---|---|---|
| 1 — Critical Security | ~1 day | 🔴 → 🟡 | SEC-01, SEC-02 |
| 2 — High Security + CVE Deps | ~4 hours | 🟡 → 🟢 for deps | SEC-03, SEC-04, CVEs in `cryptography`, DEP-02 |
| 3 — Deprecation Fixes | ~4 hours | 🟡 → 🟢 | DEP-01, DEP-03, DEP-04 |
| 4 — Housekeeping | ~1 day | defence-in-depth | SEC-05, SEC-06, remaining freshness |

**Recommended sequence:** Sprint 1 should be completed before any other development. Sprints 2 and 3 can run in parallel. Sprint 4 can be folded into normal development velocity.
