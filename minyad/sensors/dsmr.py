"""DSMR-reader MQTT ingestion for P1 meter current power values."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)

GRID_DELIVERED_TOPIC = "dsmr/reading/electricity_currently_delivered"
GRID_RETURNED_TOPIC = "dsmr/reading/electricity_currently_returned"
PHASE_DELIVERED_TOPICS = {
    "L1": "dsmr/reading/phase_currently_delivered_l1",
    "L2": "dsmr/reading/phase_currently_delivered_l2",
    "L3": "dsmr/reading/phase_currently_delivered_l3",
}
PHASE_RETURNED_TOPICS = {
    "L1": "dsmr/reading/phase_currently_returned_l1",
    "L2": "dsmr/reading/phase_currently_returned_l2",
    "L3": "dsmr/reading/phase_currently_returned_l3",
}
TIMESTAMP_TOPIC = "dsmr/reading/timestamp"

POWER_TOPICS = (
    GRID_DELIVERED_TOPIC,
    GRID_RETURNED_TOPIC,
    *PHASE_DELIVERED_TOPICS.values(),
    *PHASE_RETURNED_TOPICS.values(),
)
TOPICS = (*POWER_TOPICS, TIMESTAMP_TOPIC)


class P1Reader:
    """Read DSMR current power values from MQTT and expose signed net watts."""

    def __init__(
        self,
        broker: str,
        port: int,
        on_update: Callable[[int, dict[str, int], datetime], None],
    ) -> None:
        self.broker = broker
        self.port = port
        self.on_update = on_update
        self._values_kw: dict[str, float] = {}
        self._timestamp: datetime | None = None
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)

    def start(self) -> None:
        """Connect to MQTT and start the background network loop."""
        self._client.connect_async(self.broker, self.port)
        self._client.loop_start()

    def stop(self) -> None:
        """Disconnect from MQTT and stop the background network loop."""
        self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        if _is_failure(reason_code):
            LOG.warning("DSMR MQTT connection returned reason code %s", reason_code)
            return
        client.subscribe([(topic, 0) for topic in TOPICS])
        LOG.info("Subscribed to %d DSMR MQTT topics", len(TOPICS))

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        if _is_failure(reason_code):
            LOG.warning("DSMR MQTT disconnected unexpectedly: %s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
        topic = message.topic
        payload = message.payload.decode("utf-8", errors="replace").strip()

        if topic == TIMESTAMP_TOPIC:
            timestamp = _parse_timestamp(payload)
            if timestamp is None:
                LOG.warning("Discarding malformed DSMR timestamp payload on %s: %r", topic, payload)
                return
            self._timestamp = timestamp
            self._emit_if_ready()
            return

        if topic not in POWER_TOPICS:
            return

        value_kw = _parse_float(payload)
        if value_kw is None:
            LOG.warning("Discarding malformed DSMR power payload on %s: %r", topic, payload)
            return
        self._values_kw[topic] = value_kw
        self._emit_if_ready()

    def _emit_if_ready(self) -> None:
        if not all(topic in self._values_kw for topic in POWER_TOPICS):
            return

        net_power_w = _kw_to_w(
            self._values_kw[GRID_RETURNED_TOPIC] - self._values_kw[GRID_DELIVERED_TOPIC]
        )
        per_phase_w = {
            phase: _kw_to_w(
                self._values_kw[PHASE_RETURNED_TOPICS[phase]]
                - self._values_kw[PHASE_DELIVERED_TOPICS[phase]]
            )
            for phase in ("L1", "L2", "L3")
        }
        timestamp = self._timestamp or datetime.now(UTC)
        self.on_update(net_power_w, per_phase_w, timestamp)


def _parse_float(payload: str) -> float | None:
    try:
        return float(payload)
    except ValueError:
        return None


def _parse_timestamp(payload: str) -> datetime | None:
    normalized = payload[:-1] + "+00:00" if payload.endswith("Z") else payload
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _kw_to_w(value_kw: float) -> int:
    return int(round(value_kw * 1000))


def _is_failure(reason_code: object) -> bool:
    is_failure = getattr(reason_code, "is_failure", None)
    if isinstance(is_failure, bool):
        return is_failure
    return reason_code != 0
