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
        pass

    async def set_discharge(self, watts):
        pass


def make_config():
    return goodwe_bridge.Config(
        inverter_backend="goodwe",
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
        log_level="INFO",
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
