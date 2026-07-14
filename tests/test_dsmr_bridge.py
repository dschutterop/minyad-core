import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest


def install_import_stubs() -> None:
    if "dotenv" not in sys.modules:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules["dotenv"] = dotenv


install_import_stubs()

MODULE_PATH = Path(__file__).resolve().parents[1] / "host-services" / "dsmr_bridge.py"
spec = importlib.util.spec_from_file_location("dsmr_bridge", MODULE_PATH)
dsmr_bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["dsmr_bridge"] = dsmr_bridge
spec.loader.exec_module(dsmr_bridge)


class FakePublishResult:
    def __init__(self, rc=0):
        self.rc = rc


class FakeMqttClient:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.published = []
        self.subscribed = []
        self.username = None
        self.will = None
        self.connected = []
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        FakeMqttClient.instances.append(self)

    def username_pw_set(self, username, password):
        self.username = (username, password)

    def will_set(self, topic, payload, retain=False):
        self.will = (topic, payload, retain)

    def reconnect_delay_set(self, *, min_delay, max_delay):
        self.reconnect_delay = (min_delay, max_delay)

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, str(payload), retain))
        return FakePublishResult()

    def subscribe(self, subscriptions):
        self.subscribed.append(subscriptions)

    def connect_async(self, host, port, keepalive):
        self.connected.append((host, port, keepalive))

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True


def make_config(**overrides):
    values = {
        "dsmr_mqtt_host": "dsmr-broker",
        "dsmr_mqtt_port": 1883,
        "dsmr_mqtt_user": None,
        "dsmr_mqtt_pass": None,
        "minyad_mqtt_host": "minyad-broker",
        "minyad_mqtt_port": 1884,
        "minyad_mqtt_user": None,
        "minyad_mqtt_pass": None,
        "dsmr_topic_prefix": "dsmr/reading",
        "minyad_topic_prefix": "minyad/grid",
        "stale_timeout": 60,
        "dead_timeout": 300,
        "log_level": "INFO",
    }
    values.update(overrides)
    return dsmr_bridge.Config(**values)


def make_bridge(monkeypatch, **config_overrides):
    FakeMqttClient.instances = []
    monkeypatch.setattr(dsmr_bridge.mqtt, "Client", FakeMqttClient)
    monkeypatch.setattr(dsmr_bridge.mqtt, "CallbackAPIVersion", types.SimpleNamespace(VERSION2=2))
    monkeypatch.setattr(dsmr_bridge.mqtt, "MQTTv311", 4)
    monkeypatch.setattr(dsmr_bridge.mqtt, "MQTT_ERR_SUCCESS", 0)
    return dsmr_bridge.DsmrBridge(make_config(**config_overrides))


def test_config_from_env_builds_and_validates(monkeypatch):
    monkeypatch.setenv("DSMR_MQTT_BROKER", "dsmr")
    monkeypatch.setenv("MQTT_BROKER", "minyad")
    monkeypatch.setenv("DSMR_MQTT_PORT", "1885")
    monkeypatch.setenv("MQTT_PORT", "1886")
    monkeypatch.setenv("STALE_TIMEOUT", "10")
    monkeypatch.setenv("DEAD_TIMEOUT", "20")

    config = dsmr_bridge.Config.from_env()

    assert config.dsmr_mqtt_host == "dsmr"
    assert config.minyad_mqtt_host == "minyad"
    assert config.dsmr_mqtt_port == 1885
    assert config.minyad_mqtt_port == 1886
    assert config.dsmr_topic_prefix == "dsmr/reading"


def test_config_from_env_rejects_missing_and_same_broker(monkeypatch):
    monkeypatch.delenv("DSMR_MQTT_BROKER", raising=False)
    monkeypatch.delenv("DSMR_MQTT_HOST", raising=False)
    monkeypatch.setenv("MQTT_BROKER", "minyad")
    with pytest.raises(ValueError, match="DSMR_MQTT_BROKER"):
        dsmr_bridge.Config.from_env()

    monkeypatch.setenv("DSMR_MQTT_BROKER", "same")
    monkeypatch.setenv("MQTT_BROKER", "same")
    monkeypatch.setenv("DSMR_MQTT_PORT", "1883")
    monkeypatch.setenv("MQTT_PORT", "1883")
    with pytest.raises(ValueError, match="different broker"):
        dsmr_bridge.Config.from_env()


