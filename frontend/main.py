"""Minyad frontend scaffold."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from shared.db import init_db

app = FastAPI(title="Minyad Frontend")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
    <html><head><title>Minyad</title></head>
    <body><h1>Minyad</h1><p>Dashboard scaffold</p><nav><a href='/settings'>Settings</a></nav></body></html>
    """


@app.get("/settings", response_class=HTMLResponse)
def settings() -> str:
    return """
    <html><head><title>Minyad Settings</title></head>
    <body><h1>Settings</h1><p>Runtime settings will be loaded from PostgreSQL.</p></body></html>
    """
