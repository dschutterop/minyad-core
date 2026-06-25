"""Minyad operator agent entrypoint."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from anthropic import Anthropic
from apscheduler.schedulers.blocking import BlockingScheduler

import config
from minyad_client import MinyadClient
from prompts import SYSTEM_PROMPT
from tools import TOOLS, ToolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOGGER = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 4
SYSTEM_PROMPT_CACHE_TTL = "1h"


def claude_skip_reason(settings: dict[str, Any], estimated_tokens: int) -> str | None:
    if not settings.get("enabled", False):
        return "waiting_for_claude"
    if settings.get("token_guard_enabled", True):
        remaining = settings.get("tokens_remaining")
        if remaining is not None and int(remaining) < int(settings.get("min_tokens_remaining", 5000)):
            return "token_guard_active"
        estimated_remaining = settings.get("estimated_tokens_remaining")
        if estimated_remaining is not None and int(estimated_remaining) < int(settings.get("min_tokens_remaining", 5000)):
            return "token_guard_active"
        if int(settings.get("min_tokens_remaining", 0)) > 0 and estimated_tokens < 0:
            return "token_guard_active"
    return None


def log_api_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    usage_payload = {
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    LOGGER.info("agent_api_usage %s", json.dumps(usage_payload, sort_keys=True))
    return usage_payload


def accumulate_usage(totals: dict[str, Any], usage: dict[str, Any]) -> None:
    for key in ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens", "output_tokens"):
        current = totals.get(key) or 0
        delta = usage.get(key) or 0
        totals[key] = current + delta


_GRID_FIELDS_FOR_LLM = {
    "grid_net_power_w",
    "grid_delivered_w",
    "grid_returned_w",
    "grid_status",
    "grid_timestamp",
}
_BATTERY_FIELDS_EXCLUDED = {"bridge_last_seen", "bridge_last_seen_valid", "bridge_last_seen_error"}


def trim_state_for_llm(state: dict[str, Any]) -> dict[str, Any]:
    """Strip verbose telemetry fields the agent doesn't need for battery control decisions.

    Keeps the decision-critical fields (SoC, grid net power, solar, state) while removing
    per-phase voltage/current readings that add tokens without adding decision value.
    """
    trimmed: dict[str, Any] = {}
    for key, value in state.items():
        if key == "grid" and isinstance(value, dict):
            trimmed["grid"] = {k: v for k, v in value.items() if k in _GRID_FIELDS_FOR_LLM}
        elif key == "battery" and isinstance(value, dict):
            trimmed["battery"] = {k: v for k, v in value.items() if k not in _BATTERY_FIELDS_EXCLUDED}
        else:
            trimmed[key] = value
    return trimmed


def serialize_content_blocks(blocks: list[object]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            serialized.append({"type": "text", "text": getattr(block, "text", "")})
        elif block_type == "tool_use":
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return serialized


def rule_based_decision(
    state: dict[str, Any],
    forecast: dict[str, Any],
    operator_messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a hold decision without an LLM call when the situation is clearly deterministic.

    Returns a decision dict that can be passed directly to client.log_decision(), or None to
    proceed with the full LLM call.  Rules are conservative: any ambiguity falls through to
    the LLM.
    """
    if operator_messages:
        return None  # unread messages always need LLM interpretation

    battery = state.get("battery", {})
    soc = battery.get("soc")
    if soc is None:
        return None  # missing telemetry → trust LLM

    settings = state.get("settings", {}).get("battery", {})
    soc_floor = int(settings.get("soc_floor", 20))

    forecast_points = forecast.get("points", [])
    near_term_solar_w = max((p.get("power_w", 0) or 0 for p in forecast_points[:3]), default=0)

    # Battery at SoC floor and no solar expected in the next 3 hours: the charge controller
    # already blocks discharge, so there is nothing for the agent to adjust.
    if int(soc) <= soc_floor and near_term_solar_w < 100:
        return {
            "action_taken": "hold",
            "setpoint_w": None,
            "reasoning": (
                f"Battery at SoC floor ({soc}% ≤ {soc_floor}%), "
                f"no solar in 3h forecast (max {near_term_solar_w}W); rule-based hold."
            ),
            "confidence": "high",
        }

    return None  # all other states: use the LLM


def select_model(
    state: dict[str, Any],
    operator_messages: list[dict[str, Any]],
) -> str:
    """Choose between the full Sonnet model and the lighter Haiku model.

    Routes to Haiku only for routine cycles where the state is unambiguous and there
    is nothing requiring nuanced reasoning.  Any hint of complexity falls back to Sonnet.
    """
    if operator_messages:
        return config.MODEL  # unread messages → Sonnet

    battery = state.get("battery", {})
    soc = battery.get("soc")
    if soc is None:
        return config.MODEL  # missing data → Sonnet

    settings = state.get("settings", {}).get("battery", {})
    soc_floor = int(settings.get("soc_floor", 20))
    soc_ceiling = int(settings.get("soc_ceiling", 90))

    # Near SoC limits needs careful reasoning about forecast and ramp behaviour
    if int(soc) <= soc_floor + 5 or int(soc) >= soc_ceiling - 5:
        return config.MODEL

    grid = state.get("grid", {})
    grid_net_power_w = grid.get("grid_net_power_w")
    if grid_net_power_w is not None and abs(int(grid_net_power_w)) > 400:
        return config.MODEL  # significant imbalance requires reasoning → Sonnet

    return config.HAIKU_MODEL  # routine, balanced state → Haiku is sufficient


