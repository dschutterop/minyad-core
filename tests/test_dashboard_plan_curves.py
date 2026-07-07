import asyncio
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from datetime import datetime, timedelta, timezone

from api import main as api_main
from api.main import _classify_cloud_cover, build_plan_curves

UTC = timezone.utc


def _payload(slots):
    return {"slot_seconds": 900, "soc_start_pct": 50.0, "slots": slots}


def _slot(start, pv_w=1000, load_w=300, soc_target=50.0, cloud_cover_pct=None):
    return {
        "start": start.isoformat(),
        "pv_forecast_w": pv_w,
        "load_forecast_w": load_w,
        "soc_target_pct": soc_target,
        "curtailment_w": 0,
        "price_source": "fallback",
        "cloud_cover_pct": cloud_cover_pct,
    }


def test_classify_cloud_cover_matches_pv_uncertainty_module():
    from minyad.strategy.v3.pv_uncertainty import classify_cloud_cover

    for pct in (0.0, 10.0, 24.9, 25.0, 50.0, 74.9, 75.0, 100.0):
        assert _classify_cloud_cover(pct) == classify_cloud_cover(pct)


def test_build_plan_curves_omits_band_without_uncertainty_bands_arg():
    now_ = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    slot_start = now_
    payload = _payload([_slot(slot_start, cloud_cover_pct=10.0)])
    curves, _ = build_plan_curves(payload, 10240.0, 50.0, now_, now_ + timedelta(hours=1))
    assert curves["pv_p10_forecast"] == []
    assert curves["pv_p90_forecast"] == []


def test_build_plan_curves_omits_band_when_cloud_cover_missing():
    now_ = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    payload = _payload([_slot(now_, cloud_cover_pct=None)])
    bands = {"clear": {"p10_multiplier": 0.5, "p90_multiplier": 1.2}}
    curves, _ = build_plan_curves(payload, 10240.0, 50.0, now_, now_ + timedelta(hours=1), bands)
    assert curves["pv_p10_forecast"] == []
    assert curves["pv_p90_forecast"] == []


def test_build_plan_curves_omits_band_when_class_has_no_history():
    now_ = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    payload = _payload([_slot(now_, cloud_cover_pct=90.0)])  # cloudy
    bands = {"clear": {"p10_multiplier": 0.5, "p90_multiplier": 1.2}}  # no "cloudy" entry
    curves, _ = build_plan_curves(payload, 10240.0, 50.0, now_, now_ + timedelta(hours=1), bands)
    assert curves["pv_p10_forecast"] == []
    assert curves["pv_p90_forecast"] == []


def test_build_plan_curves_applies_band_multipliers():
    now_ = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    payload = _payload([_slot(now_, pv_w=1000, cloud_cover_pct=10.0)])  # clear
    bands = {"clear": {"p10_multiplier": 0.5, "p90_multiplier": 1.2}}
    curves, _ = build_plan_curves(payload, 10240.0, 50.0, now_, now_ + timedelta(hours=1), bands)
    assert curves["pv_p10_forecast"] == [{"timestamp": now_.isoformat(), "power_w": 500}]
    assert curves["pv_p90_forecast"] == [{"timestamp": now_.isoformat(), "power_w": 1200}]


def test_api_forecast_uses_recent_real_plan_when_latest_plan_is_fallback(monkeypatch):
    now_ = datetime.now(UTC).replace(microsecond=0)
    fallback_row = {
        "generated_at": now_,
        "valid_from": now_,
        "slot_seconds": 900,
        "payload": _payload([_slot(now_ + timedelta(minutes=15), pv_w=0)]),
        "solver_status": "FALLBACK",
    }
    real_row = {
        "generated_at": now_ - timedelta(minutes=5),
        "valid_from": now_ - timedelta(minutes=5),
        "slot_seconds": 900,
        "payload": _payload(
            [
                _slot(now_ + timedelta(minutes=15), pv_w=1200),
                _slot(now_ + timedelta(minutes=30), pv_w=1800),
            ]
        ),
        "solver_status": "OPTIMAL",
    }

    async def fake_latest_slot_plan(session, *, include_fallback=True):
        return fallback_row if include_fallback else real_row

    async def fake_battery_settings(session):
        return {"capacity_wh": 10240}

    async def fake_uncertainty_bands(session):
        return {}

    monkeypatch.setattr(api_main, "latest_slot_plan", fake_latest_slot_plan)
    monkeypatch.setattr(api_main, "battery_settings", fake_battery_settings)
    monkeypatch.setattr(api_main, "latest_pv_uncertainty_bands", fake_uncertainty_bands)
    monkeypatch.setattr(api_main, "latest_mqtt_status", lambda: {"soc": 50})

    payload = asyncio.run(api_main.api_forecast(session=object()))

    assert payload["plan_status"] == "ok"
    assert payload["points"]
    assert payload["points"][0]["power_w"] == 1200
