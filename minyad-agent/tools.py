"""Anthropic tool definitions and local implementations."""

from __future__ import annotations

import logging
from typing import Any

from minyad_client import MinyadClient

LOGGER = logging.getLogger(__name__)
INVERTER_MAX_W = 5000
DEFAULT_MIN_SOC = 20
DEFAULT_MAX_SOC = 90

TOOLS: list[dict[str, Any]] = [
    {
        "name": "set_battery_setpoint",
        "description": "Stel het charge/discharge setpoint van de batterij in. Positief = charge (W), negatief = discharge (W), 0 = idle/passthrough. Wordt serverside geclipt aan veiligheidsgrenzen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "setpoint_w": {"type": "integer", "description": "Watt, positief=laden, negatief=ontladen, range -5000..5000"},
                "duration_minutes": {"type": "integer", "description": "Hoe lang dit setpoint geldig is voor de agent het opnieuw evalueert. Default 15."},
                "reasoning": {"type": "string", "description": "Korte, concrete uitleg waarom dit setpoint nu logisch is."},
            },
            "required": ["setpoint_w", "reasoning"],
        },
    },
    {
        "name": "hold_position",
        "description": "Expliciete 'doe niets' actie. Gebruik dit i.p.v. set_battery_setpoint met 0 als de bewuste keuze is om het huidige setpoint te laten staan.",
        "input_schema": {"type": "object", "properties": {"reasoning": {"type": "string", "description": "Waarom nu niet bijsturen."}}, "required": ["reasoning"]},
    },
    {
        "name": "get_extended_forecast",
        "description": "Haal forecast op voor een langere horizon dan standaard meegegeven.",
        "input_schema": {"type": "object", "properties": {"hours_ahead": {"type": "integer", "description": "Aantal uur vooruit, max 48"}}, "required": ["hours_ahead"]},
    },
    {
        "name": "get_operational_logs",
        "description": "Lees historische Minyad logs voor diagnosevragen: agent decisions, control setpoints, strategy decisions, slot plans, shadow log, telemetry, messages, overrides en settings. Gebruik dit wanneer de operator vraagt waarom iets eerder gebeurde.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours_lookback": {"type": "integer", "description": "Aantal uur terug vanaf nu of until_iso. Default 24, max 168."},
                "limit": {"type": "integer", "description": "Maximaal aantal rijen per logsoort. Default 50, max 100."},
                "since_iso": {"type": "string", "description": "Optioneel ISO-tijdstip vanaf wanneer logs nodig zijn."},
                "until_iso": {"type": "string", "description": "Optioneel ISO-tijdstip tot wanneer logs nodig zijn."},
            },
        },
    },
    {
        "name": "log_decision",
        "description": "ALTIJD als laatste tool call, ongeacht of er gestuurd is. Schrijft het volledige besluit naar agent_decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_taken": {"type": "string", "enum": ["charge", "discharge", "hold"]},
                "setpoint_w": {"type": "integer"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["action_taken", "reasoning", "confidence"],
        },
    },
    {
        "name": "send_message",
        "description": "Send a message to the operator via the local mailbox. Use this for sparse notifications or to reply to operator messages. When replying to an operator message, set category=reply and thread_id to the original message's thread_id or id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["anomaly", "suggestion", "info", "reply"]},
                "subject": {"type": "string", "description": "Short title, about 60 characters max"},
                "body": {"type": "string", "description": "Concrete explanation, with numbers where relevant"},
                "severity": {"type": "string", "enum": ["low", "normal", "high"]},
                "thread_id": {"type": "integer", "description": "Thread root id when replying to an operator message"},
            },
            "required": ["category", "subject", "body", "severity"],
        },
        # Cache the tool definitions as a stable prefix; they never change between cycles.
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    },
]


def clip_setpoint(setpoint_w: int, state: dict[str, Any]) -> tuple[int, list[str]]:
    warnings: list[str] = []
    clipped = max(-INVERTER_MAX_W, min(INVERTER_MAX_W, int(setpoint_w)))
    if clipped != setpoint_w:
        warnings.append(f"setpoint clipped from {setpoint_w}W to {clipped}W by inverter limit")
    battery_settings = state.get("settings", {}).get("battery", {})
    min_soc = int(battery_settings.get("soc_floor", DEFAULT_MIN_SOC))
    max_soc = int(battery_settings.get("soc_ceiling", DEFAULT_MAX_SOC))
    soc = state.get("battery", {}).get("soc") or state.get("soc")
    try:
        soc_value = float(soc)
    except (TypeError, ValueError):
        soc_value = None
    if soc_value is not None and clipped < 0 and soc_value <= min_soc:
        warnings.append(f"discharge clipped to 0W because SoC {soc_value}% <= configured minimum {min_soc}%")
        clipped = 0
    if soc_value is not None and clipped > 0 and soc_value >= max_soc:
        warnings.append(f"charge clipped to 0W because SoC {soc_value}% >= configured maximum {max_soc}%")
        clipped = 0
    for warning in warnings:
        LOGGER.warning(warning)
    return clipped, warnings


class ToolExecutor:
    def __init__(
        self,
        client: MinyadClient,
        state: dict[str, Any],
        forecast: dict[str, Any],
        dry_run: bool,
        model: str,
        operator_messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.client = client
        self.state = state
        self.forecast = forecast
        self.operator_messages = operator_messages or []
        self.dry_run = dry_run
        self.model = model
        self.last_action: dict[str, Any] | None = None

    def execute(self, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        if name == "set_battery_setpoint":
            requested = int(tool_input["setpoint_w"])
            clipped, warnings = clip_setpoint(requested, self.state)
            duration = int(tool_input.get("duration_minutes") or 15)
            result = {"requested_setpoint_w": requested, "setpoint_w": clipped, "duration_minutes": duration, "dry_run": self.dry_run, "warnings": warnings}
            if not self.dry_run:
                result["api_result"] = self.client.set_battery(clipped, duration)
            self.last_action = {"action_taken": "charge" if clipped > 0 else "discharge" if clipped < 0 else "hold", "setpoint_w": clipped, "reasoning": tool_input["reasoning"]}
            return result
        if name == "hold_position":
            self.last_action = {"action_taken": "hold", "setpoint_w": None, "reasoning": tool_input["reasoning"]}
            return {"status": "held", "dry_run": self.dry_run}
        if name == "get_extended_forecast":
            hours = max(1, min(48, int(tool_input["hours_ahead"])))
            return self.client.get_forecast(hours)
        if name == "get_operational_logs":
            hours = max(1, min(168, int(tool_input.get("hours_lookback") or 24)))
            limit = max(1, min(100, int(tool_input.get("limit") or 50)))
            return self.client.get_operational_logs(
                hours_lookback=hours,
                limit=limit,
                since=tool_input.get("since_iso"),
                until=tool_input.get("until_iso"),
            )
        if name == "log_decision":
            actual_action = self.last_action or {}
            payload = {
                **tool_input,
                **{key: value for key, value in actual_action.items() if key in {"action_taken", "setpoint_w"}},
                "input_snapshot": {"state": self.state, "forecast": self.forecast, "operator_messages": self.operator_messages},
                "dry_run": self.dry_run,
                "model": self.model,
            }
            return self.client.log_decision(payload)
        if name == "send_message":
            payload = {**tool_input, "sender": "agent"}
            return self.client.send_message(payload)
        raise ValueError(f"Unknown tool: {name}")
