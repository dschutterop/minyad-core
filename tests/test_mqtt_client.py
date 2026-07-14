from typing import ClassVar

from shared.mqtt_client import MinyadMqttClient, MqttConfig


class FakeThread:
    created: ClassVar[list] = []

    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        FakeThread.created.append(self)

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


def test_start_uses_resilient_background_connector(monkeypatch):
    FakeThread.created.clear()
    monkeypatch.setattr("shared.mqtt_client.Thread", FakeThread)
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))

    client.start()
    client.start()

    assert len(FakeThread.created) == 1
    thread = FakeThread.created[0]
    assert thread.target == client.connect_forever
    assert thread.name == "minyad-control-mqtt-connect"
    assert thread.daemon is True
    assert thread.started is True


def test_connection_failure_log_omits_traceback_at_warning(caplog):
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))
    client._connect_attempt_count = 3

    with caplog.at_level("WARNING", logger="shared.mqtt_client"):
        client._log_connection_failure(OSError("temporary DNS failure"))

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert "MQTT connection attempt failed; retrying in 5s" in record.message
    assert "client_id=minyad-control" in record.message
    assert "attempt=3" in record.message
    assert record.exc_info is None


def test_publish_forwards_topic_payload_qos_and_retain():
    client = MinyadMqttClient("minyad-test-client", MqttConfig(host="broker", port=1883, keepalive=30))
    calls = []

    class Result:
        mid = 7
        rc = 0

    def fake_publish(topic, *, payload, qos, retain):
        calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})
        return Result()

    client.client.publish = fake_publish

    client.publish("minyad/trade/prices/da/2026-06-25/full", "[]", retain=True, qos=1)

    assert calls == [{
        "topic": "minyad/trade/prices/da/2026-06-25/full",
        "payload": "[]",
        "qos": 1,
        "retain": True,
    }]


def test_client_configures_mqtt_credentials():
    client = MinyadMqttClient(
        "minyad-control",
        MqttConfig(
            host="broker",
            port=1883,
            keepalive=30,
            username="minyad",
            password="secret",
        ),
    )

    assert client.client._username == b"minyad"
    assert client.client._password == b"secret"


def test_connection_callbacks_update_state_and_resubscribe():
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))
    subscribed = []
    client.subscribe("minyad/battery/+", lambda topic, payload: None)
    client.client.subscribe = lambda topic: subscribed.append(topic)

    client._on_connect(client.client, None, None, "Success", None)

    assert client.is_connected
    assert client.connection_info()["connect_count"] == 1
    assert client.connection_info()["last_connect_at"] is not None
    assert subscribed == ["minyad/battery/+"]

    client._on_disconnect(client.client, None, None, "Normal", None)

    assert not client.is_connected
    assert client.connection_info()["disconnect_count"] == 1
    assert client.connection_info()["last_disconnect_at"] is not None


def test_on_message_routes_matching_subscriptions_only():
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))
    seen = []
    client.subscribe("minyad/battery/+", lambda topic, payload: seen.append(("battery", topic, payload)))
    client.subscribe("minyad/grid/net_power_w", lambda topic, payload: seen.append(("grid", topic, payload)))

    message = type("Message", (), {"topic": "minyad/battery/soc", "payload": b"61", "qos": 0, "retain": False})()
    client._on_message(client.client, None, message)

    assert seen == [("battery", "minyad/battery/soc", b"61")]


def test_subscribe_registers_handler_and_forwards_to_client():
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))
    calls = []
    client.client.subscribe = lambda topic: calls.append(topic) or (0, 99)

    def handler(topic, payload):
        return None

    client.subscribe("minyad/grid/net_power_w", handler)

    assert client._subscriptions["minyad/grid/net_power_w"] is handler
    assert calls == ["minyad/grid/net_power_w"]


def test_publish_measurement_builds_minyad_topic():
    client = MinyadMqttClient("minyad-control", MqttConfig(host="broker", port=1883, keepalive=30))
    calls = []

    class Result:
        mid = 8
        rc = 0

    client.client.publish = lambda topic, *, payload, qos, retain: calls.append(
        {"topic": topic, "payload": payload, "qos": qos, "retain": retain}
    ) or Result()

    client.publish_measurement("battery", "soc", 61.5)

    assert calls == [{"topic": "minyad/battery/soc", "payload": "61.5", "qos": 0, "retain": False}]
