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


def log_api_usage(response: Any) -> None:
    usage = getattr(response, "usage", None)
    usage_payload = {
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "input_tokens": getattr(usage, "input_tokens", None),
    }
    LOGGER.info("agent_api_usage %s", json.dumps(usage_payload, sort_keys=True))


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


def run_cycle() -> None:
    client = MinyadClient(
        config.MINYAD_API_URL,
        retries=config.MINYAD_API_RETRIES,
        backoff_seconds=config.MINYAD_API_RETRY_BACKOFF_SECONDS,
    )
    try:
        state = client.get_state()
        forecast = client.get_forecast(hours_ahead=12)
        operator_messages = client.get_unread_operator_messages()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        LOGGER.warning("skipping agent cycle because Minyad API is unavailable: %s", exc)
        return
    anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            f"Current state:\n{json.dumps(state, ensure_ascii=False)}\n\n"
            f"Forecast:\n{json.dumps(forecast, ensure_ascii=False)}\n\n"
            f"Unread operator messages:\n{json.dumps(operator_messages, ensure_ascii=False)}"
        ),
    }]
    executor = ToolExecutor(client, state, forecast, config.DRY_RUN, config.MODEL, operator_messages)
    saw_log = False

    for _round in range(MAX_TOOL_ROUNDS):
        response = anthropic.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": SYSTEM_PROMPT_CACHE_TTL},
            }],
            tools=TOOLS,
            messages=messages,
        )
        log_api_usage(response)
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

    if not saw_log:
        action = executor.last_action or {"action_taken": "hold", "setpoint_w": None, "reasoning": "Model did not call log_decision; fallback audit log."}
        client.log_decision({
            **action,
            "confidence": "low",
            "input_snapshot": {"state": state, "forecast": forecast, "operator_messages": operator_messages},
            "dry_run": config.DRY_RUN,
            "model": config.MODEL,
        })
    for message in operator_messages:
        message_id = message.get("id")
        if isinstance(message_id, int):
            client.mark_message_read(message_id)


def main() -> None:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, "interval", minutes=config.CYCLE_MINUTES, next_run_time=None)
    LOGGER.info("starting Minyad agent dry_run=%s cycle_minutes=%s", config.DRY_RUN, config.CYCLE_MINUTES)
    run_cycle()
    scheduler.start()


if __name__ == "__main__":
    main()