def test_get_env_int_rejects_invalid(monkeypatch):
    monkeypatch.setenv("BAD_INT", "nope")
    with pytest.raises(ValueError, match="BAD_INT"):
        dsmr_bridge._get_env_int("BAD_INT", 7)


def test_bridge_initializes_clients_and_credentials(monkeypatch):
    bridge = make_bridge(
        monkeypatch,
        dsmr_mqtt_user="source-user",
        dsmr_mqtt_pass="source-pass",
        minyad_mqtt_user="target-user",
        minyad_mqtt_pass="target-pass",
    )

    assert bridge.source_client.username == ("source-user", "source-pass")
    assert bridge.target_client.username == ("target-user", "target-pass")
    assert bridge.target_client.will == ("minyad/grid/status", dsmr_bridge.STATUS_DISCONNECTED, True)


def test_handle_message_publishes_grid_values_after_primary_pair(monkeypatch):
    bridge = make_bridge(monkeypatch)
    now_values = iter([100.0, 101.0])
    monkeypatch.setattr(dsmr_bridge.time, "monotonic", lambda: next(now_values))

    bridge.handle_message(types.SimpleNamespace(topic="dsmr/reading/electricity_currently_delivered", payload=b"1.25"))
    bridge.handle_message(types.SimpleNamespace(topic="dsmr/reading/electricity_currently_returned", payload=b"0.20"))

    published = {topic: payload for topic, payload, _ in bridge.target_client.published}
    assert published["minyad/grid/delivered_w"] == "1250"
    assert published["minyad/grid/returned_w"] == "200"
    assert published["minyad/grid/net_power_w"] == "1050"
    assert bridge.last_update_monotonic == 101.0


def test_handle_message_converts_phase_voltage_and_timestamp(monkeypatch):
    bridge = make_bridge(monkeypatch)
    monkeypatch.setattr(dsmr_bridge.time, "monotonic", lambda: 100.0)

    snapshot = {
        dsmr_bridge.PRIMARY_DELIVERED: 0.5,
        dsmr_bridge.PRIMARY_RETURNED: 0.1,
        "phase_voltage_l1": 231.234,
        "timestamp": "2026-07-03T10:00:00Z",
    }
    bridge.publish_grid_values(snapshot)

    published = {topic: payload for topic, payload, _ in bridge.target_client.published}
    assert published["minyad/grid/voltage_l1_v"] == "231.2"
    assert published["minyad/grid/timestamp"] == "2026-07-03T10:00:00Z"
    assert published["minyad/grid/net_power_w"] == "400"


def test_handle_message_ignores_unknown_and_malformed_numeric(monkeypatch):
    bridge = make_bridge(monkeypatch)

    bridge.handle_message(types.SimpleNamespace(topic="other/electricity_currently_delivered", payload=b"1.0"))
    bridge.handle_message(types.SimpleNamespace(topic="dsmr/reading/electricity_currently_delivered", payload=b"bad"))

    assert bridge.target_client.published == []
    assert bridge.state == {}


def test_current_status_transitions(monkeypatch):
    bridge = make_bridge(monkeypatch, stale_timeout=10, dead_timeout=20)
    monkeypatch.setattr(dsmr_bridge.time, "monotonic", lambda: 100.0)

    assert bridge.current_status() == dsmr_bridge.STATUS_DISCONNECTED
    bridge.source_connected = True
    bridge.target_connected = True
    bridge.last_update_monotonic = 95.0
    assert bridge.current_status() == dsmr_bridge.STATUS_OK
    bridge.last_update_monotonic = 90.0
    assert bridge.current_status() == dsmr_bridge.STATUS_STALE
    bridge.last_update_monotonic = 79.0
    assert bridge.current_status() == dsmr_bridge.STATUS_DISCONNECTED


