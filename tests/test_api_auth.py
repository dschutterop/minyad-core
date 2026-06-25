from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

os.environ.setdefault("DB_URL", "postgresql+asyncpg://minyad:minyad@localhost:5432/minyad")

from api.main import app, require_api_key


def test_api_key_rejects_missing_server_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINYAD_API_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_api_key("provided"))

    assert exc.value.status_code == 401


def test_api_key_uses_constant_time_secret_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINYAD_API_SECRET", "expected-secret")

    asyncio.run(require_api_key("expected-secret"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_api_key("wrong-secret"))

    assert exc.value.status_code == 401


def test_all_mutating_routes_require_api_key() -> None:
    unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    unprotected: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute) or not unsafe_methods.intersection(route.methods):
            continue
        dependencies = {
            dependency.call
            for dependency in route.dependant.dependencies
        }
        if require_api_key not in dependencies:
            unprotected.append(f"{','.join(sorted(route.methods))} {route.path}")

    assert unprotected == []
