from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "minyad-agent"))
from tools import ToolExecutor, clip_setpoint  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.battery_calls = []
        self.decisions = []
        self.forecast_hours = []
        self.log_requests = []
        self.messages = []

    def set_battery(self, setpoint_w: int, duration_minutes: int = 15):
        self.battery_calls.append((setpoint_w, duration_minutes))
        return {"status": "ok"}

    def log_decision(self, payload):
        self.decisions.append(payload)
        return {"id": 1, "status": "logged"}

    def get_forecast(self, hours):
        self.forecast_hours.append(hours)
        return {"hours_ahead": hours, "points": []}

    def get_operational_logs(self, hours_lookback=24, limit=50, since=None, until=None):
        self.log_requests.append({
            "hours_lookback": hours_lookback,
            "limit": limit,
            "since": since,
            "until": until,
        })
        return {"logs": {"setpoint_log": []}}

    def send_message(self, payload):
        self.messages.append(payload)
        return {"id": 2}


def test_clip_setpoint_respects_inverter_and_soc_limits() -> None:
    state = {"battery": {"soc": 20}, "settings": {"battery": {"soc_floor": 20, "soc_ceiling": 90}}}

    assert clip_setpoint(-6000, state) == (0, [
        "setpoint clipped from -6000W to -5000W by inverter limit",
        "discharge clipped to 0W because SoC 20.0% <= configured minimum 20%",
    ])


def test_tool_executor_steers_battery_and_logs_auditable_snapshot() -> None:
    client = FakeClient()
    state = {"battery": {"soc": 55}, "grid": {"grid_net_power_w": 900}, "settings": {"battery": {"soc_floor": 20, "soc_ceiling": 90}}}
    forecast = {"hours_ahead": 12, "points": [{"timestamp": "2026-06-24T12:00:00+00:00", "power_w": 2500}]}
    operator_messages = [{"id": 7, "body": "Washer running"}]
    executor = ToolExecutor(client, state, forecast, dry_run=False, model="test-model", operator_messages=operator_messages)

    result = executor.execute("set_battery_setpoint", {"setpoint_w": -800, "duration_minutes": 20, "reasoning": "900W import trend and SoC 55%."})
    log_result = executor.execute("log_decision", {"action_taken": "hold", "reasoning": "logged", "confidence": "medium"})

    assert result["setpoint_w"] == -800
    assert result["dry_run"] is False
    assert client.battery_calls == [(-800, 20)]
    assert log_result == {"id": 1, "status": "logged"}
    assert client.decisions[0]["action_taken"] == "discharge"
    assert client.decisions[0]["setpoint_w"] == -800
    assert client.decisions[0]["input_snapshot"] == {"state": state, "forecast": forecast, "operator_messages": operator_messages}


def test_extended_forecast_tool_caps_horizon_to_api_limit() -> None:
    client = FakeClient()
    executor = ToolExecutor(client, {}, {}, dry_run=True, model="test-model")

    assert executor.execute("get_extended_forecast", {"hours_ahead": 72}) == {"hours_ahead": 48, "points": []}
    assert client.forecast_hours == [48]


def test_operational_logs_tool_caps_window_and_limit() -> None:
    client = FakeClient()
    executor = ToolExecutor(client, {}, {}, dry_run=True, model="test-model")

    result = executor.execute("get_operational_logs", {
        "hours_lookback": 999,
        "limit": 999,
        "since_iso": "2026-07-09T00:00:00+00:00",
        "until_iso": "2026-07-10T00:00:00+00:00",
    })

    assert result == {"logs": {"setpoint_log": []}}
    assert client.log_requests == [{
        "hours_lookback": 168,
        "limit": 100,
        "since": "2026-07-09T00:00:00+00:00",
        "until": "2026-07-10T00:00:00+00:00",
    }]


def test_send_message_can_reply_to_operator_thread() -> None:
    client = FakeClient()
    executor = ToolExecutor(client, {}, {}, dry_run=True, model="test-model")

    result = executor.execute("send_message", {
        "category": "reply",
        "subject": "Re: washer",
        "body": "I will account for the washer load in this cycle.",
        "severity": "normal",
        "thread_id": 7,
    })

    assert result == {"id": 2}
    assert client.messages == [{
        "category": "reply",
        "subject": "Re: washer",
        "body": "I will account for the washer load in this cycle.",
        "severity": "normal",
        "thread_id": 7,
        "sender": "agent",
    }]
