#!/usr/bin/env python3
"""Host-side inverter to MQTT bridge for Minyad VPP."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic, time
from typing import Any

import paho.mqtt.client as mqtt
import psycopg2
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from dotenv import load_dotenv

from backends import BatteryTelemetry, GoodWeBackend, GoodWeCompositeBackend, InverterBackend, ModbusBackend

load_dotenv()

LOGGER_NAME = "goodwe_bridge"
logger = logging.getLogger(LOGGER_NAME)

MQTT_TOPIC_CHARGE_W = "minyad/control/charge_w"
MQTT_TOPIC_DISCHARGE_W = "minyad/control/discharge_w"
MQTT_TOPIC_DSMR_NET_POWER = "minyad/dsmr/net_power_w"
MQTT_TOPIC_GRID_NET_POWER = "minyad/grid/net_power_w"
MQTT_TOPIC_CONTROL_STATE = "minyad/control/state"
MQTT_TOPIC_BATTERY_POLL_INTERVAL = "minyad/settings/battery/inverter_poll_interval_s"
MQTT_TOPIC_BATTERY_POWER_W = "minyad/battery/power_w"
MQTT_TOPIC_BATTERY_MODE = "minyad/battery/mode"
BATTERY_POLL_INTERVAL_SETTING = "battery.inverter_poll_interval_s"
POLL_INTERVAL_SEC = 2
MIN_WRITE_INTERVAL_SEC = 10
MIN_TARGET_CHANGE_W = 150
WRITE_REFRESH_INTERVAL_SEC = 600
DEFAULT_POLL_INTERVAL_SECONDS = POLL_INTERVAL_SEC
OPPOSITE_DIRECTION_SETTLE_POWER_W = 100

MQTT_TOPIC_INVERTER_STATUS = "minyad/inverter/status"
MQTT_TOPIC_BRIDGE_STATUS = "minyad/bridge/status"
MQTT_TOPIC_BRIDGE_LAST_SEEN = "minyad/bridge/last_seen"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_OFFLINE = "offline"
STATUS_OK = "ok"
STATUS_UNREACHABLE = "unreachable"
STATUS_ERROR = "error"
CLIENT_ID = "goodwe-bridge"
METRICS_PORT = int(os.getenv("METRICS_PORT", "9107"))
METRICS_ADDR = os.getenv("METRICS_ADDR", "")
VERSION = os.getenv("MINYAD_VERSION", os.getenv("MINYAD_IMAGE_TAG", "unknown"))

PROMETHEUS_REGISTRY = CollectorRegistry()
BUILD_INFO = Gauge("minyad_bridge_goodwe_build_info", "Build and version information for the GoodWe bridge.", ["version"], registry=PROMETHEUS_REGISTRY)
ERRORS_TOTAL = Counter("minyad_bridge_goodwe_errors_total", "Errors observed by the GoodWe bridge.", ["type"], registry=PROMETHEUS_REGISTRY)
READ_DURATION_SECONDS = Histogram(
    "minyad_bridge_goodwe_read_duration_seconds",
    "Duration of GoodWe bridge read_state calls.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=PROMETHEUS_REGISTRY,
)
READ_FAILURES_TOTAL = Counter("minyad_bridge_goodwe_read_failures_total", "GoodWe bridge read failures.", registry=PROMETHEUS_REGISTRY)
LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "minyad_bridge_goodwe_last_success_timestamp_seconds",
    "Unix timestamp of the most recent successful GoodWe bridge read.",
    registry=PROMETHEUS_REGISTRY,
)


def start_metrics_server() -> None:
    BUILD_INFO.labels(version=VERSION).set(1)
    start_http_server(METRICS_PORT, addr=METRICS_ADDR, registry=PROMETHEUS_REGISTRY)
    logger.info("Prometheus metrics listening on %s:%s", METRICS_ADDR, METRICS_PORT)


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
    goodwe_modbus_limits_enabled: bool
    goodwe_api_enabled: bool
    goodwe_api_host: str | None
    inverter_max_w: int
    inverter_retries: int
    inverter_delay: int
    goodwe_min_request_interval_s: float
    modbus_gw_ip: str
    modbus_gw_port: int
    modbus_slave_id: int
    modbus_timeout: float
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_pass: str | None
    poll_interval: int
    database_url: str | None
    max_charge_a: int
    max_allowed_charge_a: int
    dry_run: bool
    log_level: str
    min_write_interval_s: float
    min_target_change_w: int
    write_refresh_interval_s: float
    default_charge_limit_w: int
    default_discharge_limit_w: int
    conservative_charge_limit_w: int
    conservative_discharge_limit_w: int

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not mqtt_host:
            raise ValueError("MQTT_BROKER is required")

        legacy_backend = os.getenv("INVERTER_BACKEND")
        if legacy_backend:
            logger.warning("INVERTER_BACKEND is deprecated; use GOODWE_MODBUS_ENABLED and GOODWE_API_ENABLED")
        goodwe_api_host = os.getenv("GOODWE_API_HOST", "").strip() or None
        goodwe_modbus_enabled = os.getenv("GOODWE_MODBUS_LIMITS_ENABLED", os.getenv("GOODWE_MODBUS_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
        goodwe_api_enabled = os.getenv("GOODWE_API_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        if goodwe_api_enabled and not goodwe_api_host:
            raise ValueError("GOODWE_API_HOST is required when GOODWE_API_ENABLED=true")
        if not goodwe_modbus_enabled and not goodwe_api_enabled:
            raise ValueError("At least one of GOODWE_MODBUS_LIMITS_ENABLED or GOODWE_API_ENABLED must be true")

        requested_max_charge_a = _get_env_int("MAX_CHARGE_A", 30)
        max_allowed_charge_a = _get_env_int("MAX_ALLOWED_CHARGE_A", _get_env_int("GOODWE_MAX_ALLOWED_CHARGE_A", 30))
        max_charge_a = min(requested_max_charge_a, max_allowed_charge_a)
        if requested_max_charge_a > max_allowed_charge_a:
            logger.warning(
                "GoodWe charge current request clamped requested_max_charge_a=%s bridge_max_allowed_charge_a=%s bridge_max_charge_a=%s clamp_reason=MAX_CHARGE_A_above_MAX_ALLOWED_CHARGE_A",
                requested_max_charge_a, max_allowed_charge_a, max_charge_a,
            )
        else:
            logger.info(
                "GoodWe charge current configured requested_max_charge_a=%s bridge_max_allowed_charge_a=%s bridge_max_charge_a=%s clamp_reason=none",
                requested_max_charge_a, max_allowed_charge_a, max_charge_a,
            )
        return cls(
            goodwe_modbus_limits_enabled=goodwe_modbus_enabled,
            goodwe_api_enabled=goodwe_api_enabled,
            goodwe_api_host=goodwe_api_host,
            inverter_max_w=_get_env_int("INVERTER_MAX_W", _get_env_int("MAX_DISCHARGE_W", 5000)),
            inverter_retries=_get_env_int("INVERTER_RETRIES", 5),
            inverter_delay=_get_env_int("INVERTER_DELAY", 3),
            goodwe_min_request_interval_s=_get_env_float("GOODWE_MIN_REQUEST_INTERVAL_S", 2.0),
            modbus_gw_ip=(os.getenv("GOODWE_MODBUS_HOST") or os.getenv("MODBUS_GW_IP") or ("" if not goodwe_modbus_enabled else _get_required_env("MODBUS_GW_IP"))),
            modbus_gw_port=_get_env_int("GOODWE_MODBUS_PORT", _get_env_int("MODBUS_GW_PORT", 502)),
            modbus_slave_id=_get_env_int("GOODWE_MODBUS_DEVICE_ID", _get_env_int("MODBUS_SLAVE_ID", 247)),
            modbus_timeout=_get_env_float("MODBUS_TIMEOUT", 5.0),
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            mqtt_user=os.getenv("MQTT_USER"),
            mqtt_pass=os.getenv("MQTT_PASS"),
            poll_interval=_get_env_int("POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS),
            database_url=os.getenv("DB_URL") or os.getenv("DATABASE_URL"),
            max_charge_a=max_charge_a,
            max_allowed_charge_a=max_allowed_charge_a,
            dry_run=os.getenv("GOODWE_DRY_RUN", os.getenv("DRY_RUN", "false")).lower() in {"1", "true", "yes", "on"},
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            min_write_interval_s=_get_env_float("GOODWE_LIMIT_WRITE_INTERVAL_SEC", _get_env_float("MIN_WRITE_INTERVAL_SEC", MIN_WRITE_INTERVAL_SEC)),
            min_target_change_w=_get_env_int("GOODWE_LIMIT_MIN_CHANGE_W", _get_env_int("MIN_TARGET_CHANGE_W", MIN_TARGET_CHANGE_W)),
            write_refresh_interval_s=_get_env_float("WRITE_REFRESH_INTERVAL_SEC", WRITE_REFRESH_INTERVAL_SEC),
            default_charge_limit_w=_get_env_int("GOODWE_DEFAULT_CHARGE_LIMIT_W", 6000),
            default_discharge_limit_w=_get_env_int("GOODWE_DEFAULT_DISCHARGE_LIMIT_W", 6000),
            conservative_charge_limit_w=_get_env_int("GOODWE_CONSERVATIVE_CHARGE_LIMIT_W", 1500),
            conservative_discharge_limit_w=_get_env_int("GOODWE_CONSERVATIVE_DISCHARGE_LIMIT_W", 1500),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def psycopg2_database_url(url: str) -> str:
    if url.startswith("postgresql+") and "://" in url:
        return "postgresql://" + url.split("://", 1)[1]
    return url


def build_backend(config: Config) -> InverterBackend:
    modbus_client: InverterBackend | None = None
    api_client: InverterBackend | None = None
    if config.goodwe_modbus_limits_enabled:
        modbus_client = ModbusBackend(
            host=config.modbus_gw_ip,
            port=config.modbus_gw_port,
            slave_id=config.modbus_slave_id,
            timeout=config.modbus_timeout,
            max_w=config.inverter_max_w,
            dry_run=config.dry_run,
            min_write_interval_s=config.min_write_interval_s,
            min_target_change_w=config.min_target_change_w,
            write_refresh_interval_s=config.write_refresh_interval_s,
        )
    if config.goodwe_api_enabled:
        if not config.goodwe_api_host:
            raise ValueError("GOODWE_API_HOST is required when GOODWE_API_ENABLED=true")
        api_client = GoodWeBackend(
            config.goodwe_api_host,
            config.inverter_max_w,
            retries=config.inverter_retries,
            delay=config.inverter_delay,
            min_request_interval_s=config.goodwe_min_request_interval_s,
            dry_run=config.dry_run,
        )
    return GoodWeCompositeBackend(modbus_client, api_client)


class GoodWeBridge:
    def __init__(self, config: Config, backend: InverterBackend) -> None:
        self.config = config
        self.backend = backend
        self.loop: asyncio.AbstractEventLoop | None = None
        self.shutdown_event = asyncio.Event()
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=CLIENT_ID,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        self.mqtt_client.will_set(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_OFFLINE, retain=True)
        if config.mqtt_user:
            self.mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_pass)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.control_state = "IDLE"
        self._last_charge_setpoint_w = 0
        self._last_discharge_setpoint_w = 0
        self._last_p1_grid_power_w: int | None = 0
        self._last_p1_grid_power_monotonic: float | None = monotonic()
        self._immediate_poll_task: Future[None] | None = None
        self._mqtt_poll_interval: int | None = None
        self.modbus_reads_total = 0
        self.modbus_writes_total = 0
        self.modbus_write_skipped_total = 0
        self.modbus_errors_total = 0
        self.last_successful_read_timestamp: float | None = None
        self.last_successful_write_timestamp: float | None = None
        self.target_charge_limit_w = 0
        self.target_discharge_limit_w = 0
        self._last_write_monotonic: float | None = None
        self._last_api_command: tuple[str, int] | None = None
        self._last_api_command_monotonic: float | None = None
        self._last_api_battery_power_w: int | None = None
        self._last_api_grid_power_w: int | None = None
        self._last_api_telemetry_monotonic: float | None = None
        self._last_api_battery_soc: int | None = None
        self._last_logged_signed_setpoint_w = 0
        self._pending_charge_check: tuple[float, int, int | None] | None = None

    def load_poll_interval(self) -> int:
        """Return the current inverter polling interval in seconds.

        A retained MQTT setting is preferred so the interval is restored after
        bridge restarts. PostgreSQL remains a fallback when no MQTT setting has
        been received yet. Command handling remains event-driven and is not
        delayed by this telemetry interval.
        """
        if self._mqtt_poll_interval is not None:
            return self._mqtt_poll_interval
        configured = self.config.poll_interval
        if not self.config.database_url:
            return configured
        try:
            with closing(psycopg2.connect(psycopg2_database_url(self.config.database_url))) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "select value from settings where key = %s and encrypted = false",
                        (BATTERY_POLL_INTERVAL_SETTING,),
                    )
                    row = cur.fetchone()
        except Exception as exc:
            logger.warning("Could not load %s; using %ss: %s", BATTERY_POLL_INTERVAL_SETTING, configured, exc)
            return configured
        if row is None:
            return configured
        try:
            interval = int(row[0])
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid %s=%r; using %ss", BATTERY_POLL_INTERVAL_SETTING, row[0], configured)
            return configured
        if interval < 1:
            logger.warning("Ignoring non-positive %s=%s; using %ss", BATTERY_POLL_INTERVAL_SETTING, interval, configured)
            return configured
        return interval

    def publish(self, topic: str, payload: object, retain: bool = True) -> None:
        self.mqtt_client.publish(topic, str(payload), retain=retain)

    def on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            logger.error("MQTT connection failed with reason=%s", reason_code)
            return
        logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
        client.subscribe([(MQTT_TOPIC_CHARGE_W, 1), (MQTT_TOPIC_DISCHARGE_W, 1), (MQTT_TOPIC_CONTROL_STATE, 1), (MQTT_TOPIC_BATTERY_POLL_INTERVAL, 1), (MQTT_TOPIC_DSMR_NET_POWER, 1), (MQTT_TOPIC_GRID_NET_POWER, 1)])
        self.publish_bridge_alive()

    def on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        logger.warning("MQTT disconnected with reason=%s", reason_code)

    def publish_bridge_alive(self) -> None:
        timestamp = utc_now_iso()
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_ONLINE, retain=True)
        self.publish(MQTT_TOPIC_BRIDGE_LAST_SEEN, timestamp, retain=True)
        logger.debug("Published bridge heartbeat timestamp=%s", timestamp)

    def on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if self.loop is None:
            logger.warning("Ignoring MQTT message before event loop is ready")
            return

        payload = message.payload.decode("utf-8", errors="replace").strip()
        if message.topic == MQTT_TOPIC_CONTROL_STATE:
            self.handle_control_state(payload)
            return
        if message.topic == MQTT_TOPIC_BATTERY_POLL_INTERVAL:
            self.handle_poll_interval(payload)
            return
        if message.topic in {MQTT_TOPIC_DSMR_NET_POWER, MQTT_TOPIC_GRID_NET_POWER}:
            self.handle_grid_power(payload)
            return

        try:
            watts = int(payload)
        except ValueError:
            logger.warning("Ignoring invalid watt payload on %s: %r", message.topic, payload)
            return

        if message.topic == MQTT_TOPIC_CHARGE_W:
            asyncio.run_coroutine_threadsafe(self.handle_charge_setpoint(watts), self.loop)
        elif message.topic == MQTT_TOPIC_DISCHARGE_W:
            asyncio.run_coroutine_threadsafe(self.handle_discharge_setpoint(watts), self.loop)

    def handle_grid_power(self, payload: str) -> None:
        try:
            self._last_p1_grid_power_w = int(payload)
            self._last_p1_grid_power_monotonic = monotonic()
        except ValueError:
            logger.warning("Ignoring invalid grid power payload: %r", payload)

    def handle_poll_interval(self, payload: str) -> None:
        try:
            interval = int(payload)
        except ValueError:
            logger.warning("Ignoring invalid MQTT %s payload: %r", MQTT_TOPIC_BATTERY_POLL_INTERVAL, payload)
            return
        if interval < 1:
            logger.warning("Ignoring non-positive MQTT %s payload: %s", MQTT_TOPIC_BATTERY_POLL_INTERVAL, interval)
            return
        self._mqtt_poll_interval = interval
        logger.info("Battery inverter poll interval updated from MQTT: %ss", interval)

    def handle_control_state(self, state: str) -> None:
        previous_state = self.control_state
        self.control_state = state
        if previous_state == "IDLE" and state in {"CHARGING", "DISCHARGING"}:
            logger.info("Control state changed %s -> %s; polling inverter status immediately", previous_state, state)
            self.schedule_immediate_poll()

    def schedule_immediate_poll(self) -> None:
        if self.loop is None:
            logger.warning("Ignoring immediate poll request before event loop is ready")
            return
        if self._immediate_poll_task is not None and not self._immediate_poll_task.done():
            logger.debug("Immediate inverter status poll already queued")
            return
        self._immediate_poll_task = asyncio.run_coroutine_threadsafe(self.poll_once_safely(), self.loop)

    async def poll_once_safely(self) -> None:
        try:
            await self.poll_once()
        except (ConnectionError, TimeoutError) as exc:
            READ_FAILURES_TOTAL.inc()
            ERRORS_TOTAL.labels(type="read_unavailable").inc()
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)
        except Exception as exc:
            READ_FAILURES_TOTAL.inc()
            ERRORS_TOTAL.labels(type="read_error").inc()
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)

    async def handle_charge_setpoint(self, watts: int) -> None:
        previous_charge = self.target_charge_limit_w
        requested_charge = max(0, int(watts))
        if self._opposite_direction_settling("charge", requested_charge):
            return
        self.target_charge_limit_w = requested_charge
        clears_discharge = self.target_charge_limit_w > 0 and self.target_discharge_limit_w > 0
        if self.target_charge_limit_w > 0:
            self.target_discharge_limit_w = 0
        if self.target_charge_limit_w == previous_charge and not clears_discharge and self._last_api_command is not None:
            return
        await self._apply_actuator_targets(state_changed=(previous_charge == 0 and self.target_charge_limit_w > 0))

    async def handle_discharge_setpoint(self, watts: int) -> None:
        previous_discharge = self.target_discharge_limit_w
        requested_discharge = max(0, int(watts))
        if self._opposite_direction_settling("discharge", requested_discharge):
            return
        self.target_discharge_limit_w = requested_discharge
        clears_charge = self.target_discharge_limit_w > 0 and self.target_charge_limit_w > 0
        if self.target_discharge_limit_w > 0:
            self.target_charge_limit_w = 0
        if self.target_discharge_limit_w == previous_discharge and not clears_charge and self._last_api_command is not None:
            return
        await self._apply_actuator_targets(state_changed=(previous_discharge == 0 and self.target_discharge_limit_w > 0))

    async def _apply_actuator_targets(self, *, state_changed: bool = False) -> None:
        charge = self.target_charge_limit_w
        discharge = self.target_discharge_limit_w
        unchanged = charge == self._last_charge_setpoint_w and discharge == self._last_discharge_setpoint_w
        age = None if self._last_write_monotonic is None else monotonic() - self._last_write_monotonic
        modbus_result: str
        if unchanged and not state_changed and self._last_api_command is not None and not (age is not None and age >= self.config.write_refresh_interval_s):
            modbus_result = self._record_skipped_modbus_write("unchanged target")
        else:
            delta = max(abs(charge - self._last_charge_setpoint_w), abs(discharge - self._last_discharge_setpoint_w))
            if not state_changed and delta < self.config.min_target_change_w and not unchanged:
                modbus_result = self._record_skipped_modbus_write("below min delta")
            elif age is not None and age < self.config.min_write_interval_s:
                modbus_result = self._record_skipped_modbus_write("write interval not elapsed")
            else:
                modbus_result = await self._apply_modbus_limits(charge, discharge, state_changed=state_changed)
        api_command, api_success = await self._apply_api_command(charge, discharge)
        if api_success is True:
            self.publish_commanded_battery_state(api_command)
        self.publish_metrics()
        self._log_control_decision(charge, discharge, modbus_write_result=modbus_result, api_command=api_command, api_command_success=api_success)
        if api_success is True and api_command == "charge":
            self._pending_charge_check = (monotonic(), charge, self._last_api_battery_power_w)

    async def _apply_modbus_limits(self, charge: int, discharge: int, *, state_changed: bool) -> str:
        try:
            applied = await self.backend.set_battery_limits(charge, discharge, state_changed=state_changed)
        except (ConnectionError, TimeoutError):
            self.modbus_errors_total += 1
            logger.exception("[modbus] Modbus limit write unavailable charge_limit_w=%s discharge_limit_w=%s", charge, discharge)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
            return "failure_unavailable"
        except Exception:
            self.modbus_errors_total += 1
            logger.exception("[modbus] Failed to apply limit registers charge_limit_w=%s discharge_limit_w=%s", charge, discharge)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
            return "failure"
        if applied is False:
            self.modbus_write_skipped_total += 1
            logger.info("[modbus] Limit write skipped by backend charge_limit_w=%s discharge_limit_w=%s", charge, discharge)
            return "skipped_unchanged"
        self._last_charge_setpoint_w = charge
        self._last_discharge_setpoint_w = discharge
        self._last_write_monotonic = monotonic()
        self.last_successful_write_timestamp = time()
        self.modbus_writes_total += 1
        return "success"

    async def _apply_api_command(self, charge: int, discharge: int) -> tuple[str, bool | None]:
        if charge > 0 and discharge <= 0:
            command, target = "charge", charge
            call = self.backend.set_charge
        elif discharge > 0 and charge <= 0:
            command, target = "discharge", discharge
            call = self.backend.set_discharge
        elif charge > 0 and discharge > 0:
            if charge >= discharge:
                command, target = "charge", charge
                call = self.backend.set_charge
            else:
                command, target = "discharge", discharge
                call = self.backend.set_discharge
            logger.warning(
                "[api] Conflicting charge/discharge targets received; choosing api_command=%s target_power_w=%s charge_limit_w=%s discharge_limit_w=%s",
                command, target, charge, discharge,
            )
        else:
            command, target = "stop_forced_mode", 0
            call = getattr(self.backend, "stop_forced_mode", None)
        current = (command, target)
        age = None if self._last_api_command_monotonic is None else monotonic() - self._last_api_command_monotonic
        if current == self._last_api_command and not (age is not None and age >= self.config.write_refresh_interval_s):
            logger.info("[api] Active command skipped unchanged api_command=%s target_power_w=%s", command, target)
            return f"{command}:skipped_unchanged", None
        try:
            if call is None:
                logger.warning("[api] No stop_forced_mode command available on backend")
                self._last_api_command = current
                self._last_api_command_monotonic = monotonic()
                return command, False
            if command == "stop_forced_mode":
                await call()
            else:
                await call(target)
        except Exception:
            logger.exception("[api] Active command failed api_command=%s target_power_w=%s; battery likely not actively steered even if Modbus limits succeeded", command, target)
            return command, False
        self._last_api_command = current
        self._last_api_command_monotonic = monotonic()
        return command, True

    def publish_commanded_battery_state(self, api_command: str) -> None:
        """Optimistically publish the commanded battery state after GoodWe accepts it.

        GoodWe telemetry can lag behind an active charge/discharge command by a
        full polling interval. Publishing the accepted setpoint immediately lets
        downstream MQTT consumers display the active command without waiting for
        the next inverter readback.
        """
        if api_command == "charge":
            self.publish(MQTT_TOPIC_BATTERY_POWER_W, -self.target_charge_limit_w, retain=True)
            self.publish(MQTT_TOPIC_BATTERY_MODE, "charge", retain=True)
        elif api_command == "discharge":
            self.publish(MQTT_TOPIC_BATTERY_POWER_W, self.target_discharge_limit_w, retain=True)
            self.publish(MQTT_TOPIC_BATTERY_MODE, "discharge", retain=True)
        elif api_command == "stop_forced_mode":
            self.publish(MQTT_TOPIC_BATTERY_POWER_W, 0, retain=True)
            self.publish(MQTT_TOPIC_BATTERY_MODE, "idle", retain=True)

    def _record_skipped_modbus_write(self, reason: str) -> str:
        self.modbus_write_skipped_total += 1
        logger.info("[modbus] Limit write skipped reason=%s p1_grid_power_w=%s target_charge_limit_w=%s target_discharge_limit_w=%s current_charge_limit_w=%s current_discharge_limit_w=%s", reason, self._last_p1_grid_power_w, self.target_charge_limit_w, self.target_discharge_limit_w, self._last_charge_setpoint_w, self._last_discharge_setpoint_w)
        return f"skipped_{reason.replace(' ', '_')}"

    def _opposite_direction_settling(self, command: str, target_w: int) -> bool:
        if target_w <= 0 or self._last_api_telemetry_monotonic is None or self.config.min_write_interval_s <= 0:
            return False
        battery_power_w = self._last_api_battery_power_w
        if battery_power_w is None:
            return False
        age = monotonic() - self._last_api_telemetry_monotonic
        if age >= self.config.min_write_interval_s:
            return False
        opposite = (
            command == "charge" and battery_power_w > OPPOSITE_DIRECTION_SETTLE_POWER_W
        ) or (
            command == "discharge" and battery_power_w < -OPPOSITE_DIRECTION_SETTLE_POWER_W
        )
        if not opposite:
            return False
        self.modbus_write_skipped_total += 1
        self.publish_metrics()
        logger.warning(
            "[modbus|api] Actuator decision skipped reason=opposite direction settling requested_api_command=%s target_power_w=%s api_battery_power_w=%s telemetry_age_s=%.1f settle_window_s=%.1f p1_grid_power_w=%s",
            command,
            target_w,
            battery_power_w,
            age,
            self.config.min_write_interval_s,
            self._last_p1_grid_power_w,
        )
        return True

    def _skip_actuator_write(self, reason: str) -> None:
        self.modbus_write_skipped_total += 1
        self.publish_metrics()
        logger.info("[modbus|api] Actuator decision skipped reason=%s p1_grid_power_w=%s target_charge_limit_w=%s target_discharge_limit_w=%s current_charge_limit_w=%s current_discharge_limit_w=%s", reason, self._last_p1_grid_power_w, self.target_charge_limit_w, self.target_discharge_limit_w, self._last_charge_setpoint_w, self._last_discharge_setpoint_w)
        self._log_control_decision(self.target_charge_limit_w, self.target_discharge_limit_w, modbus_write_result=f"skipped_{reason.replace(' ', '_')}", api_command="skipped", api_command_success=None)

    def _log_control_decision(self, charge: int, discharge: int, *, modbus_write_result: str, api_command: str, api_command_success: bool | None) -> None:
        desired_state = "CHARGING" if charge > 0 and discharge <= 0 else "DISCHARGING" if discharge > 0 and charge <= 0 else self.control_state
        target_power_w = charge if desired_state == "CHARGING" else discharge if desired_state == "DISCHARGING" else 0
        signed_setpoint_w = charge if desired_state == "CHARGING" else -discharge if desired_state == "DISCHARGING" else 0
        reason = f"bridge actuator consequence; api_command={api_command} api_success={api_command_success} modbus_result={modbus_write_result}"
        logger.info(
            "[control] decision p1_grid_power_w=%s desired_state=%s target_power_w=%s api_command=%s api_command_success=%s modbus_charge_limit_w=%s modbus_discharge_limit_w=%s modbus_write_result=%s api_battery_power_w=%s api_grid_power_w=%s battery_soc=%s bridge_max_charge_a=%s bridge_max_allowed_charge_a=%s dry_run=%s note=modbus_limits_are_not_force_setpoints",
            self._last_p1_grid_power_w, desired_state, target_power_w, api_command, api_command_success, charge, discharge, modbus_write_result, self._last_api_battery_power_w, self._last_api_grid_power_w, self._last_api_battery_soc, self.config.max_charge_a, self.config.max_allowed_charge_a, self.config.dry_run,
        )
        self._insert_setpoint_log(
            signed_setpoint_w=signed_setpoint_w,
            discharge_allowed=signed_setpoint_w < 0,
            setpoint_delta=signed_setpoint_w - self._last_logged_signed_setpoint_w,
            reason=reason,
            ack_received=api_command_success is True,
        )
        self._last_logged_signed_setpoint_w = signed_setpoint_w

    def _insert_setpoint_log(self, *, signed_setpoint_w: int, discharge_allowed: bool, setpoint_delta: int, reason: str, ack_received: bool) -> None:
        if not self.config.database_url:
            return
        try:
            with closing(psycopg2.connect(psycopg2_database_url(self.config.database_url))) as conn:
                with conn.cursor() as cur:
                    cur.execute("select column_name from information_schema.columns where table_name=%s", ("setpoint_log",))
                    columns = {row[0] for row in cur.fetchall()}
                    if not columns:
                        return
                    setpoint_column = "setpoint_w" if "setpoint_w" in columns else "charge_rate_w"
                    insert_columns = ["source", "soc_floor", "soc_ceiling", setpoint_column, "discharge_allowed"]
                    values = ["%s", "%s", "%s", "%s", "%s"]
                    params: list[Any] = ["goodwe_bridge", 0, 100, signed_setpoint_w, discharge_allowed]
                    optional_values = {
                        "battery_soc_at_time": self._last_api_battery_soc,
                        "grid_power_at_time": self._last_p1_grid_power_w,
                        "battery_power_at_time": self._last_api_battery_power_w,
                        "setpoint_delta": setpoint_delta,
                        "trigger_reason": reason,
                        "ack_received": ack_received,
                        "ack_latency_ms": None,
                    }
                    for column, value in optional_values.items():
                        if column in columns:
                            insert_columns.append(column)
                            values.append("%s")
                            params.append(value)
                    cur.execute(
                        f"insert into setpoint_log ({', '.join(insert_columns)}) values ({', '.join(values)})",
                        params,
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("Unable to write bridge action to setpoint_log: %s", exc)

    async def poll_once(self) -> None:
        with READ_DURATION_SECONDS.time():
            state = await self.backend.read_state()
        self._last_api_battery_power_w = state.battery_power_w
        self._last_api_grid_power_w = state.grid_power_w
        self._last_api_telemetry_monotonic = monotonic()
        self._last_api_battery_soc = state.battery_soc
        self._check_charge_limit_effect(state)
        values = {
            "minyad/battery/soc": state.battery_soc,
            "minyad/battery/soh": state.battery_soh,
            MQTT_TOPIC_BATTERY_POWER_W: state.battery_power_w,
            "minyad/battery/voltage_v": state.battery_voltage_v,
            "minyad/battery/temperature_c": state.battery_temperature_c,
            MQTT_TOPIC_BATTERY_MODE: state.battery_mode,
            "minyad/inverter/temperature_c": state.inverter_temperature_c,
            "minyad/inverter/grid_power_w": state.grid_power_w,
            MQTT_TOPIC_INVERTER_STATUS: self._status_for_state(state),
        }
        for topic, value in values.items():
            if value is None:
                logger.debug("Skipping unavailable inverter value topic=%s", topic)
                continue
            self.publish(topic, value, retain=True)
        self.publish_bridge_alive()
        self.modbus_reads_total += 1
        self.last_successful_read_timestamp = time()
        LAST_SUCCESS_TIMESTAMP_SECONDS.set(self.last_successful_read_timestamp)
        if isinstance(state, BatteryTelemetry) and state.modbus_error and state.modbus_error != "disabled":
            self.modbus_errors_total += 1
            ERRORS_TOTAL.labels(type="modbus_read").inc()
        self.publish_metrics()
        logger.info(
            "Poll read success timestamp=%s soc=%s battery_power_w=%s inverter_grid_power_w=%s",
            utc_now_iso(),
            state.battery_soc,
            state.battery_power_w,
            state.grid_power_w,
        )

    def _check_charge_limit_effect(self, state: InverterState) -> None:
        if self._pending_charge_check is None:
            return
        started_at, charge_limit_w, previous_power = self._pending_charge_check
        if monotonic() - started_at < self.config.min_write_interval_s:
            return
        current_power = state.battery_power_w
        if current_power is None or current_power >= 0 or (previous_power is not None and current_power >= previous_power):
            logger.warning("charge limit applied but inverter did not start charging; limit registers are not force setpoints")
        self._pending_charge_check = None

    def _status_for_state(self, state: InverterState) -> str:
        if isinstance(state, BatteryTelemetry) and state.modbus_error and state.modbus_error != "disabled":
            return STATUS_UNREACHABLE
        return STATUS_OK

    def publish_metrics(self) -> None:
        metrics = {
            "modbus_reads_total": self.modbus_reads_total,
            "modbus_writes_total": self.modbus_writes_total,
            "modbus_write_skipped_total": self.modbus_write_skipped_total,
            "modbus_errors_total": self.modbus_errors_total,
            "last_successful_read_timestamp": self.last_successful_read_timestamp or "",
            "last_successful_write_timestamp": self.last_successful_write_timestamp or "",
            "current_charge_limit_w": self._last_charge_setpoint_w,
            "current_discharge_limit_w": self._last_discharge_setpoint_w,
            "target_charge_limit_w": self.target_charge_limit_w,
            "target_discharge_limit_w": self.target_discharge_limit_w,
        }
        for name, value in metrics.items():
            self.publish(f"minyad/bridge/metrics/{name}", value, retain=True)

    async def polling_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                await self.poll_once()
            except (ConnectionError, TimeoutError) as exc:
                READ_FAILURES_TOTAL.inc()
                ERRORS_TOTAL.labels(type="read_unavailable").inc()
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
                logger.warning("[modbus|api] Polling failed: %s", exc, exc_info=True)
            except Exception as exc:
                READ_FAILURES_TOTAL.inc()
                ERRORS_TOTAL.labels(type="read_error").inc()
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
                logger.warning("[modbus|api] Polling failed: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=self.load_poll_interval())
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.mqtt_client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
        self.mqtt_client.loop_start()
        await self.polling_loop()
        self.publish(MQTT_TOPIC_BRIDGE_STATUS, BRIDGE_STATUS_OFFLINE, retain=True)
        self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

    def request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.shutdown_event.set()


async def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    start_metrics_server()
    backend = build_backend(config)
    logger.info("[modbus|api] Using GoodWe protocols: modbus_enabled=%s api_enabled=%s dry_run=%s", config.goodwe_modbus_limits_enabled, config.goodwe_api_enabled, config.dry_run)
    bridge = GoodWeBridge(config, backend)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
