"""Agent decisions/logs and operator/agent message-mailbox routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from api.payload_helpers import (
        _parse_log_datetime,
        _serialize_log_row,
        serialize_agent_decision,
        serialize_agent_message,
        serialize_control_decision,
        setpoint_log_select_list,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from payload_helpers import (
        _parse_log_datetime,
        _serialize_log_row,
        serialize_agent_decision,
        serialize_agent_message,
        serialize_control_decision,
        setpoint_log_select_list,
    )
try:
    from api.state import (
        MESSAGE_NOT_FOUND_DETAIL,
        MUTATION_AUTH,
        SessionDep,
        require_api_key,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from state import (
        MESSAGE_NOT_FOUND_DETAIL,
        MUTATION_AUTH,
        SessionDep,
        require_api_key,
    )
try:
    from api.routers.settings import setpoint_log_columns
except ModuleNotFoundError:  # pragma: no cover - exercised by the API Docker image layout
    from routers.settings import setpoint_log_columns

router = APIRouter()


class AgentDecisionRequest(BaseModel):
    action_taken: Literal["charge", "discharge", "hold"]
    setpoint_w: int | None = None
    reasoning: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    input_snapshot: dict[str, Any]
    dry_run: bool = True
    model: str = "claude-sonnet-4-6"


class AgentMessageCreate(BaseModel):
    sender: Literal["agent", "operator"]
    category: Literal["anomaly", "suggestion", "info", "reply"]
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1)
    related_decision_id: int | None = None
    thread_id: int | None = None
    severity: Literal["low", "normal", "high"] = "normal"


@router.post("/api/agent/decisions", status_code=201, dependencies=MUTATION_AUTH)
async def create_agent_decision(request: AgentDecisionRequest, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_decisions (action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model)
        values (:action_taken, :setpoint_w, :reasoning, :confidence, cast(:input_snapshot as jsonb), :dry_run, :model)
        returning id, created_at
    """), {
        "action_taken": request.action_taken,
        "setpoint_w": request.setpoint_w,
        "reasoning": request.reasoning,
        "confidence": request.confidence,
        "input_snapshot": json.dumps(request.input_snapshot),
        "dry_run": request.dry_run,
        "model": request.model,
    })).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=UTC).isoformat()}


@router.get("/api/agent/decisions")
async def list_agent_decisions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    rows = (await session.execute(text("""
        select id, created_at, action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model
        from agent_decisions
        order by created_at desc
        limit :limit
    """), {"limit": limit})).mappings().all()
    return [serialize_agent_decision(row) for row in rows]


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    return bool((await session.execute(text("select to_regclass(:table_name) is not null"), {"table_name": table_name})).scalar_one())


async def _table_columns(session: AsyncSession, table_name: str) -> set[str]:
    rows = (await session.execute(
        text("""
            select column_name
            from information_schema.columns
            where table_name = :table_name
        """),
        {"table_name": table_name},
    )).scalars().all()
    return set(rows)


