#!/usr/bin/env python3
"""Host-side Enphase Envoy-S to MQTT bridge for Minyad VPP."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()

LOGGER_NAME = "enphase_bridge"
logger = logging.getLogger(LOGGER_NAME)

CLIENT_ID = "minyad-enphase-bridge"

MQTT_TOPIC_PRODUCTION_W = "minyad/solar/production_w"
MQTT_TOPIC_PRODUCTION_UPDATED_AT = "minyad/solar/production_updated_at"
MQTT_TOPIC_BRIDGE_STATUS = "minyad/solar/bridge/status"
MQTT_TOPIC_BRIDGE_LAST_SEEN = "minyad/solar/bridge/last_seen"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_ERROR = "error"


class EnvoyAuthError(RuntimeError):
    """Raised when the Envoy rejects the configured owner token."""


class EnvoyRequestError(RuntimeError):
    """Raised when the Envoy request fails for a retryable reason."""


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ValueError(f"{name} is required")
    return value.strip()


@dataclass(frozen=True)
class Config:
    envoy_host: str
    envoy_timeout: float
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_pass: str | None
    production_poll_interval: int
    inverter_poll_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not mqtt_host:
            raise ValueError("MQTT_BROKER is required")

        production_poll_interval = _get_env_int("ENPHASE_PRODUCTION_POLL_INTERVAL", 10)
        inverter_poll_interval = _get_env_int("ENPHASE_INVERTER_POLL_INTERVAL", 60)
        if production_poll_interval < 1:
            raise ValueError("ENPHASE_PRODUCTION_POLL_INTERVAL must be greater than 0")
        if inverter_poll_interval < 1:
            raise ValueError("ENPHASE_INVERTER_POLL_INTERVAL must be greater than 0")

        return cls(
            envoy_host=_get_required_env("ENPHASE_ENVOY_HOST"),
            envoy_timeout=_get_env_float("ENPHASE_ENVOY_TIMEOUT", 10.0),
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            mqtt_user=os.getenv("MQTT_USER") or None,
            mqtt_pass=os.getenv("MQTT_PASS") or None,
            production_poll_interval=production_poll_interval,
            inverter_poll_interval=inverter_poll_interval,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unix_to_iso(value: object) -> str:
    try:
        timestamp = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return utc_now_iso()
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def slugify_array_name(name: object) -> str:
    slug = re.sub(r"\s+", "_", str(name).strip().lower())
    slug = re.sub(r"[^a-z0-9_\-]", "", slug)
    return slug or "unknown"


class EnvoyClient:
    def __init__(self, host: str, token: str, timeout: float) -> None:
        self.base_url = f"https://{host.strip('/')}"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("Envoy uses a self-signed TLS certificate; requests verify=False is enabled")

    def get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, timeout=self.timeout, verify=False)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise EnvoyRequestError(str(exc)) from exc
        if response.status_code == 401:
            raise EnvoyAuthError("Envoy owner token is expired or invalid")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise EnvoyRequestError(str(exc)) from exc
        return response.json()

    async def read_production(self) -> dict[str, Any]:
        data = await asyncio.to_thread(self.get_json, "/api/v1/production")
        if not isinstance(data, dict):
            raise EnvoyRequestError("/api/v1/production returned non-object JSON")
        return data

    async def read_inverters(self) -> list[dict[str, Any]]:
        data = await asyncio.to_thread(self.get_json, "/api/v1/production/inverters")
        if not isinstance(data, list):
            raise EnvoyRequestError("/api/v1/production/inverters returned non-list JSON")
        return [item for item in data if isinstance(item, dict)]



def summarize_inverter_production(inverters: list[dict[str, Any]]) -> tuple[dict[str, int], int, object | None]:
    array_totals: dict[str, int] = {}
    latest_report_at = None
    for inverter in inverters:
        serial = str(inverter.get("serialNumber", "")).strip()
        if not serial:
            continue
        watts = int(inverter.get("lastReportWatts", 0) or 0)
        report_at = inverter.get("lastReportDate")
        if report_at is not None and (latest_report_at is None or report_at > latest_report_at):
            latest_report_at = report_at
        array_name = slugify_array_name(
            inverter.get("array") or inverter.get("arrayName") or inverter.get("name") or "unknown"
        )
        array_totals[array_name] = array_totals.get(array_name, 0) + watts
    return array_totals, sum(array_totals.values()), latest_report_at

def set_production_limit(watts: int) -> None:
    """Future hook for Enphase production curtailment."""
    # TODO: D8.x systems may expose curtailment through endpoints such as
    # /ivp/ss/pel_settings, /ivp/ss/gen_config, or related /ivp/ss controls.
    # Activating this likely requires an installer token or firmware downgrade;
    # keep this function replaceable so write support can be added without
    # changing the bridge architecture.
    raise NotImplementedError("Enphase curtailment is not implemented for owner-token local API access")


class EnphaseBridge:
    def __init__(self, config: Config, envoy: EnvoyClient) -> None:
        self.config = config
        self.envoy = envoy
        self.shutdown_event = asyncio.Event()
        self.mqtt_client = mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)
        self.mqtt_client.will_set(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_ERROR, retain=True)
        if config.mqtt_user:
            self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_pass)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

    def publish(self, topic: str, payload: object, retain: bool = True) -> None:
        result = self.mqtt_client.publish(topic, str(payload), retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish failed for %s with rc=%s", topic, result.rc)

    def on_connect(self, _client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        if rc == 0:
            logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
            self.publish_bridge_alive()
        else:
            logger.error("MQTT connection failed with rc=%s", rc)

    def on_disconnect(self, _client: mqtt.Client, _userdata: Any, rc: int) -> None:
        logger.warning("MQTT disconnected with rc=%s", rc)

    def publish_bridge_alive(self) -> None:
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_ONLINE)
        self.publish(MQTT_TOPIC_BRIDGE_LAST_SEEN, utc_now_iso())

    def publish_bridge_error(self) -> None:
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_ERROR)
        self.publish(MQTT_TOPIC_BRIDGE_LAST_SEEN, utc_now_iso())

    async def handle_auth_error(self, exc: EnvoyAuthError) -> None:
        logger.critical("%s; update ENPHASE_TOKEN in the host-services .env file and restart", exc)
        self.publish_bridge_error()

    async def production_loop(self) -> None:
        backoff = 1
        while not self.shutdown_event.is_set():
            interval = self.config.production_poll_interval
            try:
                data = await self.envoy.read_production()
                production_w = int(data.get("productionW", 0) or 0)
                updated_at = unix_to_iso(data.get("lastReportDate"))
                self.publish(MQTT_TOPIC_PRODUCTION_W, production_w)
                self.publish(MQTT_TOPIC_PRODUCTION_UPDATED_AT, updated_at)
                self.publish_bridge_alive()
                logger.info("Production poll production_w=%s updated_at=%s", production_w, updated_at)
                backoff = 1
            except EnvoyAuthError as exc:
                await self.handle_auth_error(exc)
            except EnvoyRequestError as exc:
                interval = min(backoff, 60)
                backoff = min(backoff * 2, 60)
                logger.warning("Production poll failed; retrying in %ss: %s", interval, exc)
                self.publish_bridge_error()
            except Exception as exc:
                logger.warning("Production poll failed; retrying in %ss: %s", interval, exc, exc_info=True)
                self.publish_bridge_error()

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def inverter_loop(self) -> None:
        backoff = 1
        while not self.shutdown_event.is_set():
            interval = self.config.inverter_poll_interval
            try:
                inverters = await self.envoy.read_inverters()
                array_totals, total_production_w, latest_report_at = summarize_inverter_production(
                    inverters
                )
                for inverter in inverters:
                    serial = str(inverter.get("serialNumber", "")).strip()
                    if not serial:
                        continue
                    watts = int(inverter.get("lastReportWatts", 0) or 0)
                    last_report_at = unix_to_iso(inverter.get("lastReportDate"))
                    self.publish(f"minyad/solar/inverter/{serial}/power_w", watts)
                    self.publish(f"minyad/solar/inverter/{serial}/last_report_at", last_report_at)
                for array_name, watts in array_totals.items():
                    self.publish(f"minyad/solar/array/{array_name}/power_w", watts)
                self.publish(MQTT_TOPIC_PRODUCTION_W, total_production_w)
                self.publish(MQTT_TOPIC_PRODUCTION_UPDATED_AT, unix_to_iso(latest_report_at))
                self.publish_bridge_alive()
                logger.info(
                    "Inverter poll inverter_count=%s arrays=%s total_production_w=%s",
                    len(inverters),
                    sorted(array_totals),
                    total_production_w,
                )
                backoff = 1
            except EnvoyAuthError as exc:
                await self.handle_auth_error(exc)
            except EnvoyRequestError as exc:
                interval = min(backoff, 60)
                backoff = min(backoff * 2, 60)
                logger.warning("Inverter poll failed; retrying in %ss: %s", interval, exc)
                self.publish_bridge_error()
            except Exception as exc:
                logger.warning("Inverter poll failed; retrying in %ss: %s", interval, exc, exc_info=True)
                self.publish_bridge_error()

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        self.mqtt_client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()
        await asyncio.gather(self.production_loop(), self.inverter_loop())
        self.publish_bridge_error()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    token = _get_required_env("ENPHASE_TOKEN")
    envoy = EnvoyClient(config.envoy_host, token, config.envoy_timeout)
    logger.info(
        "Using Envoy host %s with production interval=%ss and inverter interval=%ss",
        config.envoy_host,
        config.production_poll_interval,
        config.inverter_poll_interval,
    )
    bridge = EnphaseBridge(config, envoy)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
