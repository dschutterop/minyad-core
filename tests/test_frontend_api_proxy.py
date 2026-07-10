import asyncio
import os

os.environ.setdefault("API_BASE_URL", "https://minyad-api:8000")

import httpx
from fastapi.testclient import TestClient

import frontend.main as frontend_main

app = frontend_main.app


def test_api_proxy_preserves_api_prefix(monkeypatch):
    captured = {}
    monkeypatch.setattr(frontend_main, "MINYAD_API_SECRET", "proxy-secret")

    async def fake_request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(201, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    with TestClient(app) as client:
        response = client.post("/api/messages", json={"body": "hello"})

    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert captured["url"] == "/api/messages"
    assert captured["headers"]["X-API-Key"] == "proxy-secret"


def test_api_proxy_replaces_browser_supplied_api_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(frontend_main, "MINYAD_API_SECRET", "trusted-proxy-secret")

    async def fake_request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    with TestClient(app) as client:
        response = client.put(
            "/api/system-settings",
            headers={"X-API-Key": "browser-controlled-secret"},
            json={"theme": "dark"},
        )

    assert response.status_code == 200
    assert captured["headers"]["X-API-Key"] == "trusted-proxy-secret"


def test_api_proxy_falls_back_to_legacy_unprefixed_route(monkeypatch):
    calls = []

    async def fake_request(self, method, url, **kwargs):
        await asyncio.sleep(0)
        calls.append(url)
        if url == "/api/grid/status":
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(200, json={"solar_power_w": 1805})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    with TestClient(app) as client:
        response = client.get("/api/grid/status")

    assert response.status_code == 200
    assert response.json() == {"solar_power_w": 1805}
    assert calls == ["/api/grid/status", "/grid/status"]


def test_reporting_route_renders_decision_log_not_scaffold():
    with TestClient(app) as client:
        response = client.get("/reporting")

    assert response.status_code == 200
    assert "Control decisions" in response.text
    assert "Reporting module scaffold" not in response.text


def test_settings_route_renders_language_selector():
    with TestClient(app) as client:
        response = client.get("/settings")

    assert response.status_code == 200
    assert 'name="language"' in response.text or "name='language'" in response.text
    assert "English" in response.text
    assert "Dutch" in response.text
    assert "goodwe_poll_interval_grace_s" in response.text


def test_frontend_version_endpoint_is_local_and_uncached():
    with TestClient(app) as client:
        response = client.get("/frontend-version")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.json()["version"] == frontend_main.FRONTEND_VERSION
    assert response.json()["build_id"] == frontend_main.FRONTEND_BUILD_ID


def test_frontend_html_polls_for_new_container_version():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "fetch('/frontend-version', {cache: 'no-store'})" in response.text
    assert "window.location.reload()" in response.text
