from datetime import UTC, datetime
from types import SimpleNamespace

from minyad.control.loop import decide
from minyad.ingest.dsmr import parse_dsmr_message, parse_dsmr_payload
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


def test_parse_dsmr_json_current_power_uses_kilowatts():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","electricity_currently_delivered":2.734,"electricity_currently_returned":0.0}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 2734
    assert reading["export_w"] == 0


def test_parse_dsmr_json_power_delivered_aliases_use_kilowatts():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","power_delivered":2.634,"power_returned":0.0}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 2634
    assert reading["export_w"] == 0


def test_parse_dsmr_json_active_power_w_splits_signed_net_power():
    import_payload = b'{"timestamp":"2026-06-15T22:57:05Z","active_power_w":2634}'
    export_payload = b'{"timestamp":"2026-06-15T22:57:05Z","active_power_w":-512}'

    import_reading = parse_dsmr_payload(import_payload)
    export_reading = parse_dsmr_payload(export_payload)

    assert import_reading["import_w"] == 2634
    assert import_reading["export_w"] == 0
    assert export_reading["import_w"] == 0
    assert export_reading["export_w"] == 512


def test_parse_dsmr_json_current_power_accepts_unit_strings():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","electricity_currently_delivered":"2.634 kW","electricity_currently_returned":"0.0 kW"}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 2634
    assert reading["export_w"] == 0


def test_parse_dsmr_json_active_power_uses_kilowatts_when_unitless():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","active_power":1.024}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 1024
    assert reading["export_w"] == 0


def test_parse_dsmr_json_home_assistant_power_consumption_aliases():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","electricity_meter":{"power_consumption":"1.001 kW","power_production":"0.000 kW"}}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 1000
    assert reading["export_w"] == 0


def test_parse_dsmr_json_nested_value_units():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","electricity_currently_delivered":{"value":734,"unit":"W"},"electricity_currently_returned":{"value":0.125,"unit":"kW"}}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 734
    assert reading["export_w"] == 0


def test_parse_dsmr_json_consumption_production_power_aliases():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","consumption":{"power":{"value":1001,"unit":"W"}},"production":{"power":"0.250 kW"}}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 1001
    assert reading["export_w"] == 0


def test_parse_dsmr_scalar_import_topic_uses_topic_context():
    reading = parse_dsmr_message("dsmr/reading/electricity_currently_delivered", b"2.734")
    assert reading["import_w"] == 2734
    assert reading["export_w"] == 0


def test_parse_dsmr_scalar_export_topic_uses_topic_context():
    reading = parse_dsmr_message("dsmr/reading/electricity_currently_returned", b"0.125")
    assert reading["import_w"] == 0
    assert reading["export_w"] == 125



def test_dsmr_current_power_state_merges_separate_current_topics():
    from minyad.ingest.dsmr import DsmrCurrentPowerState

    state = DsmrCurrentPowerState()

    delivered = state.merge(
        parse_dsmr_message("dsmr/reading/electricity_currently_delivered", b"2.734")
    )
    returned_zero = state.merge(
        parse_dsmr_message("dsmr/reading/electricity_currently_returned", b"0.0")
    )
    returned = state.merge(
        parse_dsmr_message("dsmr/reading/electricity_currently_returned", b"0.125")
    )
    delivered_zero = state.merge(
        parse_dsmr_message("dsmr/reading/electricity_currently_delivered", b"0.0")
    )

    assert delivered["import_w"] == 2734
    assert delivered["export_w"] == 0
    assert returned_zero["import_w"] == 2734
    assert returned_zero["export_w"] == 0
    assert returned["import_w"] == 0
    assert returned["export_w"] == 125
    assert delivered_zero["import_w"] == 0
    assert delivered_zero["export_w"] == 125


def test_parse_dsmr_json_current_power_is_exclusive():
    payload = b'{"timestamp":"2026-06-15T22:57:05Z","electricity_currently_delivered":0.050,"electricity_currently_returned":0.125}'
    reading = parse_dsmr_payload(payload)
    assert reading["import_w"] == 0
    assert reading["export_w"] == 125

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
    monkeypatch.setattr(
        client, "_control_request", lambda *args, **kwargs: sent.append((args, kwargs)) or {}
    )

    assert client.set_production_limit(0) is True
    assert client.set_production_limit(100) is False
    assert len(sent) == 1


def test_env_booleans_control_integration_toggles():
    from minyad.common.config import AppConfig

    config = AppConfig(
        _env_file=None,
        DSMR_INGESTION_ENABLED="false",
        ENPHASE_INGESTION_ENABLED="false",
        ENPHASE_STEERING_ENABLED="false",
        GOODWE_INGESTION_ENABLED="true",
        GOODWE_STEERING_ENABLED="false",
        DEBUG_MESSAGES="true",
    )

    assert config.dsmr_ingestion_enabled is False
    assert config.enphase_ingestion_enabled is False
    assert config.enphase_steering_enabled is False
    assert config.goodwe_ingestion_enabled is True
    assert config.goodwe_steering_enabled is False
    assert config.debug_messages is True


def test_disabled_goodwe_client_skips_steering_calls(caplog):
    from minyad.control.loop import DisabledGoodWeClient

    client = DisabledGoodWeClient()
    with caplog.at_level("INFO"):
        client.set_charge_power(1200)
        client.set_discharge_power(500)
        client.set_idle()

    assert "skipping charge target 1200W" in caplog.text
    assert "skipping discharge target 500W" in caplog.text
    assert "skipping idle command" in caplog.text


def test_dsmr_mqtt_debug_enables_paho_logger():
    from minyad.ingest.dsmr import _configure_mqtt_debug

    class FakeMqttClient:
        def __init__(self):
            self.logger = None

        def enable_logger(self, logger):
            self.logger = logger

    client = FakeMqttClient()
    _configure_mqtt_debug(client, True)

    assert client.logger.name == "minyad.ingest.dsmr.mqtt"


def test_dsmr_mqtt_debug_disabled_leaves_paho_logger_off():
    from minyad.ingest.dsmr import _configure_mqtt_debug

    class FakeMqttClient:
        def __init__(self):
            self.enabled = False

        def enable_logger(self, logger):
            self.enabled = True

    client = FakeMqttClient()
    _configure_mqtt_debug(client, False)

    assert client.enabled is False


def test_dsmr_subscription_topics_include_base_and_descendants():
    from minyad.ingest.dsmr import _dsmr_subscription_topics

    assert _dsmr_subscription_topics("dsmr/reading") == ["dsmr/reading", "dsmr/reading/#"]
    assert _dsmr_subscription_topics("dsmr/reading/") == ["dsmr/reading", "dsmr/reading/#"]


def test_dsmr_subscription_topics_preserve_explicit_wildcards():
    from minyad.ingest.dsmr import _dsmr_subscription_topics

    assert _dsmr_subscription_topics("dsmr/+/power") == ["dsmr/+/power"]
    assert _dsmr_subscription_topics("dsmr/#") == ["dsmr/#"]
