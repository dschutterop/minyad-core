"""Tests for api.routers.agent: the operational-logs schema-tolerance behavior and the
message-thread lookup.

Most of this router is a thin, repetitive DB pass-through (single-row insert/select/404
handlers already exercised the same way dozens of times elsewhere in this codebase — see
api/routers/battery.py's override endpoints), so it isn't the focus here. What's actually
distinctive and worth locking down is agent_operational_logs' per-table existence-checking:
several of the tables it reads (day_plans, slot_plans, strategy_shadow_log, agent_messages)
were added after agent_decisions/setpoint_log, so a Minyad Core instance can legitimately be
running against a DB that hasn't been migrated to have all of them yet. This is the behavior
that keeps that endpoint from 500ing on an older schema, plus the message-thread aggregation
in get_agent_message (root_id = thread_id or id).
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import pytest
from fastapi import HTTPException

from api.routers import agent as agent_router


def run(coro):
    return asyncio.run(coro)


class _Row(dict):
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


class _Result:
    def __init__(self, rows=None, scalar=None, scalar_values=None):
        self._rows = [_Row(r) if isinstance(r, dict) else r for r in (rows or [])]
        self._scalar = scalar
        self._scalar_values = scalar_values

    def scalar_one(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def one(self):
        return self._rows[0]

    def scalars(self):
        return _Scalars(self._scalar_values if self._scalar_values is not None else self._rows)

    def __iter__(self):
        return iter(self._rows)


class FakeAgentSession:
    """Dispatches table-existence/column-introspection calls by bound param, and row
    queries by a `from <table>` substring match — the SQL text for `to_regclass(...)` and
    `information_schema.columns` checks is identical across tables; only the params differ."""

    def __init__(self, existing_tables=(), table_rows=None, settings_rows=(), columns=None):
        self.existing_tables = set(existing_tables)
        self.table_rows = table_rows or {}
        self.settings_rows = list(settings_rows)
        self.columns = columns or {}
        self.executed = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.executed.append((sql, params))
        if "to_regclass" in sql:
            return _Result(scalar=params.get("table_name") in self.existing_tables)
        if "information_schema.columns" in sql:
            table = "setpoint_log" if "'setpoint_log'" in sql else params.get("table_name")
            return _Result(scalar_values=list(self.columns.get(table, [])))
        if "from settings" in sql:
            return _Result(rows=self.settings_rows)
        for table, rows in self.table_rows.items():
            if f"from {table}" in sql:
                return _Result(rows=rows)
        return _Result(rows=[])

    async def commit(self):
        self.commits += 1


# --------------------------------------------------------------------------- #
# agent_operational_logs — schema-tolerance (table existence) branching
# --------------------------------------------------------------------------- #
def test_agent_operational_logs_marks_all_optional_tables_unavailable_on_older_schema():
    session = FakeAgentSession(existing_tables=set())

    result = run(agent_router.agent_operational_logs(session))

    assert result["logs"] == {"settings": []}
    assert set(result["unavailable"]) == {
        "agent_decisions",
        "setpoint_log",
        "strategy_decisions",
        "day_plans",
        "slot_plans",
        "strategy_shadow_log",
        "agent_messages",
        "telemetry_log",
        "battery_override",
    }


def test_agent_operational_logs_includes_present_tables_and_serializes_rows():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session = FakeAgentSession(
        existing_tables={"agent_decisions", "battery_override"},
        table_rows={
            "agent_decisions": [
                {
                    "id": 1,
                    "created_at": now,
                    "action_taken": "charge",
                    "setpoint_w": 500,
                    "reasoning": "surplus solar",
                    "confidence": "high",
                    "input_snapshot": "{}",
                    "dry_run": False,
                    "model": "test",
                }
            ],
            "battery_override": [{"id": 1, "mode": "none"}],
        },
    )

    result = run(agent_router.agent_operational_logs(session))

    assert "agent_decisions" not in result["unavailable"]
    assert "battery_override" not in result["unavailable"]
    assert result["logs"]["agent_decisions"][0]["created_at"] == now.isoformat()
    assert {"day_plans", "slot_plans", "agent_messages", "setpoint_log"} <= set(result["unavailable"])


def test_agent_operational_logs_rejects_since_after_until():
    session = FakeAgentSession()
    until = datetime.now(UTC)
    since = until + timedelta(hours=1)

    with pytest.raises(HTTPException) as exc:
        run(
            agent_router.agent_operational_logs(
                session,
                since=since.isoformat(),
                until=until.isoformat(),
            )
        )
    assert exc.value.status_code == 400


def test_agent_operational_logs_uses_present_slot_plans_strategy_version_column():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session = FakeAgentSession(
        existing_tables={"slot_plans"},
        table_rows={"slot_plans": [{"id": 1, "generated_at": now, "valid_from": now, "slot_seconds": 900, "solver_status": "OPTIMAL", "strategy_version": "v3", "payload": "{}", "created_at": now}]},
        columns={"slot_plans": ["id", "strategy_version"]},
    )

    result = run(agent_router.agent_operational_logs(session))

    assert result["logs"]["slot_plans"][0]["strategy_version"] == "v3"


def test_agent_operational_logs_falls_back_to_null_strategy_version_when_column_missing():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session = FakeAgentSession(
        existing_tables={"slot_plans"},
        table_rows={"slot_plans": [{"id": 1, "generated_at": now, "valid_from": now, "slot_seconds": 900, "solver_status": "OPTIMAL", "strategy_version": None, "payload": "{}", "created_at": now}]},
        columns={"slot_plans": ["id"]},  # no strategy_version column on this (older) schema
    )

    result = run(agent_router.agent_operational_logs(session))

    select_sql = next(sql for sql, params in session.executed if "from slot_plans" in sql)
    assert "null as strategy_version" in select_sql
    assert result["logs"]["slot_plans"][0]["strategy_version"] is None


def test_agent_operational_logs_serializes_setpoint_log_when_present():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session = FakeAgentSession(
        existing_tables={"setpoint_log"},
        table_rows={"setpoint_log": [{"id": 1, "timestamp": now, "setpoint_w": 500, "discharge_allowed": False, "source": "strategy_v3"}]},
        columns={"setpoint_log": ["id", "timestamp", "setpoint_w", "discharge_allowed", "source"]},
    )

    result = run(agent_router.agent_operational_logs(session))

    assert "setpoint_log" not in result["unavailable"]
    assert result["logs"]["setpoint_log"][0]["action"] == "charge"


def test_agent_operational_logs_includes_optional_agent_message_ack_columns_when_present():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    session = FakeAgentSession(
        existing_tables={"agent_messages"},
        table_rows={
            "agent_messages": [
                {
                    "id": 1, "created_at": now, "sender": "agent", "category": "info", "subject": "s", "body": "b",
                    "related_decision_id": None, "read_at": None, "thread_id": None, "severity": "normal",
                    "archived_at": now,
                }
            ]
        },
        columns={"agent_messages": ["archived_at"]},  # older schema without operator_ack_at/agent_ack_at
    )

    result = run(agent_router.agent_operational_logs(session))

    select_sql = next(sql for sql, params in session.executed if "from agent_messages" in sql)
    assert "archived_at" in select_sql
    assert "operator_ack_at" not in select_sql
    assert result["logs"]["agent_messages"][0]["archived_at"] == now.isoformat()


# --------------------------------------------------------------------------- #
# get_agent_message — thread aggregation
# --------------------------------------------------------------------------- #
def test_get_agent_message_404s_when_missing():
    session = FakeAgentSession()

    with pytest.raises(HTTPException) as exc:
        run(agent_router.get_agent_message(999, session))
    assert exc.value.status_code == 404


def test_get_agent_message_uses_own_id_as_thread_root_when_not_a_reply():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    root_message = {
        "id": 5, "created_at": now, "sender": "agent", "category": "info", "subject": "s",
        "body": "b", "related_decision_id": None, "read_at": None, "thread_id": None,
        "severity": "normal", "archived_at": None, "operator_ack_at": None, "agent_ack_at": None,
    }
    session = FakeAgentSession(table_rows={"agent_messages": [root_message]})

    result = run(agent_router.get_agent_message(5, session))

    assert result["message"]["id"] == 5
    assert [m["id"] for m in result["thread"]] == [5]


def test_get_agent_message_resolves_thread_via_root_thread_id():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    reply = {
        "id": 7, "created_at": now, "sender": "operator", "category": "reply", "subject": "s",
        "body": "b", "related_decision_id": None, "read_at": None, "thread_id": 5,
        "severity": "normal", "archived_at": None, "operator_ack_at": None, "agent_ack_at": None,
    }
    root = {
        "id": 5, "created_at": now, "sender": "agent", "category": "info", "subject": "s",
        "body": "b", "related_decision_id": None, "read_at": None, "thread_id": None,
        "severity": "normal", "archived_at": None, "operator_ack_at": None, "agent_ack_at": None,
    }
    # get_agent_message issues two queries against agent_messages: the direct-id lookup
    # (returns `reply` via .first()) and the thread lookup (returns both rows via .all()).
    session = FakeAgentSession()
    original_execute = session.execute

    async def execute(statement, params=None):
        sql = str(statement)
        if "from agent_messages" in sql and "where id = :id" in sql:
            return _Result(rows=[reply])
        if "from agent_messages" in sql and "root_id" in sql:
            return _Result(rows=[root, reply])
        return await original_execute(statement, params)

    session.execute = execute

    result = run(agent_router.get_agent_message(7, session))

    assert result["message"]["id"] == 7
    assert [m["id"] for m in result["thread"]] == [5, 7]
