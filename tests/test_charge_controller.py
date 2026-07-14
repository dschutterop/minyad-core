from datetime import UTC, datetime, timedelta

from minyad.strategy.charge_controller import (
    MODE_NORMAL,
    MODE_SOLAR_POOR,
    MODE_SOLAR_RICH,
    ChargeController,
)


class FakeMqtt:
    def __init__(self):
        self.published = []
        self.subscriptions = []

    def subscribe(self, topic, handler):
        self.subscriptions.append((topic, handler))

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def fixed_now():
    return datetime(2026, 6, 18, 20, 0, tzinfo=UTC)


def controller(settings=None, now=fixed_now):
    mqtt = FakeMqtt()
    defaults = {"battery.max_charge_w": "1440", "strategy.ramp_hold_seconds": "0", "strategy.ramp_floor_w": "0"}
    if settings:
        defaults.update(settings)
    c = ChargeController(mqtt, db_session_factory=defaults, now=now, ack_timeout_seconds=0, debounce_seconds=0)
    return c, mqtt, c.db_session_factory


def test_normal_mode_without_forecast_data():
    c, _, _ = controller()
    decision = c.evaluate()
    assert decision.mode == MODE_NORMAL
    assert decision.soc_floor == 20
    assert decision.soc_ceiling == 90
    assert decision.setpoint_w == 0


def test_solar_rich_recalculation_selects_headroom_mode(monkeypatch):
    c, mqtt, db = controller()
    monkeypatch.setattr(c, "fetch_tomorrow_ghi", lambda: 5.2)
    mode = c.recalculate_daily()
    assert mode.mode == MODE_SOLAR_RICH
    assert mode.soc_floor == 20
    assert mode.soc_ceiling == 90
    assert db["strategy.active"]["mode"] == MODE_SOLAR_RICH
    assert any(topic == "minyad/strategy/active" for topic, _ in mqtt.published)


def test_solar_poor_recalculation_allows_high_but_safe_ceiling(monkeypatch):
    c, _, _ = controller()
    monkeypatch.setattr(c, "fetch_tomorrow_ghi", lambda: 0.9)
    mode = c.recalculate_daily()
    assert mode.mode == MODE_SOLAR_POOR
    assert mode.soc_floor == 20
    assert mode.soc_ceiling == 90
    assert mode.charge_rate_w == 1440


def test_configured_soc_limits_drive_default_strategy_mode():
    c, _, _ = controller({"battery.soc_floor": "35", "battery.soc_ceiling": "70"})
    decision = c.evaluate()
    assert decision.soc_floor == 35
    assert decision.soc_ceiling == 70


def test_configured_soc_floor_blocks_discharge():
    c, _, _ = controller({"battery.soc_floor": "35", "battery.soc_ceiling": "70"})
    c.handle_mqtt_message("minyad/battery/soc", b"35")
    c.handle_mqtt_message("minyad/battery/power_w", b"0")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"300")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert decision.discharge_allowed is False
    assert "floor breach" in decision.reason


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
    c.handle_mqtt_message("minyad/battery/soc", b"92")
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
    assert active["soc_floor"] == 5
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


def test_grid_export_blocks_existing_battery_discharge():
    c, _, _ = controller()
    c.handle_mqtt_message("minyad/battery/power_w", b"1118")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-150")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert decision.discharge_allowed is False
    assert "discharge blocked during export/surplus" in decision.reason


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


def test_ramp_hysteresis_waits_for_configured_hold_time():
    current = {"value": fixed_now()}
    c, _, _ = controller({"strategy.ramp_hold_seconds": "120", "strategy.ramp_floor_w": "200", "strategy.ramp_ceiling_w": "1000"}, now=lambda: current["value"])
    c.handle_mqtt_message("minyad/battery/power_w", b"0")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-201")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert "ramp hold started" in decision.reason

    current["value"] = fixed_now() + timedelta(seconds=119)
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-1201")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert "ramp hold active" in decision.reason

    current["value"] = fixed_now() + timedelta(seconds=120)
    decision = c.evaluate()
    assert decision.setpoint_w == -1000
    assert decision.setpoint_delta == -1000
    assert "ramp hold satisfied" in decision.reason


def test_ramp_hysteresis_handles_import_direction_after_export():
    current = {"value": fixed_now()}
    c, _, _ = controller({"strategy.ramp_hold_seconds": "120", "strategy.ramp_floor_w": "200", "strategy.ramp_ceiling_w": "1000"}, now=lambda: current["value"])
    c.handle_mqtt_message("minyad/battery/power_w", b"0")
    c.handle_mqtt_message("minyad/grid/net_power_w", b"-500")
    assert c.evaluate().setpoint_w == 0

    current["value"] = fixed_now() + timedelta(seconds=120)
    c.handle_mqtt_message("minyad/grid/net_power_w", b"500")
    decision = c.evaluate()
    assert decision.setpoint_w == 0
    assert "import" in decision.reason

    current["value"] = fixed_now() + timedelta(seconds=240)
    decision = c.evaluate()
    assert decision.setpoint_w == 500
