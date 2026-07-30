# 2026-07-14 architecture cleanup — completed

This is a historical record, not a live backlog — every item below is done. It documents the
follow-ups from the 2026-07-14 architecture cleanup. All three were completed in
`refactor/architecture-cleanup`, each verified as far as possible in a sandboxed dev environment.
What's left in each section is genuinely "requires the real thing" — self-hosted runner, production
secrets, or live battery/grid hardware — not further code changes.

## `api/main.py` split into FastAPI routers — done

Split into `api/state.py` (shared app/mqtt/locks/caches, no dependency on `api.main`),
`api/mqtt_handlers.py` (MQTT callbacks/publishers), and six `api/routers/<domain>.py` modules
(health, settings, battery, grid, dashboard, agent), each an `APIRouter` included via
`app.include_router(...)` in `api/main.py`, which is now just the composition root plus
backward-compatible re-exports for tests that still do `from api.main import <name>`.

Verified: full test suite (467 passing), route-path parity against the pre-split file (identical
51 routes), `__all__`/re-export audit against every `api.main.<name>` usage in `tests/`, auth
coverage across all six routers, and an actual end-to-end run — real Postgres + real Mosquitto +
the production API Docker image (flat `main:app` import layout) — hit through every router
(`/health`, `/settings`, `/battery/status`, `/grid/status`, `/dashboard/forecast-quality`,
`/api/agent/decisions`, `/api/messages`, `/api/v1/surplus`), all returning 200.

**Still needs**: a canary deploy exercising real battery charge/discharge cycles and live grid
meter readings — not reproducible outside production hardware.

## Broaden linting / add type checking — done

`pyproject.toml`'s `[tool.ruff.lint]` now selects `E, F, I, UP, B, SIM, RUF, FAST002` (was
`FAST002, RUF029, F841, SIM102`), with `E501` ignored (dominated by inline HTML/CSS/JS in
`frontend/*`) and two documented per-file ignores (`RUF069` in `tests/`, `RUF001` in
`frontend/*.py`). `pyright` is configured (`basic` mode) and was, at the time, wired into the
`sonar` CI job as a report-only step (`continue-on-error: true`) — see the 2026-07-30 addendum
below for how this was resolved.

Found and fixed one real bug the broadened ruff catches: `InverterState` was used in two type
annotations in `host-services/goodwe_bridge.py` without being imported (silently masked by
`from __future__ import annotations`). Pyright's initial 58 findings were triaged down to a
24-error backlog — all either `pymodbus` version-compat shims, invariants invisible across
function boundaries, or defensive duck-typing, not live bugs — documented but not all fixed.

**Resolved 2026-07-30**: see the addendum at the end of this document — the backlog is at zero
and both CI gates are now blocking.

## `docker-compose.yml` / `.github/workflows/deploy.yml` split — done

`docker-compose.monitoring.yml` is a new overlay (extending the existing base+prod idiom) holding
`minyad-node-exporter`/`minyad-cadvisor`, the only host-privileged, build-less services. The 10
core app services stayed in the base file — they're homogeneous, and splitting them further would
just add `-f` flags for little readability gain.

`.github/actions/deploy`, `.github/actions/public-release-gate`, and `.github/actions/build-image`
replace the step-for-step duplication between `deploy.yml` and `quick-release.yml` (verified
byte-identical before extracting). The local composite actions required one new
`actions/checkout@v5` step in each workflow's `deploy` job (it previously had none, operating
entirely via `cd "${DEPLOY_PATH}"` into a separately-maintained checkout on the host) — the one
intentional step-list change; a before/after diff confirms nothing else moved or dropped.

Deliberately **not** done: deduplicating the 4x-repeated `run_trivy` boolean expression via a
job output. `sonar`/`trivy`/`trivy-gate`/`deploy` don't currently share a common direct `needs:`
predecessor that has it available, so exposing it as a `needs.<job>.outputs.run_trivy` would mean
adding new edges to the job graph — a structural change this doc always warned to be careful
with, for a purely cosmetic DRY win. Left as documented, working duplication.

