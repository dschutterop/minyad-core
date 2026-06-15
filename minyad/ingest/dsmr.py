import json
import logging
import re
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from minyad.common.config import get_config
from minyad.common.db import connect, insert_reading
from minyad.common.status import update_status
from minyad.common.time import ensure_utc, utc_now

LOG = logging.getLogger(__name__)
OBIS_PATTERNS = {
    "import_kwh_t1": re.compile(r"1-0:1\.8\.1\((\d+\.\d+)\*kWh\)"),
    "import_kwh_t2": re.compile(r"1-0:1\.8\.2\((\d+\.\d+)\*kWh\)"),
    "export_kwh_t1": re.compile(r"1-0:2\.8\.1\((\d+\.\d+)\*kWh\)"),
    "export_kwh_t2": re.compile(r"1-0:2\.8\.2\((\d+\.\d+)\*kWh\)"),
    "import_kw": re.compile(r"1-0:1\.7\.0\((\d+\.\d+)\*kW\)"),
    "export_kw": re.compile(r"1-0:2\.7\.0\((\d+\.\d+)\*kW\)"),
}


def parse_dsmr_payload(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        return {
            "timestamp": _parse_ts(data.get("timestamp") or data.get("time")),
            "import_w": _power_w(
                data,
                ("import_w", "power_delivered_w"),
                ("electricity_currently_delivered", "power_delivered"),
            ),
            "export_w": _power_w(
                data,
                ("export_w", "power_returned_w"),
                ("electricity_currently_returned", "power_returned"),
            ),
            "import_kwh_t1": _first(data, "import_kwh_t1", "electricity_delivered_1"),
            "import_kwh_t2": _first(data, "import_kwh_t2", "electricity_delivered_2"),
            "export_kwh_t1": _first(data, "export_kwh_t1", "electricity_returned_1"),
            "export_kwh_t2": _first(data, "export_kwh_t2", "electricity_returned_2"),
            "raw": data,
        }
    except json.JSONDecodeError:
        parsed: dict[str, Any] = {"timestamp": utc_now(), "raw": {"telegram": text}}
        for key, pattern in OBIS_PATTERNS.items():
            match = pattern.search(text)
            if match:
                parsed[key] = float(match.group(1))
        return {
            "timestamp": parsed["timestamp"],
            "import_w": int(parsed.get("import_kw", 0) * 1000),
            "export_w": int(parsed.get("export_kw", 0) * 1000),
            "import_kwh_t1": parsed.get("import_kwh_t1"),
            "import_kwh_t2": parsed.get("import_kwh_t2"),
            "export_kwh_t1": parsed.get("export_kwh_t1"),
            "export_kwh_t2": parsed.get("export_kwh_t2"),
            "raw": parsed["raw"],
        }


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _power_w(data: dict[str, Any], watt_keys: tuple[str, ...], kilowatt_keys: tuple[str, ...]) -> int:
    watt_value = _first(data, *watt_keys)
    if watt_value is not None:
        return int(float(watt_value))
    return int(float(_first(data, *kilowatt_keys) or 0) * 1000)


def _parse_ts(value: Any) -> datetime:
    if not value:
        return utc_now()
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = get_config()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="minyad-dsmr-consumer")
    if cfg.mqtt_username:
        client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

    def on_connect(client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        LOG.info("Connected to MQTT broker %s:%s: %s", cfg.mqtt_host, cfg.mqtt_port, reason_code)
        client.subscribe(cfg.dsmr_mqtt_topic)
        with connect() as conn:
            update_status(conn, "dsmr", "connected", {"topic": cfg.dsmr_mqtt_topic})

    def on_message(_client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            reading = parse_dsmr_payload(message.payload)
            with connect() as conn:
                insert_reading(conn, "grid_readings", reading)
                update_status(conn, "dsmr", "ok", {"topic": message.topic})
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to ingest DSMR message: %s", exc)
            with connect() as conn:
                update_status(conn, "dsmr", "error", {"error": str(exc)})

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
