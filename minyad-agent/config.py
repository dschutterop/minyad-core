"""Runtime configuration for the Minyad operator agent."""

from __future__ import annotations

import os

MINYAD_API_URL = os.getenv("MINYAD_API_URL", "http://minyad-api:8000").rstrip("/")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}
CYCLE_MINUTES = int(os.getenv("CYCLE_MINUTES", "15"))
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1500"))
MINYAD_API_RETRIES = int(os.getenv("MINYAD_API_RETRIES", "3"))
MINYAD_API_RETRY_BACKOFF_SECONDS = float(os.getenv("MINYAD_API_RETRY_BACKOFF_SECONDS", "2"))
