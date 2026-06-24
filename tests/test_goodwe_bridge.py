import asyncio
import importlib.util
import sys
import types
from pathlib import Path


def install_import_stubs() -> None:
    if "paho.mqtt.client" not in sys.modules:
        paho = types.ModuleType("paho")
        mqtt_package = types.ModuleType("paho.mqtt")
        mqtt_client = types.ModuleType("paho.mqtt.client")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.subscriptions = []
                self.published = []
                self.on_connect = None
                self.on_disconnect = None
                self.on_message = None

            def will_set(self, *args, **kwargs):
                pass

            def username_pw_set(self, *args, **kwargs):
                pass

            def reconnect_delay_set(self, *args, **kwargs):
                pass

            def subscribe(self, subscriptions):
                self.subscriptions.extend(subscriptions)

            def publish(self, topic, payload, retain=True):
                self.published.append((topic, payload, retain))

        mqtt_client.Client = FakeClient
        mqtt_client.MQTTv311 = 4
        paho.mqtt = mqtt_package
        mqtt_package.client = mqtt_client
        sys.modules["paho"] = paho
        sys.modules["paho.mqtt"] = mqtt_package
        sys.modules["paho.mqtt.client"] = mqtt_client
    if "psycopg2" not in sys.modules:
        sys.modules["psycopg2"] = types.ModuleType("psycopg2")
    if "dotenv" not in sys.modules:
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules["dotenv"] = dotenv


install_import_stubs()
HOST_SERVICES = Path(__file__).resolve().parents[1] / "host-services"
if str(HOST_SERVICES) not in sys.path:
    sys.path.insert(0, str(HOST_SERVICES))
MODULE_PATH = HOST_SERVICES / "goodwe_bridge.py"
spec = importlib.util.spec_from_file_location("goodwe_bridge", MODULE_PATH)
from backends import InverterState

goodwe_bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["goodwe_bridge"] = goodwe_bridge
spec.loader.exec_module(goodwe_bridge)


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.subscriptions = []
        self.published = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def will_set(self, *args, **kwargs):
        pass

    def username_pw_set(self, *args, **kwargs):
        pass

    def reconnect_delay_set(self, *args, **kwargs):
        pass

    def subscribe(self, subscriptions):
        self.subscriptions.extend(subscriptions)

    def publish(self, topic, payload, retain=True):
        self.published.append((topic, str(payload), retain))


class Backend:
    def __init__(self):
        self.charge_setpoints = []
        self.discharge_setpoints = []
        self.battery_limits = []

    async def read_state(self):
        return InverterState(
            battery_soc=81,
            battery_soh=99,
            battery_power_w=384,
            battery_voltage_v=52.1,
            battery_temperature_c=23.4,
            battery_mode="discharging",
            inverter_temperature_c=34.5,
            grid_power_w=384,
        )

    async def set_charge(self, watts):
        self.charge_setpoints.append(watts)

    async def set_discharge(self, watts):
        self.discharge_setpoints.append(watts)

    async def set_battery_limits(self, charge_limit_w, discharge_limit_w):
        self.battery_limits.append((charge_limit_w, discharge_limit_w))
        self.charge_setpoints.append(charge_limit_w)
        self.discharge_setpoints.append(discharge_limit_w)


def make_config():
    return goodwe_bridge.Config(
        goodwe_modbus_enabled=True,
        goodwe_api_enabled=True,
        goodwe_api_host="http://goodwe",
        inverter_max_w=5000,
        inverter_retries=5,
        inverter_delay=3,
        goodwe_min_request_interval_s=2.0,
        modbus_gw_ip="127.0.0.1",
        modbus_gw_port=502,
        modbus_slave_id=247,
        modbus_timeout=5.0,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_user=None,
        mqtt_pass=None,
        poll_interval=120,
        database_url=None,
        max_charge_a=30,
        dry_run=False,
        log_level="INFO",
        min_write_interval_s=0.0,
        min_target_change_w=0,
        write_refresh_interval_s=600.0,
    )


def test_subscribes_to_control_state_topic(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())

    bridge.on_connect(bridge.mqtt_client, None, {}, 0)

    assert (goodwe_bridge.MQTT_TOPIC_CONTROL_STATE, 1) in bridge.mqtt_client.subscriptions


