#!/usr/bin/env python3
"""Subscribe to # and print every MQTT message received. Ctrl-C to stop."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11883)
    parser.add_argument("--topic", default="#", help="Topic filter (default: #)")
    args = parser.parse_args()

    seen_topics: set[str] = set()

    def on_connect(client: mqtt.Client, _userdata, _flags, rc, _properties=None) -> None:
        if rc != 0:
            print(f"Connection failed (rc={rc})", file=sys.stderr)
            sys.exit(1)
        print(f"Connected to {args.host}:{args.port} — subscribing to '{args.topic}'\n")
        client.subscribe(args.topic)

    def on_message(_client, _userdata, message: mqtt.MQTTMessage) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        topic = message.topic
        payload = message.payload.decode(errors="replace")
        retain = " [retained]" if message.retain else ""
        first = " [NEW]" if topic not in seen_topics else ""
        seen_topics.add(topic)
        print(f"{ts}  {topic}{retain}{first}")
        print(f"         {payload}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mqtt-browse")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.host, args.port, keepalive=60)
    except OSError as e:
        print(f"Cannot connect to {args.host}:{args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n--- {len(seen_topics)} unique topics seen ---")
        for t in sorted(seen_topics):
            print(f"  {t}")


if __name__ == "__main__":
    main()
