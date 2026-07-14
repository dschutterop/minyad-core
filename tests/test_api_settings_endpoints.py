"""Endpoint-level tests for settings read/write handlers in api.main.

The handlers are invoked directly with a lightweight fake ``AsyncSession`` that
maps SQL fragments to canned results, exercising the DB-backed code paths
(defaults merging, upserts, commit gating, validation) without a real database.
"""

import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api import main as api_main
from api.routers import health as health_router


class FakeRow(dict):
    """Row that supports both attribute access (row.key) and dict() coercion."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeResult:
    def __init__(self, rows=None, scalar=None, scalar_values=None):
        self._rows = [FakeRow(r) if isinstance(r, dict) else r for r in (rows or [])]
        self._scalar = scalar
        self._scalar_values = scalar_values

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalars(self):
        values = self._scalar_values if self._scalar_values is not None else self._rows
        return _Scalars(values)


class FakeSession:
    """Fake AsyncSession dispatching by SQL substring match."""

    def __init__(self, responses):
        # responses: list of (substring, FakeResult) checked in order.
        self.responses = responses
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        for substr, result in self.responses:
            if substr in sql:
                return result
        return FakeResult()

    async def commit(self):
        self.commits += 1


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
def test_health_returns_ok():
    result = run(api_main.health())
    assert result["status"] == "ok"
    assert result["private_modules"] is api_main.PRIVATE_MODULES_AVAILABLE


# --------------------------------------------------------------------------- #
# system settings
# --------------------------------------------------------------------------- #
def test_get_system_settings_applies_defaults_when_empty():
    session = FakeSession([("from settings", FakeResult(rows=[]))])
    result = run(api_main.get_system_settings(session))
    assert result == {"debug_logging": False, "theme": "system", "language": "en"}


def test_get_system_settings_reads_stored_rows():
    rows = [
        {"key": "system.debug_logging", "value": "true"},
        {"key": "system.theme", "value": "dark"},
        {"key": "system.language", "value": "nl"},
    ]
    session = FakeSession([("from settings", FakeResult(rows=rows))])
    result = run(api_main.get_system_settings(session))
    assert result == {"debug_logging": True, "theme": "dark", "language": "nl"}


def test_update_system_settings_upserts_and_commits(monkeypatch):
    applied = {}
    monkeypatch.setattr(health_router, "_apply_log_level", lambda debug: applied.setdefault("debug", debug))
    api_main.SystemSettingsUpdate.model_rebuild(_types_namespace={"Literal": api_main.Literal})
    update = api_main.SystemSettingsUpdate(debug_logging=True, theme="light", language="en")

    stored_rows = [
        {"key": "system.debug_logging", "value": "true"},
        {"key": "system.theme", "value": "light"},
        {"key": "system.language", "value": "en"},
    ]
    session = FakeSession([("select key, value from settings", FakeResult(rows=stored_rows))])
    result = run(api_main.update_system_settings(update, session))

    assert applied["debug"] is True
    assert session.commits == 1
    # three upserts plus the final read-back select
    assert sum(1 for sql, _ in session.executed if "insert into settings" in sql) == 3
    assert result["theme"] == "light"


def test_update_system_settings_noop_when_all_none():
    api_main.SystemSettingsUpdate.model_rebuild(_types_namespace={"Literal": api_main.Literal})
    update = api_main.SystemSettingsUpdate()
    session = FakeSession([("select key, value from settings", FakeResult(rows=[]))])
    run(api_main.update_system_settings(update, session))
    assert session.commits == 0
    assert not any("insert into settings" in sql for sql, _ in session.executed)


# --------------------------------------------------------------------------- #
# claude agent settings
# --------------------------------------------------------------------------- #
def test_claude_agent_settings_defaults_when_empty():
    session = FakeSession([("claude_agent.%", FakeResult(rows=[]))])
    result = run(api_main.get_claude_agent_settings(session))
    assert result["enabled"] is False
    assert result["token_guard_enabled"] is True
    assert result["min_tokens_remaining"] == 5000
    assert result["status"] == "disabled"


def test_claude_agent_settings_reads_and_coerces_stored_values():
    rows = [
        {"key": "claude_agent.enabled", "value": "on"},
        {"key": "claude_agent.token_guard_enabled", "value": "false"},
        {"key": "claude_agent.min_tokens_remaining", "value": "-42"},
    ]
    session = FakeSession([("claude_agent.%", FakeResult(rows=rows))])
    result = run(api_main.claude_agent_settings(session))
    assert result["enabled"] is True
    assert result["token_guard_enabled"] is False
    assert result["min_tokens_remaining"] == 0  # clamped to >= 0
    assert result["status"] == "enabled"


def test_update_claude_agent_settings_writes_only_set_fields():
    api_main.ClaudeAgentSettingsUpdate.model_rebuild()
    update = api_main.ClaudeAgentSettingsUpdate(enabled=True)
    session = FakeSession([("claude_agent.%", FakeResult(rows=[{"key": "claude_agent.enabled", "value": "true"}]))])
    run(api_main.update_claude_agent_settings(update, session))
    inserts = [params for sql, params in session.executed if "insert into settings" in sql]
    assert inserts == [{"key": "claude_agent.enabled", "value": "true"}]
    assert session.commits == 1


def test_update_claude_agent_settings_noop_without_fields():
    update = api_main.ClaudeAgentSettingsUpdate()
    session = FakeSession([("claude_agent.%", FakeResult(rows=[]))])
    run(api_main.update_claude_agent_settings(update, session))
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# asset steering settings
# --------------------------------------------------------------------------- #
def test_asset_steering_settings_merges_defaults():
    session = FakeSession(
        [
            ("like 'strategy.%'", FakeResult(rows=[])),
            ("like 'strategy3.%'", FakeResult(rows=[])),
        ]
    )
    result = run(api_main.get_asset_steering_settings(session))
    assert result["ghi_solar_rich_threshold"] == 4.5
    assert result["ramp_floor_w"] == 200
    assert result["strategy3"]["traj_deadband_pct"] == 3.0


def test_update_asset_steering_settings_rejects_out_of_range():
    api_main.AssetSteeringSettingsUpdate.model_rebuild()
    update = api_main.AssetSteeringSettingsUpdate(ramp_ceiling_w=999999)
    session = FakeSession(
        [
            ("like 'strategy.%'", FakeResult(rows=[])),
            ("like 'strategy3.%'", FakeResult(rows=[])),
        ]
    )
    with pytest.raises(HTTPException) as exc:
        run(api_main.update_asset_steering_settings(update, session))
    assert exc.value.status_code == 422


def test_update_asset_steering_settings_persists_valid_values():
    api_main.AssetSteeringSettingsUpdate.model_rebuild()
    update = api_main.AssetSteeringSettingsUpdate(ramp_floor_w=300, daily_recalculate_local_time="21:15")
    session = FakeSession(
        [
            ("like 'strategy.%'", FakeResult(rows=[])),
            ("like 'strategy3.%'", FakeResult(rows=[])),
        ]
    )
    run(api_main.update_asset_steering_settings(update, session))
    inserts = [params for sql, params in session.executed if "insert into settings" in sql]
    assert {"key": "strategy.ramp_floor_w", "value": "300"} in inserts
    assert {"key": "strategy.daily_recalculate_local_time", "value": "21:15"} in inserts
    assert session.commits == 1


# --------------------------------------------------------------------------- #
# serialize_control_decision (pure)
# --------------------------------------------------------------------------- #
def test_serialize_control_decision_hold_when_zero_setpoint_no_discharge():
    row = {"setpoint_w": 0, "discharge_allowed": False, "source": "strategy_v3"}
    assert api_main.serialize_control_decision(row)["action"] == "hold"


def test_serialize_control_decision_discharge_when_zero_setpoint_discharge_allowed():
    row = {"setpoint_w": 0, "discharge_allowed": True, "source": "strategy_v3"}
    assert api_main.serialize_control_decision(row)["action"] == "discharge"


def test_serialize_control_decision_strategy_source_positive_is_charge():
    row = {"setpoint_w": 500, "discharge_allowed": False, "source": "strategy_v3"}
    assert api_main.serialize_control_decision(row)["action"] == "charge"


def test_serialize_control_decision_other_source_positive_is_discharge():
    row = {"setpoint_w": 500, "discharge_allowed": False, "source": "manual"}
    assert api_main.serialize_control_decision(row)["action"] == "discharge"


def test_serialize_control_decision_serializes_timestamp():
    from datetime import datetime

    row = {"setpoint_w": 0, "discharge_allowed": False, "source": "", "timestamp": datetime(2026, 6, 1, 8, 0, 0)}
    data = api_main.serialize_control_decision(row)
    assert data["timestamp"] == "2026-06-01T08:00:00+00:00"


# --------------------------------------------------------------------------- #
# setpoint_log_select_list (pure)
# --------------------------------------------------------------------------- #
def test_setpoint_log_select_list_uses_present_columns():
    columns = {"id", "timestamp", "setpoint_w", "source"}
    select = api_main.setpoint_log_select_list(columns)
    assert "setpoint_w" in select
    # missing columns become "null as <name>"
    assert "null as soc_floor" in select


def test_setpoint_log_select_list_uses_fallback_column_alias():
    columns = {"charge_rate_w"}
    select = api_main.setpoint_log_select_list(columns)
    assert "charge_rate_w as setpoint_w" in select


def test_setpoint_log_select_list_aliases_apparent_load_fallback():
    columns = {"home_load_at_time"}
    select = api_main.setpoint_log_select_list(columns)
    assert "home_load_at_time as apparent_load_at_time" in select
