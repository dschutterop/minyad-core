"""Integration-style test for GET /api/dashboard/energy-center.

Exercises api.routers.dashboard.energy_center_overview end to end with the
status/settings/health sub-calls it aggregates replaced by canned async
stand-ins (same style as test_api_dashboard_helpers.py's FakeSession), plus a
FakeSession for the power_curve_points query the kWh integration reads. This
checks the aggregation and response shape; the underlying status/settings/
health functions themselves are already covered by their own routers' tests.
"""

import asyncio
import os
from datetime import UTC, datetime

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import pytest

from api.routers import dashboard as dashboard_router
from tests.test_api_settings_endpoints import FakeResult, FakeSession

FIXED_NOW = datetime(2026, 6, 1, 10, 0, 3, tzinfo=UTC)  # 3 s after the canned telemetry below


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(dashboard_router, "_utcnow", lambda: FIXED_NOW)


def run(coro):
    return asyncio.run(coro)


def _curve_row(ts: datetime, source: str, power_w: float, net_w: float | None = None) -> dict:
    return {
        "ts": ts,
        "source": source,
        "power_w": power_w,
        "delivered_w": None,
        "returned_w": None,
        "net_w": net_w if net_w is not None else power_w,
    }


def _patch_sources(monkeypatch, *, soc=55, min_soc=15, max_soc=90, mismatch=False, health_status="ok", plan_row=False):
    async def fake_battery_status(session):
        await asyncio.sleep(0)
        return {
            "soc": soc,
            "soh": 97,
            "power_w": -400,  # charging
            "state": "CHARGING",
            "bridge_last_seen": "2026-06-01T10:00:00+00:00",
            "override_mode": "none",
            "override_soc_limits": False,
        }

    async def fake_grid_status(session):
        await asyncio.sleep(0)
        return {
            "solar_power_w": 1200,
            "grid_net_power_w": 390,  # importing
            "solar_updated_at": "2026-06-01T10:00:00+00:00",
            "grid_timestamp": "2026-06-01T10:00:00+00:00",
        }

    async def fake_household_status(session, store=False):
        await asyncio.sleep(0)
        return {"power_w": 400, "approx": False, "mismatch": mismatch, "deviation_pct": 22.5 if mismatch else 0.0}

    async def fake_battery_settings(session):
        await asyncio.sleep(0)
        return {"soc_floor": min_soc, "soc_ceiling": max_soc, "cooldown": 180}

    async def fake_battery_lp_meta(session):
        await asyncio.sleep(0)
        return {"capacity_kwh": 10.0}

    async def fake_health_status(session):
        await asyncio.sleep(0)
        overall = "ok" if health_status == "ok" else health_status
        return {
            "status": overall,
            "generated_at": "2026-06-01T10:00:05+00:00",
            "components": [
                {"name": "Solar / Enphase bridge", "status": "ok", "detail": "fine", "last_seen": None, "endpoint": "/solar/status"},
                {"name": "Battery / GoodWe bridge", "status": "ok", "detail": "fine", "last_seen": None, "endpoint": "/battery/status"},
                {"name": "DSMR / grid meter", "status": health_status, "detail": "stale" if health_status != "ok" else "fine", "last_seen": None, "endpoint": "/dsmr/status"},
            ],
        }

    async def fake_asset_steering_status(session):
        await asyncio.sleep(0)
        return {
            "latest_decision": {"trigger_reason": "surplus_charge", "soc_floor": min_soc, "soc_ceiling": max_soc, "timestamp": "2026-06-01T09:55:00+00:00"} if plan_row else None,
            "latest_setpoint": None,
        }

    monkeypatch.setattr(dashboard_router, "battery_status", fake_battery_status)
    monkeypatch.setattr(dashboard_router, "grid_status", fake_grid_status)
    monkeypatch.setattr(dashboard_router, "household_status_payload", fake_household_status)
    monkeypatch.setattr(dashboard_router, "battery_settings", fake_battery_settings)
    monkeypatch.setattr(dashboard_router, "battery_lp_meta", fake_battery_lp_meta)
    monkeypatch.setattr(dashboard_router, "health_status", fake_health_status)
    monkeypatch.setattr(dashboard_router, "asset_steering_status", fake_asset_steering_status)


