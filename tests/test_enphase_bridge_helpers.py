"""Tests for pure configuration/parsing helpers in host-services/enphase_bridge.

Reuses the import-stub-backed module load from test_enphase_bridge so the bridge
module imports cleanly without the real requests/paho/dotenv dependencies.
"""

import pytest

from tests.test_enphase_bridge import enphase_bridge


# --------------------------------------------------------------------------- #
# _get_env_int / _get_env_float
# --------------------------------------------------------------------------- #
def test_get_env_int_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOME_INT", raising=False)
    assert enphase_bridge._get_env_int("SOME_INT", 7) == 7


def test_get_env_int_uses_default_when_empty(monkeypatch):
    monkeypatch.setenv("SOME_INT", "")
    assert enphase_bridge._get_env_int("SOME_INT", 7) == 7


def test_get_env_int_parses_value(monkeypatch):
    monkeypatch.setenv("SOME_INT", "42")
    assert enphase_bridge._get_env_int("SOME_INT", 7) == 42


def test_get_env_int_rejects_invalid(monkeypatch):
    monkeypatch.setenv("SOME_INT", "not-int")
    with pytest.raises(ValueError):
        enphase_bridge._get_env_int("SOME_INT", 7)


def test_get_env_float_default_and_parse(monkeypatch):
    monkeypatch.delenv("SOME_FLOAT", raising=False)
    assert enphase_bridge._get_env_float("SOME_FLOAT", 1.5) == 1.5
    monkeypatch.setenv("SOME_FLOAT", "2.25")
    assert enphase_bridge._get_env_float("SOME_FLOAT", 1.5) == 2.25


def test_get_env_float_rejects_invalid(monkeypatch):
    monkeypatch.setenv("SOME_FLOAT", "abc")
    with pytest.raises(ValueError):
        enphase_bridge._get_env_float("SOME_FLOAT", 1.5)


# --------------------------------------------------------------------------- #
# _get_required_env
# --------------------------------------------------------------------------- #
def test_get_required_env_strips_value(monkeypatch):
    monkeypatch.setenv("REQ", "  host  ")
    assert enphase_bridge._get_required_env("REQ") == "host"


@pytest.mark.parametrize("value", ["", "   "])
def test_get_required_env_rejects_blank(monkeypatch, value):
    monkeypatch.setenv("REQ", value)
    with pytest.raises(ValueError):
        enphase_bridge._get_required_env("REQ")


def test_get_required_env_rejects_missing(monkeypatch):
    monkeypatch.delenv("REQ", raising=False)
    with pytest.raises(ValueError):
        enphase_bridge._get_required_env("REQ")


# --------------------------------------------------------------------------- #
# read_enphase_token
# --------------------------------------------------------------------------- #
def test_read_enphase_token_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("ENPHASE_TOKEN_FILE", str(tmp_path / "nope.token"))
    with pytest.raises(ValueError):
        enphase_bridge.read_enphase_token()


def test_read_enphase_token_empty_file_raises(monkeypatch, tmp_path):
    token_file = tmp_path / ".token"
    token_file.write_text("   \n")
    monkeypatch.setenv("ENPHASE_TOKEN_FILE", str(token_file))
    with pytest.raises(ValueError):
        enphase_bridge.read_enphase_token()