def run_cycle() -> None:
    client = MinyadClient(
        config.MINYAD_API_URL,
        retries=config.MINYAD_API_RETRIES,
        backoff_seconds=config.MINYAD_API_RETRY_BACKOFF_SECONDS,
    )
    try:
        claude_settings = client.get_claude_agent_settings()
        skip_reason = claude_skip_reason(claude_settings, config.MAX_TOKENS)
        if skip_reason is not None:
            LOGGER.info("skipping Claude agent cycle reason=%s settings=%s", skip_reason, {k: v for k, v in claude_settings.items() if "key" not in k.lower()})
            client.log_decision({
                "action_taken": "hold",
                "setpoint_w": None,
                "reasoning": f"Claude call skipped: {skip_reason}",
                "confidence": "low",
                "input_snapshot": {"claude_agent": claude_settings, "skip_reason": skip_reason},
                "dry_run": config.DRY_RUN,
                "model": config.MODEL,
            })
            return
        if not config.ANTHROPIC_API_KEY:
            LOGGER.warning("skipping Claude agent cycle because ANTHROPIC_API_KEY is not configured")
            client.log_decision({
                "action_taken": "hold",
                "setpoint_w": None,
                "reasoning": "Claude call skipped: missing Anthropic API key",
                "confidence": "low",
                "input_snapshot": {"claude_agent": claude_settings, "skip_reason": "missing_api_key"},
                "dry_run": config.DRY_RUN,
                "model": config.MODEL,
            })
            return
        state = client.get_state()
        battery_settings = client.get_battery_settings()
        state.setdefault("settings", {})["battery"] = battery_settings
        forecast = client.get_forecast(hours_ahead=12)
        operator_messages = client.get_unread_operator_messages()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        LOGGER.warning("skipping agent cycle because Minyad API is unavailable: %s", exc)
        return

    # --- Rule-based pre-filter: skip LLM for fully deterministic states ---
    rule_action = rule_based_decision(state, forecast, operator_messages)
    if rule_action is not None:
        LOGGER.info("rule_based_decision action=%s reasoning=%s", rule_action["action_taken"], rule_action["reasoning"])
        client.log_decision({
            **rule_action,
            "input_snapshot": {"state": state, "forecast": forecast, "operator_messages": operator_messages, "rule_based": True},
            "dry_run": config.DRY_RUN,
            "model": "rule_engine",
        })
        return

    # --- Model routing: Haiku for routine states, Sonnet for complex ones ---
    model = select_model(state, operator_messages)
    LOGGER.info("model_selected model=%s", model)

    # --- Context trimming: remove verbose fields not needed for battery decisions ---
    trimmed_state = trim_state_for_llm(state)

    anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            f"Current state:\n{json.dumps(trimmed_state, ensure_ascii=False)}\n\n"
            f"Forecast:\n{json.dumps(forecast, ensure_ascii=False)}\n\n"
            f"Unread operator messages:\n{json.dumps(operator_messages, ensure_ascii=False)}"
        ),
    }]
    executor = ToolExecutor(client, state, forecast, config.DRY_RUN, model, operator_messages)
    saw_log = False
    cumulative_usage: dict[str, Any] = {}

    for _round in range(MAX_TOOL_ROUNDS):
        response = anthropic.messages.create(
            model=model,
            max_tokens=config.MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": SYSTEM_PROMPT_CACHE_TTL},
            }],
            tools=TOOLS,
            messages=messages,
        )
        usage = log_api_usage(response)
        accumulate_usage(cumulative_usage, usage)
        tool_results: list[dict[str, Any]] = []
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) != "tool_use":
                continue
            result = executor.execute(block.name, dict(block.input))
            LOGGER.info("tool %s result=%s", block.name, result)
            saw_log = saw_log or block.name == "log_decision"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
        if not tool_results:
            break
        messages.append({"role": "assistant", "content": serialize_content_blocks(list(response.content))})
        messages.append({"role": "user", "content": tool_results})
        if saw_log:
            break

    LOGGER.info("agent_cycle_token_totals %s", json.dumps(cumulative_usage, sort_keys=True))

    if not saw_log:
        action = executor.last_action or {"action_taken": "hold", "setpoint_w": None, "reasoning": "Model did not call log_decision; fallback audit log."}
        client.log_decision({
            **action,
            "confidence": "low",
            "input_snapshot": {
                "state": state,
                "forecast": forecast,
                "operator_messages": operator_messages,
                "token_usage": cumulative_usage,
            },
            "dry_run": config.DRY_RUN,
            "model": model,
        })
    for message in operator_messages:
        message_id = message.get("id")
        if isinstance(message_id, int):
            client.mark_message_read(message_id)


def main() -> None:
    if not config.ANTHROPIC_API_KEY:
        LOGGER.warning("ANTHROPIC_API_KEY is not configured; container will keep running and skip Claude calls when reached")
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, "interval", minutes=config.CYCLE_MINUTES, next_run_time=None)
    LOGGER.info("starting Minyad agent dry_run=%s cycle_minutes=%s", config.DRY_RUN, config.CYCLE_MINUTES)
    run_cycle()
    scheduler.start()


if __name__ == "__main__":
    main()