def _session_with_curve_points():
    rows = [
        _curve_row(datetime(2026, 6, 1, 8, 0), "solar", 1000),
        _curve_row(datetime(2026, 6, 1, 9, 0), "solar", 2000),
        _curve_row(datetime(2026, 6, 1, 8, 0), "household", 500),
        _curve_row(datetime(2026, 6, 1, 9, 0), "household", 500),
        _curve_row(datetime(2026, 6, 1, 8, 0), "grid", 300, net_w=300),
        _curve_row(datetime(2026, 6, 1, 9, 0), "grid", -100, net_w=-100),
        _curve_row(datetime(2026, 6, 1, 8, 0), "battery", -200),
        _curve_row(datetime(2026, 6, 1, 9, 0), "battery", 100),
    ]
    return FakeSession([
        ("power_curve_points", FakeResult(rows=rows)),
        ("slot_plans", FakeResult(rows=[])),
    ])


def test_energy_center_overview_shape_and_sign_conventions(monkeypatch):
    _patch_sources(monkeypatch, soc=55, min_soc=15, max_soc=90)
    session = _session_with_curve_points()

    result = run(dashboard_router.energy_center_overview(session))

    assert result["connection"] == "live"
    assert result["instantaneous"]["gridKw"]["value"] == 0.39
    assert result["instantaneous"]["gridDirection"] == "import"
    assert result["instantaneous"]["batteryKw"]["value"] == -0.4
    assert result["instantaneous"]["batteryDirection"] == "charge"
    assert result["instantaneous"]["pvKw"]["value"] == 1.2
    assert result["today"]["selfSufficiencyPct"]["value"] is not None
    assert result["battery"]["socAlert"] is None
    # No slot plan is configured in this fixture, so the only alert is the
    # honest "no forecast plan" one -- never a fabricated "all clear".
    assert [a["id"] for a in result["alerts"]] == ["forecast-plan-unavailable"]
    assert result["topAlertSeverity"] == "info"


def test_energy_center_overview_flags_soc_below_floor_not_healthy(monkeypatch):
    _patch_sources(monkeypatch, soc=14, min_soc=15, max_soc=90)
    session = _session_with_curve_points()

    result = run(dashboard_router.energy_center_overview(session))

    assert result["battery"]["socPct"]["value"] == 14
    assert result["battery"]["socAlert"] is not None
    assert result["battery"]["socAlert"]["severity"] == "warning"
    assert any(a["id"] == "battery-soc-below-floor" for a in result["alerts"])
    assert result["topAlertSeverity"] == "warning"


def test_energy_center_overview_household_mismatch_and_unhealthy_component_produce_alerts(monkeypatch):
    _patch_sources(monkeypatch, mismatch=True, health_status="warning")
    session = _session_with_curve_points()

    result = run(dashboard_router.energy_center_overview(session))

    alert_ids = {a["id"] for a in result["alerts"]}
    assert "household-meter-mismatch" in alert_ids
    assert any(a_id.startswith("health-") for a_id in alert_ids)
    assert result["connection"] == "delayed"


def test_energy_center_overview_agent_section_uses_strategy_decision_when_present(monkeypatch):
    _patch_sources(monkeypatch, plan_row=True)
    session = _session_with_curve_points()

    result = run(dashboard_router.energy_center_overview(session))

    assert result["agent"]["mode"] == "CHARGING"
    assert result["agent"]["reasonText"] == "surplus_charge"
    assert result["agent"]["enabled"] is True
    assert result["agent"]["nextActionText"] == "Geen geplande actie beschikbaar"


def test_energy_center_overview_agent_section_unavailable_when_no_decision(monkeypatch):
    _patch_sources(monkeypatch, plan_row=False)
    session = _session_with_curve_points()

    result = run(dashboard_router.energy_center_overview(session))

    assert result["agent"]["enabled"] is None
    assert result["agent"]["reasonText"] is None