async def _fetch_log_rows(session: AsyncSession, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (await session.execute(text(query), params)).mappings().all()
    return [_serialize_log_row(row) for row in rows]


async def _collect_log(
    session: AsyncSession,
    logs: dict[str, Any],
    unavailable: list[str],
    table: str,
    query: str,
    params: dict[str, Any],
) -> None:
    if await _table_exists(session, table):
        logs[table] = await _fetch_log_rows(session, query, params)
    else:
        unavailable.append(table)


@router.get("/api/agent/logs", dependencies=[Depends(require_api_key)], responses={400: {"description": "Bad request"}})
async def agent_operational_logs(
    session: SessionDep,
    hours_lookback: Annotated[int, Query(ge=1, le=168)] = 24,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    since: Annotated[str | None, Query()] = None,
    until: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    until_dt = _parse_log_datetime(until) or datetime.now(UTC)
    since_dt = _parse_log_datetime(since) or (until_dt - timedelta(hours=hours_lookback))
    if since_dt > until_dt:
        raise HTTPException(status_code=400, detail="since must be before until")
    params = {"since": since_dt, "until": until_dt, "limit": limit}
    logs: dict[str, Any] = {}
    unavailable: list[str] = []

    await _collect_log(session, logs, unavailable, "agent_decisions", """
        select id, created_at, action_taken, setpoint_w, reasoning, confidence, input_snapshot, dry_run, model
        from agent_decisions
        where created_at >= :since and created_at <= :until
        order by created_at desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "setpoint_log"):
        columns = await setpoint_log_columns(session)
        select_list = setpoint_log_select_list(columns)
        rows = (await session.execute(text(f"""
            select {select_list}
            from setpoint_log
            where timestamp >= :since and timestamp <= :until
            order by timestamp desc, id desc
            limit :limit
        """), params)).mappings().all()
        logs["setpoint_log"] = [serialize_control_decision(row) for row in rows]
    else:
        unavailable.append("setpoint_log")

    await _collect_log(session, logs, unavailable, "strategy_decisions", """
        select id, timestamp, mode, soc_floor, soc_ceiling, forecast_ghi, trigger_reason, applied_at
        from strategy_decisions
        where timestamp >= :since and timestamp <= :until
        order by timestamp desc, id desc
        limit :limit
    """, params)

    await _collect_log(session, logs, unavailable, "day_plans", """
        select id, plan_date, solar_mode, forecast_ghi_kwh_m2, effective_soc_floor,
               effective_soc_ceiling, grid_charge_windows, price_discharge_windows,
               planned_soc_at_sunset, valid_until, reason, created_at
        from day_plans
        where created_at <= :until and valid_until >= :since
        order by created_at desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "slot_plans"):
        columns = await _table_columns(session, "slot_plans")
        strategy_version_select = "strategy_version" if "strategy_version" in columns else "null as strategy_version"
        logs["slot_plans"] = await _fetch_log_rows(session, f"""
            select id, generated_at, valid_from, slot_seconds, solver_status, {strategy_version_select}, payload, created_at
            from slot_plans
            where generated_at >= :since and generated_at <= :until
            order by generated_at desc, id desc
            limit :limit
        """, params)
    else:
        unavailable.append("slot_plans")

    await _collect_log(session, logs, unavailable, "strategy_shadow_log", """
        select id, ts, v2_setpoint_w, v3_setpoint_w, soc, net_grid_w, v3_reason, created_at
        from strategy_shadow_log
        where ts >= :since and ts <= :until
        order by ts desc, id desc
        limit :limit
    """, params)

    if await _table_exists(session, "agent_messages"):
        columns = await _table_columns(session, "agent_messages")
        optional_columns = [
            name for name in ("archived_at", "operator_ack_at", "agent_ack_at")
            if name in columns
        ]
        select_columns = [
            "id", "created_at", "sender", "category", "subject", "body",
            "related_decision_id", "read_at", "thread_id", "severity", *optional_columns,
        ]
        logs["agent_messages"] = await _fetch_log_rows(session, f"""
            select {", ".join(select_columns)}
            from agent_messages
            where created_at >= :since and created_at <= :until
            order by created_at desc, id desc
            limit :limit
        """, params)
    else:
        unavailable.append("agent_messages")

    await _collect_log(session, logs, unavailable, "telemetry_log", """
        select id, timestamp, topic, payload
        from telemetry_log
        where timestamp >= :since and timestamp <= :until
        order by timestamp desc, id desc
        limit :limit
    """, params)

    await _collect_log(session, logs, unavailable, "battery_override", """
        select *
        from battery_override
        order by id
        limit :limit
    """, params)

    settings_rows = (await session.execute(text("""
        select key, value, updated_at
        from settings
        where key like 'battery.%' or key like 'strategy.%' or key like 'strategy3.%'
        order by key
    """))).mappings().all()
    logs["settings"] = [_serialize_log_row(row) for row in settings_rows]

    return {
        "window": {
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "hours_lookback": hours_lookback,
            "limit_per_log": limit,
        },
        "logs": logs,
        "unavailable": unavailable,
    }


@router.get("/api/messages")
async def list_agent_messages(
    session: SessionDep,
    unread: bool | None = None,
    category: Literal["anomaly", "suggestion", "info", "reply"] | None = None,
    sender: Literal["agent", "operator"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    archived: bool | None = False,
) -> list[dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if unread is True:
        clauses.append("read_at is null")
    elif unread is False:
        clauses.append("read_at is not null")
    if category is not None:
        clauses.append("category = :category")
        params["category"] = category
    if sender is not None:
        clauses.append("sender = :sender")
        params["sender"] = sender
    if archived is True:
        clauses.append("archived_at is not null")
    elif archived is False:
        clauses.append("archived_at is null")
    where = " where " + " and ".join(clauses) if clauses else ""
    rows = (await session.execute(text(f"""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        {where}
        order by created_at desc
        limit :limit
    """), params)).mappings().all()
    return [serialize_agent_message(row) for row in rows]


@router.get("/api/messages/unread-count")
async def agent_messages_unread_count(
    session: SessionDep,
    sender: Literal["agent", "operator"] | None = "agent",
) -> dict[str, int]:
    clause = "read_at is null and archived_at is null"
    params: dict[str, Any] = {}
    if sender is not None:
        clause += " and sender = :sender"
        params["sender"] = sender
    count = (await session.execute(text(f"select count(*) from agent_messages where {clause}"), params)).scalar_one()
    return {"unread_count": int(count)}


@router.get("/api/messages/{message_id}", responses={404: {"description": "Not found"}})
async def get_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :id
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    root_id = row["thread_id"] or row["id"]
    thread_rows = (await session.execute(text("""
        select id, created_at, sender, category, subject, body, related_decision_id, read_at, thread_id, severity, archived_at, operator_ack_at, agent_ack_at
        from agent_messages
        where id = :root_id or thread_id = :root_id
        order by created_at asc
    """), {"root_id": root_id})).mappings().all()
    return {"message": serialize_agent_message(row), "thread": [serialize_agent_message(thread_row) for thread_row in thread_rows]}


@router.post("/api/messages", status_code=201, dependencies=MUTATION_AUTH)
async def create_agent_message(request: AgentMessageCreate, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        insert into agent_messages (sender, category, subject, body, related_decision_id, thread_id, severity, operator_ack_at, agent_ack_at)
        values (:sender, :category, :subject, :body, :related_decision_id, :thread_id, :severity, case when :sender = 'operator' then now() else null end, case when :sender = 'agent' then now() else null end)
        returning id, created_at
    """), request.model_dump())).mappings().one()
    await session.commit()
    return {"status": "ok", "id": row["id"], "created_at": row["created_at"].replace(tzinfo=UTC).isoformat()}


@router.patch("/api/messages/{message_id}/read", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def mark_agent_message_read(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set read_at = coalesce(read_at, now()),
            agent_ack_at = case when sender = 'operator' then coalesce(agent_ack_at, now()) else agent_ack_at end
        where id = :id
        returning id, read_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"], "read_at": row["read_at"].replace(tzinfo=UTC).isoformat()}


@router.patch("/api/messages/{message_id}/archive", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def archive_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("""
        update agent_messages
        set archived_at = coalesce(archived_at, now())
        where id = :id
        returning id, archived_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"], "archived_at": row["archived_at"].replace(tzinfo=UTC).isoformat()}


@router.patch("/api/messages/{message_id}/ack", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def acknowledge_agent_message(message_id: int, session: SessionDep, actor: Literal["operator", "agent"] = "operator") -> dict[str, Any]:
    column = "operator_ack_at" if actor == "operator" else "agent_ack_at"
    row = (await session.execute(text(f"""
        update agent_messages
        set {column} = coalesce({column}, now())
        where id = :id
        returning id, operator_ack_at, agent_ack_at
    """), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", **serialize_agent_message(row)}


@router.delete("/api/messages/{message_id}", dependencies=MUTATION_AUTH, responses={404: {"description": "Not found"}})
async def delete_agent_message(message_id: int, session: SessionDep) -> dict[str, Any]:
    row = (await session.execute(text("delete from agent_messages where id = :id returning id"), {"id": message_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    await session.commit()
    return {"status": "ok", "id": row["id"]}
