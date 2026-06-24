"""DSMR-reader external MQTT adapter for P1 power readings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

LOGGER = logging.getLogger(__name__)

DELIVERED_TOPIC = "dsmr/reading/electricity_currently_delivered"
RETURNED_TOPIC = "dsmr/reading/electricity_currently_returned"
TIMESTAMP_TOPIC = "dsmr/reading/timestamp"
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
REQUIRED_TOPICS = frozenset(
    [DELIVERED_TOPIC, RETURNED_TOPIC, TIMESTAMP_TOPIC]
    + list(PHASE_DELIVERED_TOPICS.values())
    + list(PHASE_RETURNED_TOPICS.values())
)


class P1Reader:
    """Subscribe to DSMR-reader topics and emit computed net watt values."""

    def __init__(self, broker: str, port: int, on_update: Callable[[int, dict, datetime, int, int], None]) -> None:
        self.broker = broker
        self.port = port
        self.on_update = on_update
        self._values: dict[str, float | datetime] = {}
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="minyad-p1-reader")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def start(self) -> None:
        """Start the DSMR MQTT client without crashing when the broker is unreachable.

        The DSMR broker can live outside the Docker network and may be offline or
        unreachable while the ingestion service starts.  Use paho's asynchronous
        connection mode so the network loop can retry the first connection instead
        of raising an OSError that terminates the container.
        """
        self._client.reconnect_delay_set(min_delay=5, max_delay=60)
        self._client.connect_async(self.broker, self.port, 60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, _userdata: object, _flags: mqtt.ConnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        LOGGER.info("Connected to external DSMR MQTT broker: %s", reason_code)
        for topic in REQUIRED_TOPICS:
            client.subscribe(topic)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: mqtt.DisconnectFlags, reason_code: mqtt.ReasonCode, _properties: mqtt.Properties | None) -> None:
        LOGGER.warning("Disconnected from external DSMR MQTT broker: %s", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        payload = message.payload.decode("utf-8", errors="replace").strip()
        if message.topic == TIMESTAMP_TOPIC:
            self._values[message.topic] = _parse_timestamp(payload)
        else:
            try:
                self._values[message.topic] = float(payload)
            except ValueError:
                LOGGER.warning("Discarding malformed DSMR payload on %s", message.topic)
                return
        self._emit_if_ready()

    def _emit_if_ready(self) -> None:
        if not REQUIRED_TOPICS.issubset(self._values):
            return
        delivered = float(self._values[DELIVERED_TOPIC])
        returned = float(self._values[RETURNED_TOPIC])
        # Use the same sign convention as the host-side DSMR bridge and the
        # control service: positive means grid import (delivered by the grid),
        # negative means grid export (returned to the grid).  This lets evening
        # import such as 1400 W trigger battery discharge instead of being
        # mistaken for solar surplus.
        net_power_w = round((delivered - returned) * 1000)
        per_phase_w = {
            phase: round((float(self._values[PHASE_DELIVERED_TOPICS[phase]]) - float(self._values[PHASE_RETURNED_TOPICS[phase]])) * 1000)
            for phase in ("L1", "L2", "L3")
        }
        timestamp = self._values[TIMESTAMP_TOPIC]
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        self.on_update(net_power_w, per_phase_w, timestamp, round(delivered * 1000), round(returned * 1000))


def _parse_timestamp(payload: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(payload.replace("Z", "+00:00"))
    except ValueError:
        LOGGER.warning("Discarding malformed DSMR timestamp; using current UTC time")
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
