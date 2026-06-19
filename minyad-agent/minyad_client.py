"""Thin HTTP client for the Minyad API."""

from __future__ import annotations

from typing import Any

import httpx


class MinyadClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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

    def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.post(path, **kwargs)
            response.raise_for_status()
            return response.json()

    def _patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.patch(path, **kwargs)
            response.raise_for_status()
            return response.json()