**Still needs**: an actual run of both workflows against the real self-hosted runner and
production secrets, on a branch, before merging to `main` — none of this is reachable from a
sandboxed dev environment.

## Split deploy out of minyad-core entirely — done

Superseded the paragraph above: `.github/actions/deploy` is gone, and so is
`quick-release.yml`. `deploy.yml` is renamed to `release.yml` and now stops after
`trivy-gate` — it builds and pushes the 11 service images to GHCR and nothing else, no
self-hosted deploy job, no `DEPLOY_PATH`, no dispatch to any other repo. `sonar`/`trivy`/
`trivy-gate` still run on the self-hosted `minyad` runner (needed for the internal
SonarQube/Trivy network access), but that runner no longer touches the production
docker-compose stack or host secrets.

The actual merge-and-deploy logic moved to a new repo, `minyad-pro`, which pulls
`minyad-core` and `minyad-private`, overlays them, and runs the deploy job that used to
live here. See that repo's README for the trigger model (schedule + optional dispatch from
`minyad-private`, no dependency on this repo notifying anyone).

## Pyright backlog resolved and ci.yml's type-check gate made blocking (2026-07-30) — done

Triaged the 24-error backlog above (23 by the time this ran; one had already been fixed
incidentally) to zero. Six were exactly the documented category — invariants invisible across
function/method boundaries, not real bugs — fixed with `assert`s that double as runtime guards,
or small restructurings, rather than `# type: ignore` suppressions:
`api/routers/dashboard.py`, `control/main.py`, `host-services/minyad_explain.py`,
`scripts/fetch_dryad.py`, `ingestion/sensors/dsmr.py`, `host-services/backends/goodwe_backend.py`.

One was a real, currently-live bug: `host-services/backends/modbus_backend.py`'s Modbus
unit-ID fallback only ever tried `slave=`/`unit=`, and both raise `TypeError` against the
pinned `pymodbus==3.13.1` (confirmed by installing that exact version and inspecting
`read_holding_registers`/`write_register`/`write_registers` directly — the real parameter is
`device_id`). Every Modbus read/write would currently fail for any deployment with
`GOODWE_MODBUS_LIMITS_ENABLED=true`. The test suite's fake client had silently drifted from
the real pinned dependency's signature, which is exactly why this wasn't caught. Replaced the
two-name fallback with a helper trying `device_id`/`slave`/`unit` in order, updated the fake,
and added tests covering the fallback paths explicitly.

`ci.yml`'s pyright step is now a normal blocking step. It also needed installing the project's
own `requirements.txt` first — the lint job never had that, so pyright couldn't resolve any
third-party import (sqlalchemy, cryptography, paho-mqtt, alembic's `op`, ...), producing ~74
unrelated errors that `continue-on-error: true` was silently swallowing alongside the real
backlog. Verified end-to-end: a green PR against the actual `ci.yml` on GitHub, not just a
local run.

`release.yml`'s `sonar` job had the identical report-only pyright step and the identical
missing-dependency gap. Brought it to the same blocking state for consistency, as its own
explicit change rather than bundled into the docs cleanup above, since `sonar` runs only on
the self-hosted `minyad` runner with production secrets.

**Still needs**: unlike everything else here, this last piece isn't reachable from a sandboxed
dev environment, so it's verified only by static reasoning (identical fix pattern to `ci.yml`,
which did get a real green run) and by installing the exact pinned dependencies into an
isolated local environment and confirming the same zero-error result. `sonar` is a leaf job
nothing else depends on (`build`/`trivy`/`trivy-gate` all key off `test`, not `sonar`), so the
blast radius if something about that runner's environment turns out to differ is low — but it
still needs one actual run on that runner to fully confirm.
