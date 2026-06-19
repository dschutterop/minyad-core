#!/usr/bin/env python3
"""Refresh the Enphase Envoy owner token and restart the bridge service."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

import requests
from dotenv import load_dotenv

DEFAULT_ENV_FILE = Path("/opt/minyad/host-services/.env")
DEFAULT_TOKEN_FILE = Path("/opt/minyad/host-services/.token")
DEFAULT_SERVICE_NAME = "enphase_bridge.service"

LOGGER_NAME = "enphase_token_refresh"
logger = logging.getLogger(LOGGER_NAME)


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ValueError(f"{name} is required")
    return value.strip()


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def login_entrez(session: requests.Session, username: str, password: str) -> str:
    """Log in to entrez.enphaseenergy.com and return the session_id."""
    response = session.post(
        "https://entrez.enphaseenergy.com/login",
        data={"username": username, "password": password},
        timeout=15,
    )
    response.raise_for_status()
    match = re.search(r'name="session_id" value="([^"]+)"', response.text)
    if not match:
        raise RuntimeError("session_id not found; Enphase login flow changed or credentials are invalid")
    return match.group(1)


def fetch_token(session: requests.Session, session_id: str, envoy_serial: str) -> str:
    """Fetch a JWT owner token for the configured Envoy serial number."""
    response = session.post(
        "https://entrez.enphaseenergy.com/entrez_tokens",
        data={"session_id": session_id, "serial_num": envoy_serial},
        timeout=15,
    )
    response.raise_for_status()
    token = response.text.strip()
    if not token or len(token) < 100:
        raise RuntimeError(f"Unexpected token response: {token[:200]}")
    return token


def write_token_file(token: str, token_file: Path) -> None:
    """Atomically create or replace the token file with owner-readable contents."""
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = token_file.with_name(f".{token_file.name}.tmp")
    temp_file.write_text(f"{token}\n")
    temp_file.chmod(0o600)
    temp_file.replace(token_file)


def restart_service(service_name: str) -> None:
    subprocess.run(["systemctl", "restart", service_name], check=True)


def main() -> None:
    env_file = Path(os.getenv("MINYAD_ENV_FILE", DEFAULT_ENV_FILE))
    load_dotenv(env_file)
    configure_logging()

    username = _get_required_env("ENPHASE_USERNAME")
    password = _get_required_env("ENPHASE_PASSWORD")
    envoy_serial = _get_required_env("ENVOY_SERIAL")
    token_file = Path(os.getenv("ENPHASE_TOKEN_FILE", DEFAULT_TOKEN_FILE))
    service_name = os.getenv("ENPHASE_REFRESH_RESTART_SERVICE", DEFAULT_SERVICE_NAME)

    session = requests.Session()
    session_id = login_entrez(session, username, password)
    token = fetch_token(session, session_id, envoy_serial)
    write_token_file(token, token_file)
    restart_service(service_name)
    logger.info("Token refreshed (%s chars), wrote %s, restarted %s", len(token), token_file, service_name)


if __name__ == "__main__":
    main()
