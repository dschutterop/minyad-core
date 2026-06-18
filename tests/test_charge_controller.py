from datetime import datetime, timedelta, timezone

from minyad.strategy.charge_controller import ChargeController, MODE_NORMAL, MODE_SOLAR_POOR, MODE_SOLAR_RICH


class FakeMqtt:
    def __init__(self):
        self.published = []
        self.subscriptions = []

    def subscribe(self, topic, handler):
        self.subscriptions.append((topic, handler))

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def fixed_now():
    return datetime(2026, 6, 18, 20, 0, tzinfo=timezone.utc)


def controller(settings=None):
    mqtt = FakeMqtt()
    c = ChargeController(mqtt, db_session_factory=settings or {"battery.max_charge_w": "1440"}, now=fixed_now, ack_timeout_seconds=0, debounce_seconds=0)
    return c, mqtt, c.db_session_factory


def test_normal_mode_without_forecast_data():
    c, _, _ = controller()
    decision = c.evaluate()
    assert decision.mode == MODE_NORMAL
    assert decision.soc_floor == 20
    assert decision.soc_ceiling == 80
    assert decision.setpoint_w == 0


def test_solar_rich_recalculation_selects_headroom_mode(monkeypatch):
    c, mqtt, db = controller()
    monkeypatch.setattr(c, "fetch_tomorrow_ghi", lambda: 5.2)
    mode = c.recalculate_daily()
    assert mode.mode == MODE_SOLAR_RICH
    assert mode.soc_floor == 30
    assert mode.soc_ceiling == 60
    assert db["strategy.active"]["mode"] == MODE_SOLAR_RICH
    assert any(topic == "minyad/strategy/active" for topic, _ in mqtt.published)


def test_solar_poor_recalculation_allows_high_but_safe_ceiling(monkeypatch):
    c, _, _ = controller()
    monkeypatch.setattr(c, "fetch_tomorrow_ghi", lambda: 0.9)
    mode = c.recalculate_daily()
    assert mode.mode == MODE_SOLAR_POOR
    assert mode.soc_floor == 20
    assert mode.soc_ceiling == 92
    assert mode.charge_rate_w == 1440


def test_floor_breach_enables_charge_and_blocks_discharge():
    settings = {"battery.max_charge_w": "1440", "strategy.active": {"mode": MODE_SOLAR_RICH, "soc_floor": 30, "soc_ceiling": 60, "setpoint_w": None, "reason": "test", "valid_until": fixed_now() + timedelta(hours=4)}}
    c, _, _ = controller(settings)
    c.handle_mqtt_message("minyad/battery/soc", b"25")
    c.handle_mqtt_message("minyad/battery/power_w", b"200")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"100")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert decision.discharge_allowed is False
    assert "floor breach" in decision.reason


def test_ceiling_breach_stops_charge_without_forced_discharge():
    c, _, _ = controller()
    c.handle_mqtt_message("minyad/battery/soc", b"82")
    c.handle_mqtt_message("minyad/battery/power_w", b"-250")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-150")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert decision.discharge_allowed is True
    assert "ceiling" in decision.reason


def test_apply_publishes_json_and_bridge_topics_and_logs_failed_ack():
    c, mqtt, db = controller()
    c.apply(c.evaluate())
    topics = [topic for topic, _ in mqtt.published]
    assert "minyad/battery/setpoint" in topics
    assert "minyad/control/charge_w" in topics
    assert db["setpoint_log"][0]["ack_received"] is False
    assert "apparent_load_at_time" in db["setpoint_log"][0]


def test_manual_override_clamps_to_24h_and_100_percent():
    c, _, db = controller()
    c.override(5, 100, fixed_now() + timedelta(days=2))
    active = db["strategy.active"]
    assert active["mode"] == "MANUAL_OVERRIDE"
    assert active["soc_floor"] == 10
    assert active["soc_ceiling"] == 100


def test_balancing_grid_import_while_battery_discharging():
    c, _, _ = controller()
    c.handle_mqtt_message("minyad/battery/power_w", b"200")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"100")
    decision = c.evaluate()
    assert decision.setpoint_w == 300
    assert decision.grid_power_at_eval == 100
    assert decision.battery_power_at_eval == 200
    assert decision.apparent_load_at_eval == 300
    assert decision.setpoint_delta == 100


def test_balancing_grid_export_while_battery_idle():
    c, _, _ = controller()
    c.handle_mqtt_message("minyad/battery/power_w", b"0")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-150")
    decision = c.evaluate()
    assert decision.setpoint_w == -150
    assert decision.setpoint_delta == -150


def test_prompt_json_topics_are_accepted_for_telemetry():
    c, _, _ = controller()
    c.handle_mqtt_message("goodwe/battery", b'{"soc": 50, "battery_power": 400}')
    c.handle_mqtt_message("dsmr/reading", b'{"current_electricity_usage": 0.45, "current_electricity_delivery": 0.0}')
    decision = c.evaluate()
    assert decision.setpoint_w == 850


def test_jitter_suppression_reuses_last_setpoint():
    c, _, _ = controller()
    c._last_setpoint_w = 300
    c.handle_mqtt_message("minyad/battery/power_w", b"280")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"40")
    decision = c.evaluate()
    assert decision.setpoint_w == 300
    assert "jitter suppressed" in decision.reason
