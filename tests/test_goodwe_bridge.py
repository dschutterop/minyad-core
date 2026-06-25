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
                self.args = args
                self.kwargs = kwargs
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
        mqtt_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
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
        self.args = args
        self.kwargs = kwargs
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

    async def set_battery_limits(self, charge_limit_w, discharge_limit_w, *, state_changed=False):
        self.battery_limits.append((charge_limit_w, discharge_limit_w))
        self.charge_setpoints.append(charge_limit_w)
        self.discharge_setpoints.append(discharge_limit_w)


def make_config():
    return goodwe_bridge.Config(
        goodwe_modbus_limits_enabled=True,
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
        max_allowed_charge_a=30,
        dry_run=False,
        log_level="INFO",
        min_write_interval_s=0.0,
        min_target_change_w=0,
        write_refresh_interval_s=600.0,
        default_charge_limit_w=6000,
        default_discharge_limit_w=6000,
        conservative_charge_limit_w=1500,
        conservative_discharge_limit_w=1500,
    )


def test_subscribes_to_control_state_topic(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), Backend())

    bridge.on_connect(bridge.mqtt_client, None, {}, types.SimpleNamespace(is_failure=False), None)

    assert (goodwe_bridge.MQTT_TOPIC_CONTROL_STATE, 1) in bridge.mqtt_client.subscriptions
    assert bridge.mqtt_client.args[0] == goodwe_bridge.mqtt.CallbackAPIVersion.VERSION2


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

    bridge.on_connect(bridge.mqtt_client, None, {}, types.SimpleNamespace(is_failure=False), None)

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

    bridge.on_connect(bridge.mqtt_client, None, {}, types.SimpleNamespace(is_failure=False), None)

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


def test_bridge_does_not_log_success_when_backend_skips_actuator_write(monkeypatch):
    class SkippingBackend(Backend):
        async def set_battery_limits(self, charge_limit_w, discharge_limit_w, *, state_changed=False):
            await super().set_battery_limits(charge_limit_w, discharge_limit_w, state_changed=state_changed)
            return False

    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)
    bridge = goodwe_bridge.GoodWeBridge(make_config(), SkippingBackend())
    bridge._last_p1_grid_power_w = -2493
    bridge._last_p1_grid_power_monotonic = goodwe_bridge.monotonic()

    asyncio.run(bridge.handle_charge_setpoint(2411))

    assert bridge.modbus_writes_total == 0
    assert bridge.modbus_write_skipped_total == 1
    assert bridge._last_charge_setpoint_w == 0


class MutablePowerBackend(Backend):
    def __init__(self):
        super().__init__()
        self.power = 100

    async def read_state(self):
        state = await super().read_state()
        return InverterState(
            battery_soc=state.battery_soc,
            battery_soh=state.battery_soh,
            battery_power_w=self.power,
            battery_voltage_v=state.battery_voltage_v,
            battery_temperature_c=state.battery_temperature_c,
            battery_mode=state.battery_mode,
            inverter_temperature_c=state.inverter_temperature_c,
            grid_power_w=state.grid_power_w,
        )


def test_warns_when_charge_limit_does_not_force_charging(monkeypatch, caplog):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = MutablePowerBackend()
        config = make_config()
        bridge = goodwe_bridge.GoodWeBridge(config, backend)
        bridge.control_state = "CHARGING"
        await bridge.poll_once()
        await bridge.handle_charge_setpoint(1500)
        await bridge.poll_once()

    asyncio.run(run())

    assert "charge limit applied but inverter did not start charging; limit registers are not force setpoints" in caplog.text

class CommandBackend(Backend):
    def __init__(self):
        super().__init__()
        self.api_commands = []
        self.fail_api = False
        self.skip_modbus = False

    async def set_charge(self, watts):
        if self.fail_api:
            raise RuntimeError("api down")
        self.api_commands.append(("charge", watts))

    async def set_discharge(self, watts):
        if self.fail_api:
            raise RuntimeError("api down")
        self.api_commands.append(("discharge", watts))

    async def stop_forced_mode(self):
        if self.fail_api:
            raise RuntimeError("api down")
        self.api_commands.append(("stop_forced_mode", 0))

    async def set_battery_limits(self, charge_limit_w, discharge_limit_w, *, state_changed=False):
        self.battery_limits.append((charge_limit_w, discharge_limit_w))
        if self.skip_modbus:
            return False
        return True


def test_export_charging_sends_api_charge_command_and_modbus_charge_limit(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("-1200")
        bridge.control_state = "CHARGING"
        await bridge.handle_charge_setpoint(1100)
        assert backend.battery_limits == [(1100, 0)]
        assert backend.api_commands == [("charge", 1100)]
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_POWER_W, "-1100", True) in bridge.mqtt_client.published
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_MODE, "charge", True) in bridge.mqtt_client.published

    asyncio.run(run())


