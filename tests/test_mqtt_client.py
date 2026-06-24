from shared.mqtt_client import MinyadMqttClient, MqttConfig


class FakeThread:
    created = []

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
    client = MinyadMqttClient("minyad-trade", MqttConfig(host="broker", port=1883, keepalive=30))
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
