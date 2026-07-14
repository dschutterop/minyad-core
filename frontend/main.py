"""Minyad web frontend."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

try:
    from frontend.assets import FRONTEND_BUILD_ID, FRONTEND_VERSION
except ModuleNotFoundError:  # pragma: no cover - exercised by the frontend Docker image layout
    from assets import FRONTEND_BUILD_ID, FRONTEND_VERSION
try:
    from frontend.views import (
        MENU,
        agent_body,
        asset_steering_body,
        battery_control_body,
        battery_settings_body,
        dsmr_body,
        health_body,
        history_body,
        html_response,
        render_dashboard_page,
        render_page,
        reporting_body,
        solar_body,
        trade_body,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the frontend Docker image layout
    from views import (
        MENU,
        agent_body,
        asset_steering_body,
        battery_control_body,
        battery_settings_body,
        dsmr_body,
        health_body,
        history_body,
        html_response,
        render_dashboard_page,
        render_page,
        reporting_body,
        solar_body,
        trade_body,
    )

app = FastAPI(title="Minyad Frontend")
API_BASE_URL = os.getenv("API_BASE_URL", "https://minyad-api:8000")
MINYAD_INTERNAL_CA_FILE = os.getenv("MINYAD_INTERNAL_CA_FILE", "/run/minyad/tls/internal.crt")
MINYAD_API_SECRET = os.getenv("MINYAD_API_SECRET", "")

# Re-exported for backward compatibility: tests/test_frontend_api_proxy.py accesses these
# via `frontend_main.FRONTEND_VERSION` / `frontend_main.FRONTEND_BUILD_ID`.
__all__ = ["app", "FRONTEND_BUILD_ID", "FRONTEND_VERSION"]


def _api_verify() -> str | bool:
    ca_file = Path(MINYAD_INTERNAL_CA_FILE)
    return str(ca_file) if ca_file.is_file() else True


@app.get("/frontend-version")
async def frontend_version() -> JSONResponse:
    return JSONResponse(
        {"version": FRONTEND_VERSION, "build_id": FRONTEND_BUILD_ID},
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_proxy(path: str, request: Request) -> Response:
    """Forward browser API calls to the API service without hiding failures."""
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "x-api-key"}
    }
    if MINYAD_API_SECRET:
        headers["X-API-Key"] = MINYAD_API_SECRET
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0, verify=_api_verify()) as client:
            body = await request.body()
            response = await client.request(
                request.method,
                f"/api/{path}",
                params=request.query_params,
                content=body,
                headers=headers,
            )
            if response.status_code == 404:
                response = await client.request(
                    request.method,
                    f"/{path}",
                    params=request.query_params,
                    content=body,
                    headers=headers,
                )
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "detail": "Unable to reach Minyad API service",
                "api_base_url": API_BASE_URL,
                "error": str(exc),
            },
        )

    excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in excluded_headers
    }
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )


@app.get("/")
async def dashboard() -> HTMLResponse:
    return html_response(render_dashboard_page())


@app.get("/reporting")
async def reporting() -> HTMLResponse:
    return html_response(render_page("Reporting", reporting_body()))


@app.get("/{section}")
async def section(section: str) -> HTMLResponse:
    title = "DSMR" if section.lower() == "dsmr" else section.replace("-", " ").title()
    if title not in MENU:
        title = "Dashboard"
    if title == "Settings":
        return html_response(render_page(title, battery_settings_body()))
    if title == "Agent":
        return html_response(render_page(title, agent_body()))
    if title == "Health":
        return html_response(render_page(title, health_body()))
    if title == "Battery":
        return html_response(render_page(title, battery_control_body()))
    if title == "Asset Steering":
        return html_response(render_page(title, asset_steering_body()))
    if title == "DSMR":
        return html_response(render_page(title, dsmr_body()))
    if title == "History":
        return html_response(render_page(title, history_body()))
    if title == "Trade":
        return html_response(render_page(title, trade_body()))
    if title == "Solar":
        return html_response(render_page(title, solar_body()))
    if title == "Reporting":
        return html_response(render_page(title, reporting_body()))
    content = f"{title} module scaffold."
    return html_response(render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>"))
