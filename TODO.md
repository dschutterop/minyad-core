# TODO

Follow-ups deliberately left out of the 2026-07-14 architecture cleanup (requirements-per-service,
pyproject.toml, TLS script extraction, api/frontend payload/view extraction) because they're
bigger and/or riskier than that pass, not because they don't matter.

## Split `api/main.py`'s routes into FastAPI routers

`api/main.py` still holds every `@app.get`/`@app.put`/`@app.post`/... handler, the MQTT event
wiring, and the shared locks/caches (`MQTT_STATUS_LOCK`, `TRADE_PRICE_CACHE`, the `mqtt` client
instance, etc.) in one file (~2000 lines). The pure payload-shaping logic already moved out to
`api/payload_helpers.py` — what's left is genuinely stateful and tightly coupled, which is exactly
why it wasn't touched blind: a wrong extraction here can't be fully verified without exercising it
against real battery/grid hardware, and this file drives live control decisions.

To do it properly:
- Introduce a dedicated state module (locks/caches/MQTT client) with no dependency on `api.main`,
  so router modules can import shared state without a circular import back to `main.py`.
- Split routes into `api/routers/<domain>.py` (battery, grid/solar, trade, agent/messages,
  dashboard, settings) using FastAPI `APIRouter` + `app.include_router(...)`.
- Watch for: routes calling other routes as plain functions (e.g. `api_control_battery` calls
  `current_battery_override`/`set_battery_override` directly), and the handful of multi-decorated
  routes (`/api/claude-agent/settings` + `/claude-agent/settings` on one handler).
- Verify against the full test suite *and* a real deploy before trusting it — this is the one
  place where "tests pass" isn't sufficient confidence on its own.

## Broaden linting / add type checking

CI only runs `ruff check` with a hand-picked rule subset (`FAST002,RUF029,F841,SIM102`, see
`pyproject.toml`'s `[tool.ruff.lint]`). There's no mypy/pyright anywhere in the pipeline for a
codebase this size. Turning on a broader ruleset or a type checker will likely surface a real
backlog of pre-existing findings — budget time to triage them (fix vs. suppress vs. ignore) rather
than just flipping it on and leaving CI red.

## Split `docker-compose.yml` / `.github/workflows/deploy.yml`

Both are large single files (405 and 452 lines respectively) that will get harder to reason about
as more services are added. Splitting the workflow into reusable/composite GitHub Actions is the
natural fix, but deliberately not touched in this pass — it's the exact production CI/CD pipeline
that took a long back-and-forth to stabilize (see git history around the minyad-deploy setup), and
restructuring it right after finally getting it green carries real risk of reintroducing the same
class of breakage. Worth doing once it's been stable for a while, with careful testing on a branch
first.