# --------------------------------------------------------------------------- #
# Config.from_env
# --------------------------------------------------------------------------- #
def _clear_config_env(monkeypatch):
    for key in (
        "MQTT_BROKER", "MQTT_HOST", "ENPHASE_ENVOY_HOST", "ENPHASE_ENVOY_TIMEOUT",
        "MQTT_PORT", "MQTT_USER", "MQTT_PASS", "LOG_LEVEL",
        "ENPHASE_PRODUCTION_POLL_INTERVAL", "ENPHASE_INVERTER_POLL_INTERVAL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_from_env_requires_mqtt_broker(monkeypatch):
    _clear_config_env(monkeypatch)
    monkeypatch.setenv("ENPHASE_ENVOY_HOST", "envoy.local")
    with pytest.raises(ValueError, match="MQTT_BROKER is required"):
        enphase_bridge.Config.from_env()


def test_config_from_env_builds_config_with_defaults(monkeypatch):
    _clear_config_env(monkeypatch)
    monkeypatch.setenv("MQTT_BROKER", "broker.local")
    monkeypatch.setenv("ENPHASE_ENVOY_HOST", "envoy.local")
    config = enphase_bridge.Config.from_env()
    assert config.mqtt_host == "broker.local"
    assert config.envoy_host == "envoy.local"
    assert config.mqtt_port == 1883
    assert config.envoy_timeout == 10.0
    assert config.production_poll_interval == 10
    assert config.inverter_poll_interval == 60
    assert config.mqtt_user is None


def test_config_from_env_rejects_non_positive_poll_intervals(monkeypatch):
    _clear_config_env(monkeypatch)
    monkeypatch.setenv("MQTT_BROKER", "broker.local")
    monkeypatch.setenv("ENPHASE_ENVOY_HOST", "envoy.local")
    monkeypatch.setenv("ENPHASE_PRODUCTION_POLL_INTERVAL", "0")
    with pytest.raises(ValueError, match="PRODUCTION_POLL_INTERVAL"):
        enphase_bridge.Config.from_env()


def test_config_from_env_rejects_non_positive_inverter_interval(monkeypatch):
    _clear_config_env(monkeypatch)
    monkeypatch.setenv("MQTT_BROKER", "broker.local")
    monkeypatch.setenv("ENPHASE_ENVOY_HOST", "envoy.local")
    monkeypatch.setenv("ENPHASE_INVERTER_POLL_INTERVAL", "0")
    with pytest.raises(ValueError, match="INVERTER_POLL_INTERVAL"):
        enphase_bridge.Config.from_env()


# --------------------------------------------------------------------------- #
# unix_to_iso
# --------------------------------------------------------------------------- #
def test_unix_to_iso_converts_epoch():
    assert enphase_bridge.unix_to_iso(0).startswith("1970-01-01T00:00:00")


def test_unix_to_iso_falls_back_on_invalid():
    # Non-numeric -> current time (just assert it is a valid ISO string with T)
    result = enphase_bridge.unix_to_iso("not-a-number")
    assert "T" in result


# --------------------------------------------------------------------------- #
# slugify_array_name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,expected",
    [
        ("South Roof", "south_roof"),
        ("  Array #1! ", "array_1"),
        ("", "unknown"),
        ("***", "unknown"),
        ("east-west", "east-west"),
    ],
)
def test_slugify_array_name(name, expected):
    assert enphase_bridge.slugify_array_name(name) == expected


# --------------------------------------------------------------------------- #
# summarize_inverter_production
# --------------------------------------------------------------------------- #
def test_summarize_inverter_production_groups_by_array():
    inverters = [
        {"serialNumber": "a", "lastReportWatts": 100, "lastReportDate": 10, "array": "South"},
        {"serialNumber": "b", "lastReportWatts": 200, "lastReportDate": 30, "array": "South"},
        {"serialNumber": "c", "lastReportWatts": 50, "lastReportDate": 20, "array": "North"},
    ]
    totals, total, latest = enphase_bridge.summarize_inverter_production(inverters)
    assert totals == {"south": 300, "north": 50}
    assert total == 350
    assert latest == 30


def test_summarize_inverter_production_skips_blank_serials():
    inverters = [{"serialNumber": "  ", "lastReportWatts": 999, "lastReportDate": 5}]
    totals, total, latest = enphase_bridge.summarize_inverter_production(inverters)
    assert totals == {}
    assert total == 0
    assert latest is None


# --------------------------------------------------------------------------- #
# set_production_limit
# --------------------------------------------------------------------------- #
def test_set_production_limit_not_implemented():
    with pytest.raises(NotImplementedError):
        enphase_bridge.set_production_limit(500)
