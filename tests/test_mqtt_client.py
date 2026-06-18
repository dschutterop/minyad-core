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
