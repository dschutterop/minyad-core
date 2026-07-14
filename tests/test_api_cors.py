from __future__ import annotations

import importlib
import os

from fastapi.testclient import TestClient

os.environ.setdefault("DB_URL", "postgresql+asyncpg://minyad:minyad@localhost:5432/minyad")


def test_api_cors_defaults_are_restricted() -> None:
    api_main = importlib.import_module("api.main")
    middleware = next(
        item
        for item in api_main.app.user_middleware
        if item.cls.__name__ == "CORSMiddleware"
    )

    assert middleware.kwargs["allow_origins"] == [
        "http://localhost:8084",
        "http://localhost:8085",
    ]
    assert "*" not in middleware.kwargs["allow_origins"]
    assert middleware.kwargs["allow_headers"] == ["X-API-Key", "Content-Type"]


def test_api_cors_allows_only_configured_frontend_origin() -> None:
    api_main = importlib.import_module("api.main")
    client = TestClient(api_main.app)

    allowed = client.options(
        "/system-settings",
        headers={
            "Origin": "http://localhost:8084",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "X-API-Key, Content-Type",
        },
    )
    denied = client.options(
        "/system-settings",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "PUT",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8084"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
