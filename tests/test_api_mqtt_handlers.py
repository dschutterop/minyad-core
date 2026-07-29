"""Tests for api.mqtt_handlers: MQTT message parsing/validation and settings publishing.

Covers the malformed-input branches of handle_trade_price_mqtt (bad topic shape, invalid
JSON, non-list payload, malformed price points) that test_trade_prices.py's happy-path test
doesn't reach, plus handle_status_mqtt, the settings publishers, and build_health_status's
degraded-state branches. collect_retained_mqtt_status (a live MQTT connect-and-wait loop) is
intentionally not unit tested here — see the note above its section.
"""

import json
import logging
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api import mqtt_handlers
from api.state import (
    MQTT_EVENTS,
    MQTT_STATUS,
    MQTT_STATUS_LOCK,
    TRADE_PRICE_CACHE,
    TRADE_PRICE_CACHE_LOCK,
)


def _clear_trade_cache():
    with TRADE_PRICE_CACHE_LOCK:
        TRADE_PRICE_CACHE.clear()


def _clear_status():
    with MQTT_STATUS_LOCK:
        MQTT_STATUS.clear()
    MQTT_EVENTS.clear()


# --------------------------------------------------------------------------- #
# handle_trade_price_mqtt — malformed-input branches
# --------------------------------------------------------------------------- #
def test_handle_trade_price_mqtt_ignores_wrong_topic_shape():
    _clear_trade_cache()
    mqtt_handlers.handle_trade_price_mqtt("minyad/trade/prices/da/2026-06-25/summary", b"[]")
    assert mqtt_handlers.latest_trade_prices() == []


def test_handle_trade_price_mqtt_ignores_wrong_prefix():
    _clear_trade_cache()
    mqtt_handlers.handle_trade_price_mqtt("other/trade/prices/da/2026-06-25/full", b"[]")
    assert mqtt_handlers.latest_trade_prices() == []


def test_handle_trade_price_mqtt_logs_and_ignores_invalid_json(caplog):
    _clear_trade_cache()
    with caplog.at_level(logging.WARNING):
        mqtt_handlers.handle_trade_price_mqtt("minyad/trade/prices/da/2026-06-25/full", b"{not json")
    assert mqtt_handlers.latest_trade_prices() == []
    assert "invalid day-ahead price payload" in caplog.text


def test_handle_trade_price_mqtt_logs_and_ignores_non_list_payload(caplog):
    _clear_trade_cache()
    with caplog.at_level(logging.WARNING):
        mqtt_handlers.handle_trade_price_mqtt(
            "minyad/trade/prices/da/2026-06-25/full", json.dumps({"not": "a list"}).encode()
        )
    assert mqtt_handlers.latest_trade_prices() == []
    assert "non-list day-ahead price payload" in caplog.text


def test_handle_trade_price_mqtt_skips_malformed_points_but_keeps_valid_ones():
    _clear_trade_cache()
    payload = [
        "not a dict",
        {"starts_at": "2026-06-25T01:00:00+02:00"},  # missing price_eur_kwh
        {"price_eur_kwh": "not-a-number", "starts_at": "2026-06-25T02:00:00+02:00"},
        {"price_eur_kwh": 0.15, "starts_at": "2026-06-25T03:00:00+02:00"},
    ]
    mqtt_handlers.handle_trade_price_mqtt(
        "minyad/trade/prices/da/2026-06-25/full", json.dumps(payload).encode()
    )
    prices = mqtt_handlers.latest_trade_prices()
    assert len(prices) == 1
    assert prices[0]["price_eur_kwh"] == 0.15


# --------------------------------------------------------------------------- #
# handle_status_mqtt / latest_mqtt_status
# --------------------------------------------------------------------------- #
def test_handle_status_mqtt_ignores_unsupported_topic():
    _clear_status()
    mqtt_handlers.handle_status_mqtt("minyad/unknown/thing", b"42")
    assert mqtt_handlers.latest_mqtt_status() == {}
    assert len(MQTT_EVENTS) == 0


def test_handle_status_mqtt_records_status_and_event():
    _clear_status()
    mqtt_handlers.handle_status_mqtt("minyad/battery/soc", b"77")
    status = mqtt_handlers.latest_mqtt_status()
    assert status["soc"] == "77"
    assert len(MQTT_EVENTS) == 1
    assert MQTT_EVENTS[-1]["topic"] == "minyad/battery/soc"


def test_latest_mqtt_status_returns_a_copy_not_the_live_dict():
    _clear_status()
    mqtt_handlers.handle_status_mqtt("minyad/battery/soc", b"50")
    snapshot = mqtt_handlers.latest_mqtt_status()
    snapshot["soc"] = "mutated"
    assert mqtt_handlers.latest_mqtt_status()["soc"] == "50"