def test_idle_to_active_state_triggers_immediate_battery_status_poll(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())
        bridge.loop = asyncio.get_running_loop()

        bridge.handle_control_state("DISCHARGING")
        assert bridge._immediate_poll_task is not None
        await asyncio.wrap_future(bridge._immediate_poll_task)

        assert ("minyad/battery/power_w", "384", True) in bridge.mqtt_client.published
        assert (goodwe_bridge.MQTT_TOPIC_INVERTER_STATUS, "ok", True) in bridge.mqtt_client.published

    asyncio.run(run())


def test_active_to_active_state_does_not_trigger_immediate_poll(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())
    bridge.control_state = "CHARGING"
    bridge.loop = asyncio.new_event_loop()
    try:
        bridge.handle_control_state("DISCHARGING")
        assert bridge._immediate_poll_task is None
    finally:
        bridge.loop.close()


def test_unchanged_charge_setpoint_is_not_written_twice(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = Backend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)

        await bridge.handle_charge_setpoint(750)
        await bridge.handle_charge_setpoint(750)
        await bridge.handle_charge_setpoint(0)

        assert backend.charge_setpoints == [750, 0]

    asyncio.run(run())


def test_unchanged_discharge_setpoint_is_not_written_twice(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = Backend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)

        await bridge.handle_discharge_setpoint(425)
        await bridge.handle_discharge_setpoint(425)
        await bridge.handle_discharge_setpoint(0)

        assert backend.discharge_setpoints == [425, 0]

    asyncio.run(run())


def test_subscribes_to_battery_poll_interval_setting_topic(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())

    bridge.on_connect(bridge.mqtt_client, None, {}, 0)

    assert (goodwe_bridge.MQTT_TOPIC_BATTERY_POLL_INTERVAL, 1) in bridge.mqtt_client.subscriptions


def test_poll_interval_can_be_driven_by_retained_mqtt(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    config = make_config()
    bridge = goodwe_bridge.GoodWeBridge(config, Backend())
    bridge.loop = asyncio.new_event_loop()

    class Message:
        topic = goodwe_bridge.MQTT_TOPIC_BATTERY_POLL_INTERVAL
        payload = b"45"

    try:
        bridge.on_message(bridge.mqtt_client, None, Message())
        assert bridge.load_poll_interval() == 45
    finally:
        bridge.loop.close()


def test_invalid_mqtt_poll_interval_keeps_previous_value(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())

    bridge.handle_poll_interval("30")
    bridge.handle_poll_interval("0")
    bridge.handle_poll_interval("invalid")

    assert bridge.load_poll_interval() == 30


def test_subscribes_to_grid_power_topics_for_actuator_logging(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())

    bridge.on_connect(bridge.mqtt_client, None, {}, 0)

    assert (goodwe_bridge.MQTT_TOPIC_DSMR_NET_POWER, 1) in bridge.mqtt_client.subscriptions
    assert (goodwe_bridge.MQTT_TOPIC_GRID_NET_POWER, 1) in bridge.mqtt_client.subscriptions


def test_grid_power_topic_is_remembered_for_actuator_boundary(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())
    bridge.loop = asyncio.new_event_loop()

    class Message:
        topic = goodwe_bridge.MQTT_TOPIC_GRID_NET_POWER
        payload = b"-321"

    try:
        bridge.on_message(bridge.mqtt_client, None, Message())
        assert bridge._last_p1_grid_power_w == -321
    finally:
        bridge.loop.close()


class PartialBackend(Backend):
    async def read_state(self):
        return InverterState(
            battery_soc=None,
            battery_soh=None,
            battery_power_w=-123,
            battery_voltage_v=51.8,
            battery_temperature_c=None,
            battery_mode="charge",
            inverter_temperature_c=None,
            grid_power_w=None,
        )


def test_poll_once_skips_unavailable_modbus_values_instead_of_publishing_zeroes(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        bridge = goodwe_bridge.GoodWeBridge(make_config(), PartialBackend())
        await bridge.poll_once()
        return bridge.mqtt_client.published

    published = asyncio.run(run())
    topics = [topic for topic, _payload, _retain in published]
    assert "minyad/battery/power_w" in topics
    assert "minyad/battery/voltage_v" in topics
    assert "minyad/battery/mode" in topics
    assert "minyad/battery/soc" not in topics
    assert "minyad/battery/soh" not in topics
    assert "minyad/inverter/grid_power_w" not in topics
