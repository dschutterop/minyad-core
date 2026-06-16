import json
import logging
import re
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from minyad.common.config import get_config
from minyad.common.db import connect, insert_reading
from minyad.common.logging import configure_logging
from minyad.common.status import update_status
from minyad.common.time import ensure_utc, utc_now

LOG = logging.getLogger(__name__)
PAYLOAD_PREVIEW_CHARS = 500
OBIS_PATTERNS = {
    "import_kwh_t1": re.compile(r"1-0:1\.8\.1\((\d+\.\d+)\*kWh\)"),
    "import_kwh_t2": re.compile(r"1-0:1\.8\.2\((\d+\.\d+)\*kWh\)"),
    "export_kwh_t1": re.compile(r"1-0:2\.8\.1\((\d+\.\d+)\*kWh\)"),
    "export_kwh_t2": re.compile(r"1-0:2\.8\.2\((\d+\.\d+)\*kWh\)"),
    "import_kw": re.compile(r"1-0:1\.7\.0\((\d+\.\d+)\*kW\)"),
    "export_kw": re.compile(r"1-0:2\.7\.0\((\d+\.\d+)\*kW\)"),
}


def parse_dsmr_message(topic: str, payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_dsmr_payload(payload)
    if isinstance(data, dict):
        return _parse_dsmr_json(data)
    return _parse_scalar_topic(topic, data)


def parse_dsmr_payload(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return _parse_scalar_topic("", data)
        return _parse_dsmr_json(data)
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


def _parse_dsmr_json(data: dict[str, Any]) -> dict[str, Any]:
    import_w, export_w = _grid_power(data)
    return {
        "timestamp": _parse_ts(data.get("timestamp") or data.get("time")),
        "import_w": import_w,
        "export_w": export_w,
        "import_kwh_t1": _first(data, "import_kwh_t1", "electricity_delivered_1"),
        "import_kwh_t2": _first(data, "import_kwh_t2", "electricity_delivered_2"),
        "export_kwh_t1": _first(data, "export_kwh_t1", "electricity_returned_1"),
        "export_kwh_t2": _first(data, "export_kwh_t2", "electricity_returned_2"),
        "raw": data,
    }


def _parse_scalar_topic(topic: str, value: Any) -> dict[str, Any]:
    normalized_topic = _normalize_key(topic)
    watts = _number_with_unit(value, None, default_multiplier=_default_scalar_multiplier(value))
    is_export = any(
        part in normalized_topic
        for part in ("returned", "return", "export", "production", "produced")
    )
    is_import = any(
        part in normalized_topic for part in ("delivered", "import", "consumption", "consumed")
    )
    return {
        "timestamp": utc_now(),
        "import_w": watts if is_import or not is_export else 0,
        "export_w": watts if is_export else 0,
        "import_kwh_t1": None,
        "import_kwh_t2": None,
        "export_kwh_t1": None,
        "export_kwh_t2": None,
        "raw": {"topic": topic, "value": value},
    }


def _default_scalar_multiplier(value: Any) -> int:
    try:
        return 1000 if abs(float(str(value).strip().replace(",", "."))) < 100 else 1
    except (TypeError, ValueError):
        return 1


def _first(data: dict[str, Any], *keys: str) -> Any:
    normalized = _flatten(data)
    for key in keys:
        if key in normalized and normalized[key] is not None:
            return normalized[key]
    return None


def _top_level_first(data: dict[str, Any], *keys: str) -> Any:
    normalized = {_normalize_key(key): value for key, value in data.items()}
    for key in keys:
        if key in normalized and normalized[key] is not None:
            return normalized[key]
    return None


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in data.items():
        normalized_key = _normalize_key(key)
        path = f"{prefix}_{normalized_key}" if prefix else normalized_key
        if isinstance(value, dict):
            flattened.update(_flatten(value, path))
        else:
            flattened[path] = value
            flattened.setdefault(normalized_key, value)
    return flattened


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _grid_power(data: dict[str, Any]) -> tuple[int, int]:
    net_w = _top_level_first(data, "active_power_w", "net_power_w", "power_w")
    if net_w is not None:
        return _split_signed_power(_number(net_w))

    net_kw = _top_level_first(data, "active_power", "net_power", "power")
    if net_kw is not None:
        return _split_signed_power(_number(net_kw, multiplier=1000))

    return (
        _power_w(
            data,
            (
                "import_w",
                "power_delivered_w",
                "power_consumed_w",
                "consumption_w",
                "electricity_currently_delivered_w",
                "electricity_meter_power_consumption_w",
                "consumption_power_w",
            ),
            (
                "electricity_currently_delivered",
                "power_delivered",
                "power_consumed",
                "power_consumption",
                "currently_delivered",
                "electricity_meter_power_consumption",
                "consumption_power",
                "consumption",
            ),
        ),
        _power_w(
            data,
            (
                "export_w",
                "power_returned_w",
                "power_produced_w",
                "production_w",
                "electricity_currently_returned_w",
                "electricity_meter_power_production_w",
                "production_power_w",
            ),
            (
                "electricity_currently_returned",
                "power_returned",
                "power_produced",
                "power_production",
                "currently_returned",
                "electricity_meter_power_production",
                "production_power",
                "production",
            ),
        ),
    )


def _split_signed_power(watts: int) -> tuple[int, int]:
    return max(0, watts), max(0, -watts)


def _power_w(
    data: dict[str, Any], watt_keys: tuple[str, ...], kilowatt_keys: tuple[str, ...]
) -> int:
    normalized = _flatten(data)
    watt_value = _first(data, *watt_keys)
    if watt_value is not None:
        return _number(watt_value)

    for key in kilowatt_keys:
        value = normalized.get(key)
        if value is not None:
            return _number_with_unit(value, _first(data, f"{key}_unit"), default_multiplier=1000)
        nested_value = normalized.get(f"{key}_value")
        if nested_value is not None:
            return _number_with_unit(
                nested_value,
                normalized.get(f"{key}_unit") or normalized.get(f"{key}_uom"),
                default_multiplier=1000,
            )
    return 0


def _number(value: Any, multiplier: int = 1) -> int:
    return _number_with_unit(value, None, default_multiplier=multiplier)


def _number_with_unit(value: Any, unit: Any, default_multiplier: int = 1) -> int:
    multiplier = default_multiplier
    if isinstance(value, str):
        parts = value.strip().replace(",", ".").split()
        value = parts[0]
        if len(parts) > 1:
            unit = parts[1]
    if unit is not None:
        normalized_unit = str(unit).strip().lower()
        if normalized_unit in {"w", "watt", "watts"}:
            multiplier = 1
        elif normalized_unit in {"kw", "kilowatt", "kilowatts"}:
            multiplier = 1000
    return int(float(value) * multiplier)


def _parse_ts(value: Any) -> datetime:
    if not value:
        return utc_now()
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _payload_preview(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= PAYLOAD_PREVIEW_CHARS:
        return text
    return f"{text[:PAYLOAD_PREVIEW_CHARS]}…"


def _payload_debug_details(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        matched_obis = [key for key, pattern in OBIS_PATTERNS.items() if pattern.search(text)]
        return {"format": "telegram", "matched_obis": matched_obis}
    if isinstance(data, dict):
        flattened = _flatten(data)
        return {"format": "json", "keys": sorted(flattened)}
    return {"format": type(data).__name__}


def _log_dsmr_reading(topic: str, payload: bytes, reading: dict[str, Any]) -> None:
    details = _payload_debug_details(payload)
    LOG.info(
        "DSMR reading topic=%s import_w=%s export_w=%s import_kwh_t1=%s import_kwh_t2=%s "
        "export_kwh_t1=%s export_kwh_t2=%s format=%s",
        topic,
        reading.get("import_w"),
        reading.get("export_w"),
        reading.get("import_kwh_t1"),
        reading.get("import_kwh_t2"),
        reading.get("export_kwh_t1"),
        reading.get("export_kwh_t2"),
        details.get("format"),
    )
    LOG.debug(
        "DSMR payload details topic=%s details=%s preview=%s",
        topic,
        details,
        _payload_preview(payload),
    )
    if not reading.get("import_w") and not reading.get("export_w"):
        LOG.warning(
            "DSMR reading has zero import/export; topic=%s details=%s preview=%s",
            topic,
            details,
            _payload_preview(payload),
        )


def _configure_mqtt_debug(client: mqtt.Client, debug_messages: bool) -> None:
    if not debug_messages:
        return
    client.enable_logger(logging.getLogger("minyad.ingest.dsmr.mqtt"))
    LOG.debug("Enabled verbose DSMR MQTT client logging")


def main() -> None:
    configure_logging()
    cfg = get_config()
    if not cfg.dsmr_ingestion_enabled:
        LOG.info("DSMR ingestion is disabled; exiting")
        return
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="minyad-dsmr-consumer")
    _configure_mqtt_debug(client, cfg.debug_messages)
    if cfg.mqtt_username:
        client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

    def on_connect(
        client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None
    ) -> None:
        LOG.info("Connected to MQTT broker %s:%s: %s", cfg.mqtt_host, cfg.mqtt_port, reason_code)
        client.subscribe(cfg.dsmr_mqtt_topic)
        with connect() as conn:
            update_status(conn, "dsmr", "connected", {"topic": cfg.dsmr_mqtt_topic})

    def on_message(_client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        LOG.debug(
            "Received DSMR MQTT message topic=%s payload_bytes=%s qos=%s retain=%s",
            message.topic,
            len(message.payload),
            message.qos,
            message.retain,
        )
        try:
            reading = parse_dsmr_message(message.topic, message.payload)
            _log_dsmr_reading(message.topic, message.payload, reading)
            with connect() as conn:
                insert_reading(conn, "grid_readings", reading)
                update_status(
                    conn,
                    "dsmr",
                    "ok",
                    {
                        "topic": message.topic,
                        "import_w": reading.get("import_w"),
                        "export_w": reading.get("export_w"),
                        "debug": _payload_debug_details(message.payload),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to ingest DSMR message: %s", exc)
            with connect() as conn:
                update_status(conn, "dsmr", "error", {"error": str(exc)})

    def on_subscribe(
        _client: mqtt.Client,
        _userdata: Any,
        mid: int,
        reason_codes: Any,
        _properties: Any = None,
    ) -> None:
        LOG.debug(
            "Subscribed to DSMR MQTT topic=%s mid=%s reason_codes=%s",
            cfg.dsmr_mqtt_topic,
            mid,
            reason_codes,
        )

    def on_disconnect(
        _client: mqtt.Client,
        _userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        LOG.info(
            "Disconnected from MQTT broker %s:%s: %s", cfg.mqtt_host, cfg.mqtt_port, reason_code
        )
        LOG.debug("DSMR MQTT disconnect flags=%s", disconnect_flags)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
