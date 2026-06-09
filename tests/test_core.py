import pytest

pytest.importorskip("pydantic")
pytest.importorskip("pydantic_settings")

from datetime import UTC, datetime

from minyad.control.loop import decide
from minyad.ingest.dsmr import parse_dsmr_payload


def test_parse_dsmr_telegram_power_and_counters():
    payload = b"""
/ISk5\2MT382-1000
1-0:1.8.1(00123.456*kWh)
1-0:1.8.2(00001.000*kWh)
1-0:2.8.1(00003.210*kWh)
1-0:2.8.2(00000.500*kWh)
1-0:1.7.0(00.345*kW)
1-0:2.7.0(00.012*kW)
!0000
"""
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 345
    assert reading["export_w"] == 12
    assert reading["import_kwh_t1"] == 123.456
    assert reading["export_kwh_t2"] == 0.5


def test_decision_zero_export_charges_battery():
    decision = decide(
        grid={"import_w": 0, "export_w": 350},
        solar={"production_w": 2500},
        battery={"soc_pct": 55, "charge_w": 0, "discharge_w": 0},
        settings={
            "export_tolerance_w": "50",
            "max_soc_pct": "95",
            "min_soc_pct": "15",
            "battery_max_charge_w": "4600",
        },
        forecast=[],
    )
    assert decision.trigger == "zero_export"
    assert decision.action == "charge"
    assert decision.target_w == 300


def test_low_solar_forecast_raises_evening_soc_floor():
    forecast = [
        {"timestamp_target": datetime(2026, 6, 10, hour, tzinfo=UTC), "predicted_w": 50}
        for hour in range(24)
    ]
    decision = decide(
        grid={"import_w": 800, "export_w": 0},
        solar={"production_w": 0},
        battery={"soc_pct": 25, "charge_w": 0, "discharge_w": 0},
        settings={
            "charge_threshold_w": "200",
            "min_soc_pct": "15",
            "min_forecast_soc_pct": "35",
            "low_solar_forecast_kwh": "8",
        },
        forecast=forecast,
    )
    assert decision.action == "idle"
    assert decision.details["effective_min_soc_pct"] == 35.0
