from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from ingestion.sensors.dsmr import (
    DELIVERED_TOPIC,
    PHASE_DELIVERED_TOPICS,
    PHASE_RETURNED_TOPICS,
    P1Reader,
    RETURNED_TOPIC,
    TIMESTAMP_TOPIC,
)


def _message(topic: str, payload: str) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=payload.encode())


def _feed_required(reader: P1Reader, *, delivered_kw: float, returned_kw: float) -> None:
    values = {
        DELIVERED_TOPIC: delivered_kw,
        RETURNED_TOPIC: returned_kw,
        TIMESTAMP_TOPIC: "2026-06-24T20:15:00+00:00",
        PHASE_DELIVERED_TOPICS["L1"]: delivered_kw,
        PHASE_DELIVERED_TOPICS["L2"]: 0,
        PHASE_DELIVERED_TOPICS["L3"]: 0,
        PHASE_RETURNED_TOPICS["L1"]: returned_kw,
        PHASE_RETURNED_TOPICS["L2"]: 0,
        PHASE_RETURNED_TOPICS["L3"]: 0,
    }
    for topic, value in values.items():
        reader._on_message(None, None, _message(topic, str(value)))


def test_p1_reader_reports_positive_net_power_for_grid_import() -> None:
    updates = []
    reader = P1Reader("broker", 1883, lambda *args: updates.append(args))

    _feed_required(reader, delivered_kw=1.4, returned_kw=0.0)

    net_power_w, per_phase_w, timestamp, delivered_w, returned_w = updates[-1]
    assert net_power_w == 1400
    assert per_phase_w["L1"] == 1400
    assert timestamp == datetime(2026, 6, 24, 20, 15, tzinfo=timezone.utc)
    assert delivered_w == 1400
    assert returned_w == 0


def test_p1_reader_reports_negative_net_power_for_grid_export() -> None:
    updates = []
    reader = P1Reader("broker", 1883, lambda *args: updates.append(args))

    _feed_required(reader, delivered_kw=0.0, returned_kw=1.4)

    net_power_w, per_phase_w, _timestamp, delivered_w, returned_w = updates[-1]
    assert net_power_w == -1400
    assert per_phase_w["L1"] == -1400
    assert delivered_w == 0
    assert returned_w == 1400
