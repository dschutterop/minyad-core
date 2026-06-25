from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "minyad-agent"))
from minyad_client import MinyadClient  # noqa: E402


class SequenceTransport(httpx.BaseTransport):
    def __init__(self, outcomes: list[httpx.Response | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_client_retries_transient_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequenceTransport([
        httpx.ConnectError("connection refused"),
        httpx.Response(200, json={"ok": True}),
    ])

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))

    sleeps: list[float] = []
    client = MinyadClient("http://minyad-api:8000", retries=1, backoff_seconds=0.5, sleep=sleeps.append)

    assert client.get_state() == {"ok": True}
    assert len(transport.requests) == 2
    assert sleeps == [0.5]


def test_client_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequenceTransport([httpx.Response(404, json={"detail": "missing"})])
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))

    client = MinyadClient("http://minyad-api:8000", retries=3, sleep=lambda _delay: None)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_state()
    assert len(transport.requests) == 1


def test_client_sends_api_secret_header(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SequenceTransport([httpx.Response(200, json={"ok": True})])
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))

    client = MinyadClient("http://minyad-api:8000", api_secret="agent-secret")

    assert client.get_state() == {"ok": True}
    assert transport.requests[0].headers["X-API-Key"] == "agent-secret"