def test_energy_center_overview_connection_follows_telemetry_age_not_health(monkeypatch):
    _patch_sources(monkeypatch)
    # Health says ok, but the clock is 2 minutes past the newest reading: not live.
    monkeypatch.setattr(dashboard_router, "_utcnow", lambda: datetime(2026, 6, 1, 10, 2, 0, tzinfo=UTC))

    result = run(dashboard_router.energy_center_overview(_session_with_curve_points()))

    assert result["connection"] == "offline"
    assert result["telemetryAgeSeconds"] == 120.0
    assert result["updatedAt"] == "2026-06-01T10:00:00+00:00"
    assert result["instantaneous"]["gridKw"]["quality"] == "stale"


def test_energy_center_overview_updated_at_is_telemetry_time_not_health_check_time(monkeypatch):
    _patch_sources(monkeypatch)

    result = run(dashboard_router.energy_center_overview(_session_with_curve_points()))

    assert result["connection"] == "live"
    assert result["updatedAt"] == "2026-06-01T10:00:00+00:00"  # health generated_at is 10:00:05
    assert result["telemetryAgeSeconds"] == 3.0


def test_energy_center_overview_day_totals_missing_without_points_not_zero(monkeypatch):
    _patch_sources(monkeypatch)
    session = FakeSession([("power_curve_points", FakeResult(rows=[])), ("slot_plans", FakeResult(rows=[]))])

    result = run(dashboard_router.energy_center_overview(session))

    for key in ("pvKwh", "homeKwh", "gridImportKwh", "gridExportKwh", "batteryChargeKwh", "batteryDischargeKwh"):
        assert result["today"][key]["value"] is None
        assert result["today"][key]["quality"] == "missing"
    assert result["today"]["selfSufficiencyPct"]["value"] is None
    assert result["today"]["selfSufficiencyPct"]["quality"] == "missing"


def test_energy_center_overview_day_total_with_gap_is_estimated_with_note(monkeypatch):
    _patch_sources(monkeypatch)
    rows = [
        _curve_row(datetime(2026, 6, 1, 6, 0), "solar", 1000),
        _curve_row(datetime(2026, 6, 1, 7, 0), "solar", 1000),
        _curve_row(datetime(2026, 6, 1, 10, 0), "solar", 1000),  # 3 h gap is not bridged
    ]
    session = FakeSession([("power_curve_points", FakeResult(rows=rows)), ("slot_plans", FakeResult(rows=[]))])

    result = run(dashboard_router.energy_center_overview(session))

    assert result["today"]["pvKwh"]["value"] == 1.0
    assert result["today"]["pvKwh"]["quality"] == "estimated"
    assert "180 min" in result["today"]["pvKwh"]["note"]


def test_energy_center_overview_soc_alert_carries_observed_and_threshold(monkeypatch):
    _patch_sources(monkeypatch, soc=14, min_soc=15)

    result = run(dashboard_router.energy_center_overview(_session_with_curve_points()))

    alert = next(a for a in result["alerts"] if a["id"] == "battery-soc-below-floor")
    assert alert["observed"] == {"value": 14, "unit": "%"}
    assert alert["threshold"] == {"value": 15, "unit": "%", "kind": "minimum"}


def test_energy_center_overview_extra_blocks_co2_sun_goals_weather(monkeypatch):
    _patch_sources(monkeypatch)

    result = run(dashboard_router.energy_center_overview(_session_with_curve_points()))

    assert result["co2SavedKg"]["unit"] == "kg"
    assert result["co2SavedKg"]["value"] == round(result["today"]["pvKwh"]["value"] * 0.39, 2)
    assert result["sun"]["sunrise"] < result["sun"]["sunset"]
    assert result["weather"] is None  # no provider: unavailable, never invented
    assert result["goals"] == {"selfSufficiencyPct": 70.0, "consumptionKwh": 8.0}
    assert result["today"]["supplyMix"] is not None
    assert round(sum(p["pct"] for p in result["today"]["supplyMix"]["parts"].values())) == 100


def test_energy_center_overview_supply_mix_unavailable_without_data(monkeypatch):
    _patch_sources(monkeypatch)
    session = FakeSession([("power_curve_points", FakeResult(rows=[])), ("slot_plans", FakeResult(rows=[]))])

    result = run(dashboard_router.energy_center_overview(session))

    assert result["today"]["supplyMix"] is None
    assert result["co2SavedKg"]["value"] is None
