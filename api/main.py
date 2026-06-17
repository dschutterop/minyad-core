"""Minyad REST API scaffold."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.db import ApiKey, get_session, init_db

app = FastAPI(title="Minyad API")


class ApiKeyCreate(BaseModel):
    name: str


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api-keys", status_code=202)
def scaffold_api_key(request: ApiKeyCreate, session: Session = Depends(get_session)) -> dict[str, str]:
    _ = session.query(ApiKey).filter(ApiKey.name == request.name).first()
    return {"status": "scaffolded", "message": "API key generation is intentionally not implemented yet"}
