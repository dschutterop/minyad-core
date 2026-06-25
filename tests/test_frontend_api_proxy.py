import os

os.environ.setdefault("API_BASE_URL", "http://minyad-api:8000")

import httpx
from fastapi.testclient import TestClient

from frontend.main import app


def test_api_proxy_preserves_api_prefix(monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return httpx.Response(201, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    with TestClient(app) as client:
        response = client.post("/api/messages", json={"body": "hello"})

    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert captured["url"] == "/api/messages"