# --------------------------------------------------------------------------- #
# collect_retained_mqtt_status
#
# This function opens a real MQTT connection and blocks on an Event with a timeout — its
# happy path is a thin, mostly-untestable wrapper around paho's connect/subscribe/on_message
# plumbing, and faking that faithfully would mostly test the fake rather than our code. The
# one behavior worth locking down here is the OSError contract: battery.py's battery_status
# and household_status_payload both specifically catch OSError from this call as their
# "MQTT broker unreachable" fallback signal, so a connection failure must (a) still raise
# OSError and (b) record it in LAST_RETAINED_FETCH for the /health endpoint.
# --------------------------------------------------------------------------- #
def test_collect_retained_mqtt_status_records_and_reraises_on_connection_failure(monkeypatch):
    class _FailingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def username_pw_set(self, *_args, **_kwargs):
            pass

        def connect(self, *_args, **_kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(mqtt_handlers.paho_mqtt, "Client", _FailingClient)
    mqtt_handlers.LAST_RETAINED_FETCH.clear()

    try:
        mqtt_handlers.collect_retained_mqtt_status(timeout_seconds=0.01)
        raised = False
    except OSError:
        raised = True

    assert raised
    assert mqtt_handlers.LAST_RETAINED_FETCH["success"] is False
    assert "connection refused" in mqtt_handlers.LAST_RETAINED_FETCH["error"]


# --------------------------------------------------------------------------- #
# publish_trade_mqtt_settings / publish_battery_mqtt_settings
# --------------------------------------------------------------------------- #
def test_publish_trade_mqtt_settings_publishes_only_keys_present(monkeypatch):
    published = []
    monkeypatch.setattr(
        mqtt_handlers.mqtt.client, "publish", lambda topic, payload=None, qos=0, retain=False: published.append((topic, payload))
    )
    mqtt_handlers.publish_trade_mqtt_settings({"bidding_zone": "NL", "unrelated_key": "ignored"})
    topics = [topic for topic, _ in published]
    assert topics == [mqtt_handlers.MQTT_TRADE_SETTING_TOPICS["bidding_zone"]]


def test_publish_battery_mqtt_settings_publishes_only_keys_present(monkeypatch):
    published = []
    monkeypatch.setattr(
        mqtt_handlers.mqtt.client, "publish", lambda topic, payload=None, qos=0, retain=False: published.append((topic, payload))
    )
    mqtt_handlers.publish_battery_mqtt_settings({"soc_floor": 20, "unrelated_key": "ignored"})
    topics = [topic for topic, _ in published]
    assert topics == [mqtt_handlers.MQTT_BATTERY_SETTING_TOPICS["soc_floor"]]


# --------------------------------------------------------------------------- #
# build_health_status — degraded-state branches
# --------------------------------------------------------------------------- #
def test_build_health_status_reports_db_error(monkeypatch):
    monkeypatch.setattr(mqtt_handlers.mqtt, "connection_info", lambda: {"host": "mqtt", "port": 1883, "connected": True})
    payload = mqtt_handlers.build_health_status({}, db_ok=False, db_error="connection refused")
    assert payload["status"] == "error"
    db_component = next(c for c in payload["components"] if c["name"] == "PostgreSQL")
    assert db_component["status"] == "error"
    assert "connection refused" in db_component["detail"]


def test_build_health_status_reports_mqtt_disconnected():
    with mqtt_handlers.TRADE_PRICE_CACHE_LOCK:
        mqtt_handlers.TRADE_PRICE_CACHE.clear()
    payload = mqtt_handlers.build_health_status({}, db_ok=True)
    mqtt_component = next(c for c in payload["components"] if c["name"] == "MQTT broker")
    # the real (unconnected) test-time paho client reports connected=False
    assert mqtt_component["status"] == "error"
    assert payload["status"] == "error"


def test_build_health_status_warns_when_no_trade_prices_cached(monkeypatch):
    with mqtt_handlers.TRADE_PRICE_CACHE_LOCK:
        mqtt_handlers.TRADE_PRICE_CACHE.clear()
    monkeypatch.setattr(mqtt_handlers.mqtt, "connection_info", lambda: {"host": "mqtt", "port": 1883, "connected": True})
    payload = mqtt_handlers.build_health_status({}, db_ok=True)
    trade_component = next(c for c in payload["components"] if c["name"] == "Trade prices")
    assert trade_component["status"] == "warning"
    assert payload["status"] == "warning"
