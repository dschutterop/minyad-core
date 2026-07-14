"""Integration tests for the authenticated GET /api/v1/surplus response: the whole route
handler (DB access glue + build_surplus_payload) exercised together, including over real HTTP
via TestClient, matching how Vesper polls this endpoint."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import pytest
from fastapi.testclient import TestClient

import api.main as api_main

pytestmark = pytest.mark.usefixtures("_require_forecast_contract")


@pytest.fixture
def _require_forecast_contract():
    pytest.importorskip(
        "minyad.strategy.v3.forecast_contract",
        reason="private strategy package not present in a standalone Minyad Core checkout",
    )

UTC = timezone.utc


def _aligned_now() -> datetime:
    """A real, 15-minute-aligned 'now' — the route under test calls datetime.now(timezone.utc)
    internally, so plan freshness must be computed relative to real time, not a fixed date."""
    now = datetime.now(UTC)
    return now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)


class Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeResult:
    def __init__(self, rows=None, mapping=None, scalar=None):
        self._rows = rows or []
        self._mapping = mapping
        self._scalar = scalar

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return self._rows

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def scalar_one_or_none(self):
        return self._scalar


def _plan_row(now, *, solver_status="Optimal"):
    slots = [
        {
            "start": (now + timedelta(seconds=900 * i)).isoformat(),
            "soc_target_pct": min(90.0, 68.0 + i * 0.02),
            "planned_grid_charge_w": 0,
            "planned_export_w": 0,
            "pv_forecast_w": 1500.0,
            "load_forecast_w": 400.0,
            "charge_w": 300.0,
            "discharge_w": 0,
            "curtailment_w": 0,
            "price_source": "fallback",
            "cloud_cover_pct": 10.0,
            "surplus_w": 800.0,
            "price_import": 0.25,
            "price_export": 0.0,
        }
        for i in range(96)
    ]
    payload = {
        "generated_at": now.isoformat(),
        "valid_from": now.isoformat(),
        "slot_seconds": 900,
        "soc_start_pct": 68.0,
        "slots": slots,
        "friday_full_cycle": False,
        "solver_status": solver_status,
        "pv_calibration_factor": 7.0,
        "plan_schema": 2,
    }
    return {
        "generated_at": now,
        "valid_from": now,
        "slot_seconds": 900,
        "payload": payload,
        "solver_status": solver_status,
    }


def _bands_rows():
    grid = [[1, 0.5], [5, 0.6], [10, 0.7], [25, 0.85], [50, 1.0], [75, 1.1], [90, 1.2], [95, 1.25], [99, 1.3]]
    return [Row(cloud_class="clear", p10_multiplier=0.7, p90_multiplier=1.2, p25_multiplier=0.85, p50_multiplier=1.0, quantile_grid=grid)]


class FakeSession:
    """Dispatches on SQL substrings, mirroring the fake-Session pattern already used in
    tests/test_api_battery_settings.py and tests/test_api_status_payloads.py for exercising
    route handlers without a real Postgres instance."""

    def __init__(self, plan_row=None, bands_rows=None):
        self.plan_row = plan_row
        self.bands_rows = bands_rows if bands_rows is not None else _bands_rows()

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "from battery_override" in sql:
            return FakeResult(mapping=None)
        if "key like 'battery.%'" in sql:
            return FakeResult(rows=[Row(key="battery.soc_floor", value="20"), Row(key="battery.soc_ceiling", value="90")])
        if "key = any(:keys)" in sql:
            return FakeResult(rows=[
                Row(key="battery.capacity_wh", value="10240"),
                Row(key="strategy3.one_way_efficiency", value="0.92"),
                Row(key="battery.max_charge_w", value="3000"),
                Row(key="battery.max_charge_a", value="100"),
                Row(key="battery.nominal_v", value="48"),
                Row(key="battery.max_discharge_w", value="3000"),
            ])
        if "from slot_plans" in sql:
            return FakeResult(mapping=self.plan_row)
        if "max(calibration_date)" in sql:
            return FakeResult(scalar=datetime(2026, 7, 14).date() if self.bands_rows else None)
        if "from pv_uncertainty_bands where calibration_date" in sql:
            return FakeResult(rows=self.bands_rows)
        return FakeResult()

    async def commit(self):
        return None


def _mqtt_status(now: datetime):
    now_iso = now.isoformat()
    return {
        "soc": "68",
        "soh": "98",
        "power_w": "-300",
        "voltage": "52.0",
        "mode": "charge",
        "bridge_status": "online",
        "bridge_last_seen": now_iso,
        "grid_net_power_w": "-800",
        "grid_status": "connected",
        "grid_timestamp": now_iso,
        "solar_power_w": "1500",
        "solar_updated_at": now_iso,
    }


async def _noop(*_args, **_kwargs):
    await asyncio.sleep(0)
    return None


def test_api_v1_surplus_route_returns_valid_minyad_forecast(monkeypatch):
    now = _aligned_now()
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: _mqtt_status(now))
    monkeypatch.setattr(api_main, "store_power_curve_point", _noop)

    session = FakeSession(plan_row=_plan_row(now))
    payload = asyncio.run(api_main.api_v1_surplus(session))

    assert payload["api_version"] == "v1"
    assert payload["surplus_w"] == 800
    assert payload["battery"]["soc"] == 68
    assert payload["minyad_forecast"]["quality"] == "authoritative_lp"
    assert payload["minyad_forecast"]["slot_count"] == 96
    assert len(payload["minyad_forecast"]["surplus_p50_w"]) == 96
    assert payload["battery"]["soc_trajectory_pct"] == payload["minyad_forecast"]["soc_pct"]
    assert payload["battery"]["capacity_kwh"] == 10.24


def test_api_v1_surplus_route_marks_forecast_unavailable_on_fallback_plan(monkeypatch):
    now = _aligned_now()
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: _mqtt_status(now))
    monkeypatch.setattr(api_main, "store_power_curve_point", _noop)

    session = FakeSession(plan_row=_plan_row(now, solver_status="FALLBACK"))
    payload = asyncio.run(api_main.api_v1_surplus(session))

    assert payload["surplus_w"] == 800  # live fields unaffected
    assert payload["minyad_forecast"]["quality"] == "unavailable"
    assert payload["minyad_forecast"]["validation"]["reason"] == "solver_fallback"
    assert "soc_trajectory_pct" not in payload["battery"]


def test_api_v1_surplus_route_omits_forecast_when_no_plan_exists(monkeypatch):
    now = _aligned_now()
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: _mqtt_status(now))
    monkeypatch.setattr(api_main, "store_power_curve_point", _noop)

    session = FakeSession(plan_row=None)
    payload = asyncio.run(api_main.api_v1_surplus(session))

    assert payload["surplus_w"] == 800
    assert payload["minyad_forecast"]["quality"] == "unavailable"
    assert payload["minyad_forecast"]["validation"]["reason"] == "missing_plan"


def test_api_v1_surplus_over_http_returns_forecast_and_legacy_fields(monkeypatch):
    """Full HTTP round trip through FastAPI's own routing/serialization, as Vesper would call it."""
    now = _aligned_now()
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: _mqtt_status(now))
    monkeypatch.setattr(api_main, "store_power_curve_point", _noop)

    async def _override_session():
        await asyncio.sleep(0)
        yield FakeSession(plan_row=_plan_row(now))

    api_main.app.dependency_overrides[api_main.get_session] = _override_session
    try:
        # No `with` block: entering TestClient as a context manager runs FastAPI's real
        # startup event (a genuine DB/MQTT connection) — matches the existing convention in
        # tests/test_api_cors.py, which also constructs TestClient without one.
        client = TestClient(api_main.app)
        response = client.get("/api/v1/surplus")
        legacy_response = client.get("/api/surplus")
    finally:
        api_main.app.dependency_overrides.pop(api_main.get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["surplus_w"] == 800
    assert body["minyad_forecast"]["slot_count"] == 96
    assert body["minyad_forecast"]["starts_at"] == now.isoformat()

    assert legacy_response.status_code == 200
    assert legacy_response.json()["minyad_forecast"]["quality"] == "authoritative_lp"
