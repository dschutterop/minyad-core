from datetime import UTC

from minyad.sensors import dsmr


class Message:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


def publish(reader: dsmr.P1Reader, topic: str, payload: str) -> None:
    reader._on_message(reader._client, None, Message(topic, payload.encode()))


def publish_all(reader: dsmr.P1Reader) -> None:
    publish(reader, dsmr.GRID_DELIVERED_TOPIC, "0.000")
    publish(reader, dsmr.GRID_RETURNED_TOPIC, "0.994")
    publish(reader, dsmr.PHASE_DELIVERED_TOPICS["L1"], "0.100")
    publish(reader, dsmr.PHASE_RETURNED_TOPICS["L1"], "0.000")
    publish(reader, dsmr.PHASE_DELIVERED_TOPICS["L2"], "0.000")
    publish(reader, dsmr.PHASE_RETURNED_TOPICS["L2"], "1.068")
    publish(reader, dsmr.PHASE_DELIVERED_TOPICS["L3"], "0.200")
    publish(reader, dsmr.PHASE_RETURNED_TOPICS["L3"], "0.000")


def test_p1_reader_emits_signed_grid_and_per_phase_power_after_required_topics():
    updates = []
    reader = dsmr.P1Reader("192.168.110.2", 1883, lambda *args: updates.append(args))

    publish(reader, dsmr.TIMESTAMP_TOPIC, "2026-06-17T12:34:56+02:00")
    publish_all(reader)

    net_power_w, per_phase_w, timestamp = updates[-1]
    assert net_power_w == 994
    assert per_phase_w == {"L1": -100, "L2": 1068, "L3": -200}
    assert timestamp.isoformat() == "2026-06-17T10:34:56+00:00"


def test_p1_reader_uses_current_utc_time_when_timestamp_not_received():
    updates = []
    reader = dsmr.P1Reader("192.168.110.2", 1883, lambda *args: updates.append(args))

    publish_all(reader)

    assert updates[-1][0] == 994
    assert updates[-1][2].tzinfo is UTC


def test_p1_reader_discards_malformed_payloads_without_emitting(caplog):
    updates = []
    reader = dsmr.P1Reader("192.168.110.2", 1883, lambda *args: updates.append(args))

    publish(reader, dsmr.GRID_DELIVERED_TOPIC, "not-a-float")
    publish_all(reader)

    assert len(updates) == 1
    assert "Discarding malformed DSMR power payload" in caplog.text
