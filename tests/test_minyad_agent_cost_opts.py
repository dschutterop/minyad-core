"""Tests for the cost-optimisation additions to minyad-agent/agent.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "minyad-agent"
sys.path.insert(0, str(AGENT_DIR))

# Lightweight stubs so importing agent.py does not pull in optional runtime packages.
sys.modules.setdefault("anthropic", SimpleNamespace(Anthropic=lambda **_kwargs: None))
sys.modules.setdefault("apscheduler", SimpleNamespace())
sys.modules.setdefault("apscheduler.schedulers", SimpleNamespace())
sys.modules.setdefault("apscheduler.schedulers.blocking", SimpleNamespace(BlockingScheduler=lambda: None))

spec = importlib.util.spec_from_file_location("minyad_agent_main", AGENT_DIR / "agent.py")
agent = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(agent)


# ---------------------------------------------------------------------------
# trim_state_for_llm
# ---------------------------------------------------------------------------

def test_trim_state_drops_phase_grid_fields() -> None:
    state = {
        "grid": {
            "grid_net_power_w": 50,
            "grid_delivered_w": 300,
            "grid_returned_w": 250,
            "grid_phase_delivered_l1_w": 100,
            "grid_phase_delivered_l2_w": 100,
            "grid_phase_delivered_l3_w": 100,
            "grid_voltage_l1_v": 231.0,
            "grid_status": "ok",
        },
        "battery": {
            "soc": 55,
            "bridge_last_seen": "2026-06-25T10:00:00Z",
            "bridge_last_seen_valid": True,
        },
        "timestamp": "2026-06-25T10:00:00Z",
    }
    result = agent.trim_state_for_llm(state)

    assert result["grid"] == {
        "grid_net_power_w": 50,
        "grid_delivered_w": 300,
        "grid_returned_w": 250,
        "grid_status": "ok",
    }
    # Verbose phase and voltage fields removed
    assert "grid_phase_delivered_l1_w" not in result["grid"]
    assert "grid_voltage_l1_v" not in result["grid"]

    # Bridge metadata stripped from battery
    assert result["battery"] == {"soc": 55}

    # Non-grid/battery keys are left unchanged
    assert result["timestamp"] == "2026-06-25T10:00:00Z"


def test_trim_state_leaves_missing_sections_intact() -> None:
    state: dict = {}
    result = agent.trim_state_for_llm(state)
    assert result == {}


# ---------------------------------------------------------------------------
# rule_based_decision
# ---------------------------------------------------------------------------

_SETTINGS = {"battery": {"soc_floor": 20, "soc_ceiling": 90}}


def test_rule_based_skips_when_at_floor_and_no_solar() -> None:
    state = {"battery": {"soc": 20}, "settings": _SETTINGS}
    forecast = {"points": [{"power_w": 0}, {"power_w": 50}, {"power_w": 30}]}
    decision = agent.rule_based_decision(state, forecast, operator_messages=[])
    assert decision is not None
    assert decision["action_taken"] == "hold"
    assert decision["confidence"] == "high"


def test_rule_based_passes_through_when_solar_expected() -> None:
    state = {"battery": {"soc": 20}, "settings": _SETTINGS}
    forecast = {"points": [{"power_w": 500}, {"power_w": 1200}]}
    decision = agent.rule_based_decision(state, forecast, operator_messages=[])
    assert decision is None


def test_rule_based_passes_through_with_operator_messages() -> None:
    state = {"battery": {"soc": 20}, "settings": _SETTINGS}
    forecast = {"points": [{"power_w": 0}]}
    decision = agent.rule_based_decision(state, forecast, operator_messages=[{"id": 1}])
    assert decision is None


def test_rule_based_passes_through_when_soc_above_floor() -> None:
    state = {"battery": {"soc": 40}, "settings": _SETTINGS}
    forecast = {"points": [{"power_w": 0}]}
    decision = agent.rule_based_decision(state, forecast, operator_messages=[])
    assert decision is None


# ---------------------------------------------------------------------------
# select_model
# ---------------------------------------------------------------------------

def _mock_config(model: str, haiku: str) -> None:
    """Temporarily patch config values for select_model tests."""
    agent.config.MODEL = model
    agent.config.HAIKU_MODEL = haiku


def test_select_model_uses_haiku_for_routine_balanced_state() -> None:
    _mock_config("sonnet", "haiku")
    state = {
        "battery": {"soc": 55},
        "settings": _SETTINGS,
        "grid": {"grid_net_power_w": 80},
    }
    assert agent.select_model(state, operator_messages=[]) == "haiku"


def test_select_model_uses_sonnet_near_soc_floor() -> None:
    _mock_config("sonnet", "haiku")
    state = {
        "battery": {"soc": 23},  # within 5% of floor (20)
        "settings": _SETTINGS,
        "grid": {"grid_net_power_w": 50},
    }
    assert agent.select_model(state, operator_messages=[]) == "sonnet"


def test_select_model_uses_sonnet_near_soc_ceiling() -> None:
    _mock_config("sonnet", "haiku")
    state = {
        "battery": {"soc": 88},  # within 5% of ceiling (90)
        "settings": _SETTINGS,
        "grid": {"grid_net_power_w": 50},
    }
    assert agent.select_model(state, operator_messages=[]) == "sonnet"


def test_select_model_uses_sonnet_for_large_grid_imbalance() -> None:
    _mock_config("sonnet", "haiku")
    state = {
        "battery": {"soc": 55},
        "settings": _SETTINGS,
        "grid": {"grid_net_power_w": 600},
    }
    assert agent.select_model(state, operator_messages=[]) == "sonnet"


def test_select_model_uses_sonnet_when_operator_messages_present() -> None:
    _mock_config("sonnet", "haiku")
    state = {
        "battery": {"soc": 55},
        "settings": _SETTINGS,
        "grid": {"grid_net_power_w": 50},
    }
    assert agent.select_model(state, operator_messages=[{"id": 1}]) == "sonnet"


# ---------------------------------------------------------------------------
# log_api_usage / accumulate_usage
# ---------------------------------------------------------------------------

def test_log_api_usage_returns_all_four_fields() -> None:
    class FakeUsage:
        cache_read_input_tokens = 500
        cache_creation_input_tokens = 1200
        input_tokens = 300
        output_tokens = 120

    class FakeResponse:
        usage = FakeUsage()

    result = agent.log_api_usage(FakeResponse())
    assert result == {
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 1200,
        "input_tokens": 300,
        "output_tokens": 120,
    }


def test_accumulate_usage_sums_across_rounds() -> None:
    totals: dict = {}
    agent.accumulate_usage(totals, {"input_tokens": 300, "output_tokens": 50, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0})
    agent.accumulate_usage(totals, {"input_tokens": 200, "output_tokens": 40, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0})
    assert totals == {
        "input_tokens": 500,
        "output_tokens": 90,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 0,
    }


def test_accumulate_usage_handles_none_values() -> None:
    totals: dict = {}
    agent.accumulate_usage(totals, {"input_tokens": None, "output_tokens": None, "cache_read_input_tokens": None, "cache_creation_input_tokens": None})
    assert totals["input_tokens"] == 0
