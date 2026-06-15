from datetime import UTC, datetime
from types import SimpleNamespace

from minyad.control.loop import decide
from minyad.ingest.dsmr import parse_dsmr_payload
from minyad.integrations.enphase import POWER_STATUS_PATH, EnphaseClient, EnphasePowerStatus


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


class FakeGoodWeClient:
    def __init__(self):
        self.calls = []

    def set_charge_power(self, watts):
        self.calls.append(("charge", watts))

    def set_discharge_power(self, watts):
        self.calls.append(("discharge", watts))

    def set_idle(self):
        self.calls.append(("idle", None))


class FakeEnphaseCurtailmentClient:
    def __init__(self):
        self.limits = []

    def set_production_limit(self, percent):
        self.limits.append(percent)
        return True


def test_apply_decision_curtail_solar_uses_enphase_limit_interface():
    from minyad.control.loop import Decision, apply_decision

    goodwe = FakeGoodWeClient()
    enphase = FakeEnphaseCurtailmentClient()
    actual = apply_decision(goodwe, Decision("zero_export", "curtail_solar", 500, {}), enphase)
    assert actual == 0
    assert goodwe.calls == [("idle", None)]
    assert enphase.limits == [0]


def test_enphase_hard_curtailment_payload_and_status_mapping(monkeypatch):
    config = SimpleNamespace(
        envoy_host="envoy.local",
        envoy_username="installer",
        envoy_password="secret",
        enphase_gateway_ip="192.0.2.10",
        enphase_verify_tls=False,
        enphase_switch_hysteresis_s=600,
        http_timeout_s=5,
        enphase_token="jwt-token",
        curtailment_granular_enabled=False,
    )
    client = EnphaseClient(config)
    requests_sent = []

    def fake_control_request(method, path, **kwargs):
        requests_sent.append((method, path, kwargs))
        if method == "GET":
            return {"powerForcedOff": False}
        return {}

    monkeypatch.setattr(client, "_control_request", fake_control_request)
    assert client.set_production_limit(0) is True
    assert requests_sent[-1] == (
        "PUT",
        POWER_STATUS_PATH,
        {"json": {"length": 1, "arr": [{"phase": "ph-a", "expectedEnergyFlag": 0}]}},
    )


def test_enphase_hysteresis_blocks_fast_reverse_switch(monkeypatch):
    config = SimpleNamespace(
        envoy_host="envoy.local",
        envoy_username="installer",
        envoy_password="secret",
        enphase_gateway_ip="192.0.2.10",
        enphase_verify_tls=False,
        enphase_switch_hysteresis_s=600,
        http_timeout_s=5,
        enphase_token="jwt-token",
        curtailment_granular_enabled=False,
    )
    client = EnphaseClient(config)
    sent = []
    statuses = [EnphasePowerStatus(False, {}), EnphasePowerStatus(True, {})]
    times = iter([1000.0, 1001.0])

    monkeypatch.setattr(client, "get_power_status", lambda: statuses.pop(0))
    monkeypatch.setattr("minyad.integrations.enphase.time.monotonic", lambda: next(times))
    monkeypatch.setattr(client, "_control_request", lambda *args, **kwargs: sent.append((args, kwargs)) or {})

    assert client.set_production_limit(0) is True
    assert client.set_production_limit(100) is False
    assert len(sent) == 1
