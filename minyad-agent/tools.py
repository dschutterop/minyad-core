"""Anthropic tool definitions and local implementations."""

from __future__ import annotations

import logging
from typing import Any

from minyad_client import MinyadClient

LOGGER = logging.getLogger(__name__)
INVERTER_MAX_W = 5000
MIN_SOC = 20
MAX_SOC_FOR_FORCED_CHARGE = 95

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
        "description": "Send a message to the operator via the local mailbox. Use this sparingly for anomalies, improvement suggestions, or relevant observations that do not belong in the standard decision log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["anomaly", "suggestion", "info"]},
                "subject": {"type": "string", "description": "Short title, about 60 characters max"},
                "body": {"type": "string", "description": "Concrete explanation, with numbers where relevant"},
                "severity": {"type": "string", "enum": ["low", "normal", "high"]},
            },
            "required": ["category", "subject", "body", "severity"],
        },
    },
]


def clip_setpoint(setpoint_w: int, state: dict[str, Any]) -> tuple[int, list[str]]:
    warnings: list[str] = []
    clipped = max(-INVERTER_MAX_W, min(INVERTER_MAX_W, int(setpoint_w)))
    if clipped != setpoint_w:
        warnings.append(f"setpoint clipped from {setpoint_w}W to {clipped}W by inverter limit")
    soc = state.get("battery", {}).get("soc") or state.get("soc")
    try:
        soc_value = float(soc)
    except (TypeError, ValueError):
        soc_value = None
    if soc_value is not None and clipped < 0 and soc_value <= MIN_SOC:
        warnings.append(f"discharge clipped to 0W because SoC {soc_value}% <= {MIN_SOC}%")
        clipped = 0
    if soc_value is not None and clipped > 0 and soc_value >= MAX_SOC_FOR_FORCED_CHARGE:
        warnings.append(f"charge clipped to 0W because SoC {soc_value}% >= {MAX_SOC_FOR_FORCED_CHARGE}%")
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