def test_import_discharging_sends_api_discharge_command_and_modbus_discharge_limit(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("900")
        bridge.control_state = "DISCHARGING"
        await bridge.handle_discharge_setpoint(800)
        assert backend.battery_limits == [(0, 800)]
        assert backend.api_commands == [("discharge", 800)]
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_POWER_W, "800", True) in bridge.mqtt_client.published
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_MODE, "discharge", True) in bridge.mqtt_client.published

    asyncio.run(run())


def test_idle_stops_forced_mode(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("0")
        bridge.control_state = "IDLE"
        await bridge.handle_charge_setpoint(0)
        assert backend.api_commands == [("stop_forced_mode", 0)]
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_POWER_W, "0", True) in bridge.mqtt_client.published
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_MODE, "idle", True) in bridge.mqtt_client.published

    asyncio.run(run())


def test_unchanged_api_command_is_not_sent_twice(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("1000")
        bridge.control_state = "DISCHARGING"
        await bridge.handle_discharge_setpoint(700)
        await bridge._apply_api_command(0, 700)
        assert backend.api_commands == [("discharge", 700)]

    asyncio.run(run())


def test_api_command_failure_is_not_masked_by_successful_modbus_write(monkeypatch, caplog):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        backend.fail_api = True
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("1000")
        bridge.control_state = "DISCHARGING"
        await bridge.handle_discharge_setpoint(600)
        assert backend.battery_limits == [(0, 600)]
        assert bridge.modbus_writes_total == 1
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_POWER_W, "600", True) not in bridge.mqtt_client.published
        assert (goodwe_bridge.MQTT_TOPIC_BATTERY_MODE, "discharge", True) not in bridge.mqtt_client.published

    asyncio.run(run())
    assert "Active command failed" in caplog.text
    assert "battery likely not actively steered" in caplog.text


def test_modbus_skipped_unchanged_does_not_count_as_failure(monkeypatch):
    monkeypatch.setattr(goodwe_bridge.mqtt, "Client", FakeClient)

    async def run():
        backend = CommandBackend()
        backend.skip_modbus = True
        bridge = goodwe_bridge.GoodWeBridge(make_config(), backend)
        bridge.handle_grid_power("1000")
        bridge.control_state = "DISCHARGING"
        await bridge.handle_discharge_setpoint(600)
        assert bridge.modbus_errors_total == 0
        assert bridge.modbus_write_skipped_total == 1
        assert backend.api_commands == [("discharge", 600)]

    asyncio.run(run())


def _set_required_bridge_env(monkeypatch, *, max_charge_a: str, max_allowed_charge_a: str | None):
    monkeypatch.setenv("MQTT_BROKER", "mqtt")
    monkeypatch.setenv("GOODWE_API_HOST", "http://goodwe")
    monkeypatch.setenv("MODBUS_GW_IP", "127.0.0.1")
    monkeypatch.setenv("MAX_CHARGE_A", max_charge_a)
    if max_allowed_charge_a is None:
        monkeypatch.delenv("MAX_ALLOWED_CHARGE_A", raising=False)
        monkeypatch.delenv("GOODWE_MAX_ALLOWED_CHARGE_A", raising=False)
    else:
        monkeypatch.setenv("MAX_ALLOWED_CHARGE_A", max_allowed_charge_a)


def test_config_allows_60a_when_safety_ceiling_is_60(monkeypatch):
    _set_required_bridge_env(monkeypatch, max_charge_a="60", max_allowed_charge_a="60")

    config = goodwe_bridge.Config.from_env()

    assert config.max_charge_a == 60
    assert config.max_allowed_charge_a == 60


def test_config_clamps_60a_to_explicit_30a_safety_ceiling(monkeypatch, caplog):
    _set_required_bridge_env(monkeypatch, max_charge_a="60", max_allowed_charge_a="30")

    with caplog.at_level("WARNING", logger=goodwe_bridge.LOGGER_NAME):
        config = goodwe_bridge.Config.from_env()

    assert config.max_charge_a == 30
    assert config.max_allowed_charge_a == 30
    assert "requested_max_charge_a=60" in caplog.text
    assert "bridge_max_allowed_charge_a=30" in caplog.text
    assert "clamp_reason=MAX_CHARGE_A_above_MAX_ALLOWED_CHARGE_A" in caplog.text


def test_config_has_no_hidden_30a_cap_when_safety_ceiling_is_raised(monkeypatch):
    _set_required_bridge_env(monkeypatch, max_charge_a="73", max_allowed_charge_a="200")

    config = goodwe_bridge.Config.from_env()

    assert config.max_charge_a == 73
