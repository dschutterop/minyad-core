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
BATTERY_POLL_INTERVAL_SETTING = "battery.inverter_poll_interval_s"
POLL_INTERVAL_SEC = 2
MIN_WRITE_INTERVAL_SEC = 10
MIN_TARGET_CHANGE_W = 150
WRITE_REFRESH_INTERVAL_SEC = 600
DEFAULT_POLL_INTERVAL_SECONDS = POLL_INTERVAL_SEC

MQTT_TOPIC_INVERTER_STATUS = "minyad/inverter/status"
MQTT_TOPIC_BRIDGE_STATUS = "minyad/bridge/status"
MQTT_TOPIC_BRIDGE_LAST_SEEN = "minyad/bridge/last_seen"
BRIDGE_STATUS_ONLINE = "online"
BRIDGE_STATUS_OFFLINE = "offline"
STATUS_OK = "ok"
STATUS_UNREACHABLE = "unreachable"
STATUS_ERROR = "error"
CLIENT_ID = "goodwe-bridge"


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
    goodwe_modbus_enabled: bool
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
    dry_run: bool
    log_level: str
    min_write_interval_s: float
    min_target_change_w: int
    write_refresh_interval_s: float

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST")
        if not mqtt_host:
            raise ValueError("MQTT_BROKER is required")

        legacy_backend = os.getenv("INVERTER_BACKEND")
        if legacy_backend:
            logger.warning("INVERTER_BACKEND is deprecated; use GOODWE_MODBUS_ENABLED and GOODWE_API_ENABLED")
        goodwe_api_host = os.getenv("GOODWE_API_HOST", "").strip() or None
        goodwe_modbus_enabled = os.getenv("GOODWE_MODBUS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        goodwe_api_enabled = os.getenv("GOODWE_API_ENABLED", "").lower() in {"1", "true", "yes", "on"} if os.getenv("GOODWE_API_ENABLED") is not None else goodwe_api_host is not None
        if goodwe_api_enabled and not goodwe_api_host:
            raise ValueError("GOODWE_API_HOST is required when GOODWE_API_ENABLED=true")
        if not goodwe_modbus_enabled and not goodwe_api_enabled:
            raise ValueError("At least one of GOODWE_MODBUS_ENABLED or GOODWE_API_ENABLED must be true")

        max_charge_a = _get_env_int("MAX_CHARGE_A", 30)
        return cls(
            goodwe_modbus_enabled=goodwe_modbus_enabled,
            goodwe_api_enabled=goodwe_api_enabled,
            goodwe_api_host=goodwe_api_host,
            inverter_max_w=_get_env_int("INVERTER_MAX_W", _get_env_int("MAX_DISCHARGE_W", 5000)),
            inverter_retries=_get_env_int("INVERTER_RETRIES", 5),
            inverter_delay=_get_env_int("INVERTER_DELAY", 3),
            goodwe_min_request_interval_s=_get_env_float("GOODWE_MIN_REQUEST_INTERVAL_S", 2.0),
            modbus_gw_ip=_get_required_env("MODBUS_GW_IP"),
            modbus_gw_port=_get_env_int("MODBUS_GW_PORT", 502),
            modbus_slave_id=_get_env_int("MODBUS_SLAVE_ID", 247),
            modbus_timeout=_get_env_float("MODBUS_TIMEOUT", 5.0),
            mqtt_host=mqtt_host,
            mqtt_port=_get_env_int("MQTT_PORT", 1883),
            mqtt_user=os.getenv("MQTT_USER"),
            mqtt_pass=os.getenv("MQTT_PASS"),
            poll_interval=_get_env_int("POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS),
            database_url=os.getenv("DB_URL") or os.getenv("DATABASE_URL"),
            max_charge_a=min(max_charge_a, 30),
            dry_run=os.getenv("GOODWE_DRY_RUN", os.getenv("DRY_RUN", "false")).lower() in {"1", "true", "yes", "on"},
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            min_write_interval_s=_get_env_float("MIN_WRITE_INTERVAL_SEC", MIN_WRITE_INTERVAL_SEC),
            min_target_change_w=_get_env_int("MIN_TARGET_CHANGE_W", MIN_TARGET_CHANGE_W),
            write_refresh_interval_s=_get_env_float("WRITE_REFRESH_INTERVAL_SEC", WRITE_REFRESH_INTERVAL_SEC),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_backend(config: Config) -> InverterBackend:
    modbus_client: InverterBackend | None = None
    api_client: InverterBackend | None = None
    if config.goodwe_modbus_enabled:
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
        )
    return GoodWeCompositeBackend(modbus_client, api_client)


class GoodWeBridge:
    def __init__(self, config: Config, backend: InverterBackend) -> None:
        self.config = config
        self.backend = backend
        self.loop: asyncio.AbstractEventLoop | None = None
        self.shutdown_event = asyncio.Event()
        self.mqtt_client = mqtt.Client(client_id=CLIENT_ID, clean_session=False, protocol=mqtt.MQTTv311)
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
            with closing(psycopg2.connect(self.config.database_url)) as conn:
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

    def on_connect(self, client: mqtt.Client, _userdata: Any, _flags: dict[str, Any], rc: int) -> None:
        if rc == 0:
            logger.info("MQTT connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
            client.subscribe([(MQTT_TOPIC_CHARGE_W, 1), (MQTT_TOPIC_DISCHARGE_W, 1), (MQTT_TOPIC_CONTROL_STATE, 1), (MQTT_TOPIC_BATTERY_POLL_INTERVAL, 1), (MQTT_TOPIC_DSMR_NET_POWER, 1), (MQTT_TOPIC_GRID_NET_POWER, 1)])
            self.publish_bridge_alive()
        else:
            logger.error("MQTT connection failed with rc=%s", rc)

    def on_disconnect(self, _client: mqtt.Client, _userdata: Any, rc: int) -> None:
        logger.warning("MQTT disconnected with rc=%s", rc)

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
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)
        except Exception as exc:
            self.publish_bridge_alive()
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
            logger.warning("Immediate polling failed: %s", exc, exc_info=True)

    async def handle_charge_setpoint(self, watts: int) -> None:
        self.target_charge_limit_w = max(0, int(watts))
        await self._apply_actuator_targets(state_changed=self.control_state == "CHARGING")

    async def handle_discharge_setpoint(self, watts: int) -> None:
        self.target_discharge_limit_w = max(0, int(watts))
        await self._apply_actuator_targets(state_changed=self.control_state == "DISCHARGING")

    async def _apply_actuator_targets(self, *, state_changed: bool = False) -> None:
        if self._last_p1_grid_power_w is None or (self._last_p1_grid_power_monotonic is not None and monotonic() - self._last_p1_grid_power_monotonic > 60):
            self._skip_actuator_write("stale P1 data")
            return
        charge = self.target_charge_limit_w
        discharge = self.target_discharge_limit_w
        unchanged = charge == self._last_charge_setpoint_w and discharge == self._last_discharge_setpoint_w
        age = None if self._last_write_monotonic is None else monotonic() - self._last_write_monotonic
        if unchanged and not (age is not None and age >= self.config.write_refresh_interval_s):
            self._skip_actuator_write("unchanged target")
            return
        delta = max(abs(charge - self._last_charge_setpoint_w), abs(discharge - self._last_discharge_setpoint_w))
        if not state_changed and delta < self.config.min_target_change_w and not unchanged:
            self._skip_actuator_write("below min delta")
            return
        if age is not None and age < self.config.min_write_interval_s:
            self._skip_actuator_write("write interval not elapsed")
            return
        try:
            await self.backend.set_battery_limits(charge, discharge)
        except (ConnectionError, TimeoutError):
            self._skip_actuator_write("modbus unavailable")
            self.modbus_errors_total += 1
            logger.exception("Modbus unavailable while applying charge_w=%s discharge_w=%s", charge, discharge)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
            return
        except Exception:
            self.modbus_errors_total += 1
            logger.exception("Failed to apply charge_w=%s discharge_w=%s", charge, discharge)
            self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
            return
        self._last_charge_setpoint_w = charge
        self._last_discharge_setpoint_w = discharge
        self._last_write_monotonic = monotonic()
        self.last_successful_write_timestamp = time()
        self.modbus_writes_total += 1
        self.publish_metrics()
        logger.info("Actuator write success p1_grid_power_w=%s charge_limit_w=%s discharge_limit_w=%s dry_run=%s", self._last_p1_grid_power_w, charge, discharge, self.config.dry_run)

    def _skip_actuator_write(self, reason: str) -> None:
        self.modbus_write_skipped_total += 1
        self.publish_metrics()
        logger.info("Actuator write skipped reason=%s p1_grid_power_w=%s target_charge_limit_w=%s target_discharge_limit_w=%s current_charge_limit_w=%s current_discharge_limit_w=%s", reason, self._last_p1_grid_power_w, self.target_charge_limit_w, self.target_discharge_limit_w, self._last_charge_setpoint_w, self._last_discharge_setpoint_w)

    async def poll_once(self) -> None:
        state = await self.backend.read_state()
        values = {
            "minyad/battery/soc": state.battery_soc,
            "minyad/battery/soh": state.battery_soh,
            "minyad/battery/power_w": state.battery_power_w,
            "minyad/battery/voltage_v": state.battery_voltage_v,
            "minyad/battery/temperature_c": state.battery_temperature_c,
            "minyad/battery/mode": state.battery_mode,
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
        if isinstance(state, BatteryTelemetry) and state.modbus_error and state.modbus_error != "disabled":
            self.modbus_errors_total += 1
        self.publish_metrics()
        logger.info(
            "Poll read success timestamp=%s soc=%s battery_power_w=%s inverter_grid_power_w=%s",
            utc_now_iso(),
            state.battery_soc,
            state.battery_power_w,
            state.grid_power_w,
        )

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
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_UNREACHABLE, retain=True)
                logger.warning("Polling failed: %s", exc, exc_info=True)
            except Exception as exc:
                self.publish_bridge_alive()
                self.publish(MQTT_TOPIC_INVERTER_STATUS, STATUS_ERROR, retain=True)
                logger.warning("Polling failed: %s", exc, exc_info=True)

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
    backend = build_backend(config)
    logger.info("Using GoodWe protocols: modbus_enabled=%s api_enabled=%s dry_run=%s", config.goodwe_modbus_enabled, config.goodwe_api_enabled, config.dry_run)
    bridge = GoodWeBridge(config, backend)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.request_shutdown)

    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
