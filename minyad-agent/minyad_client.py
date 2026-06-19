"""Thin HTTP client for the Minyad API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class MinyadClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        retries: int = 3,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep

    def get_state(self) -> dict[str, Any]:
        return self._get("/api/state")

    def get_forecast(self, hours_ahead: int = 12) -> dict[str, Any]:
        return self._get("/api/forecast", params={"hours_ahead": hours_ahead})

    def set_battery(self, setpoint_w: int, duration_minutes: int = 15) -> dict[str, Any]:
        return self._post(
            "/api/control/battery",
            json={"setpoint_w": setpoint_w, "duration_minutes": duration_minutes},
        )

    def log_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/agent/decisions", json=payload)

    def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/messages", json=payload)

    def get_unread_operator_messages(self) -> list[dict[str, Any]]:
        return self._get("/api/messages", params={"unread": "true", "sender": "operator"})  # type: ignore[return-value]

    def mark_message_read(self, message_id: int) -> dict[str, Any]:
        return self._patch(f"/api/messages/{message_id}/read")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        attempts = max(1, self.retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                    response = client.request(method, path, **kwargs)
                    response.raise_for_status()
                    return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                last_error = exc
                if attempt == attempts:
                    break
                delay = self.backoff_seconds * attempt
                LOGGER.warning(
                    "Minyad API request failed method=%s path=%s attempt=%s/%s retry_in=%.1fs error=%s",
                    method,
                    path,
                    attempt,
                    attempts,
                    delay,
                    exc,
                )
                self.sleep(delay)
        assert last_error is not None
        raise last_error

    def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", path, **kwargs)

    def _patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("PATCH", path, **kwargs)