def test_connect_callbacks_update_state_and_subscribe(monkeypatch):
    bridge = make_bridge(monkeypatch)
    reason_ok = types.SimpleNamespace(is_failure=False)
    reason_fail = types.SimpleNamespace(is_failure=True)

    bridge.on_source_connect(bridge.source_client, None, None, reason_ok, None)
    assert bridge.source_connected is True
    assert len(bridge.source_client.subscribed[0]) == len(dsmr_bridge.SUBSCRIBED_FIELDS)

    bridge.on_target_connect(bridge.target_client, None, None, reason_fail, None)
    assert bridge.target_connected is False

    bridge.on_source_disconnect(bridge.source_client, None, None, "lost", None)
    assert bridge.source_connected is False
    assert bridge.target_client.published[-1] == ("minyad/grid/status", dsmr_bridge.STATUS_DISCONNECTED, True)

    bridge.on_target_connect(bridge.target_client, None, None, reason_ok, None)
    assert bridge.target_connected is True
    bridge.on_target_disconnect(bridge.target_client, None, None, types.SimpleNamespace(value=1), None)
    assert bridge.target_connected is False


def test_publish_records_error_when_client_publish_fails(monkeypatch):
    bridge = make_bridge(monkeypatch)

    def failing_publish(topic, payload, retain=False):
        bridge.target_client.published.append((topic, str(payload), retain))
        return FakePublishResult(rc=9)

    bridge.target_client.publish = failing_publish

    bridge.publish("status", dsmr_bridge.STATUS_OK)

    assert bridge.target_client.published == [("minyad/grid/status", dsmr_bridge.STATUS_OK, True)]


def test_on_message_logs_unexpected_handler_errors(monkeypatch):
    bridge = make_bridge(monkeypatch)
    seen = []
    monkeypatch.setattr(bridge, "handle_message", lambda _message: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(dsmr_bridge.logger, "warning", lambda *args, **kwargs: seen.append((args, kwargs)))

    bridge.on_message(None, None, types.SimpleNamespace(topic="dsmr/reading/timestamp", payload=b"bad"))

    assert seen


def test_status_loop_publishes_once_and_records_publish_errors(monkeypatch):
    bridge = make_bridge(monkeypatch)
    waits = iter([False, False, True])
    warnings = []
    monkeypatch.setattr(bridge.status_stop_event, "wait", lambda _seconds: next(waits))
    monkeypatch.setattr(bridge, "current_status", lambda: dsmr_bridge.STATUS_OK)
    monkeypatch.setattr(dsmr_bridge.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs)))

    calls = []

    def publish(field, payload):
        calls.append((field, payload))
        if len(calls) == 2:
            raise RuntimeError("publish failed")

    monkeypatch.setattr(bridge, "publish", publish)

    bridge.status_loop()

    assert calls == [("status", dsmr_bridge.STATUS_OK), ("status", dsmr_bridge.STATUS_OK)]
    assert warnings


class FakeThread:
    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.joined = False

    def start(self):
        return None

    def join(self, timeout=None):
        self.joined = timeout


def test_run_starts_clients_and_cleans_up_on_shutdown(monkeypatch):
    bridge = make_bridge(monkeypatch)
    monkeypatch.setattr(dsmr_bridge.threading, "Thread", FakeThread)

    async def run_and_stop():
        task = asyncio.create_task(bridge.run())
        await asyncio.sleep(0)
        bridge.request_shutdown()
        await task

    asyncio.run(run_and_stop())

    assert bridge.status_thread.name == "dsmr-status"
    assert bridge.target_client.connected == [("minyad-broker", 1884, 60)]
    assert bridge.source_client.connected == [("dsmr-broker", 1883, 60)]
    assert bridge.target_client.loop_started
    assert bridge.source_client.loop_started
    assert bridge.target_client.loop_stopped
    assert bridge.source_client.loop_stopped
    assert bridge.target_client.disconnected
    assert bridge.source_client.disconnected
    assert bridge.target_client.published[-1] == ("minyad/grid/status", dsmr_bridge.STATUS_DISCONNECTED, True)


def test_request_shutdown_sets_event(monkeypatch):
    bridge = make_bridge(monkeypatch)
    assert not bridge.shutdown_event.is_set()
    bridge.request_shutdown()
    assert bridge.shutdown_event.is_set()
