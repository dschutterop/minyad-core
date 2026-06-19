#!/usr/bin/env python3
"""Refresh the Enphase Envoy owner token and restart the bridge service."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

DEFAULT_ENV_FILE = Path("/opt/minyad/host-services/.env")
DEFAULT_TOKEN_FILE = Path("/opt/minyad/host-services/.token")
DEFAULT_SERVICE_NAME = "enphase_bridge.service"
LOGIN_URL = "https://enlighten.enphaseenergy.com/login/login.json"
TOKEN_URL = "https://entrez.enphaseenergy.com/tokens"

LOGGER_NAME = "enphase_token_refresh"
logger = logging.getLogger(LOGGER_NAME)


class DebugRecorder:
    """Emit step-by-step diagnostics without logging secrets."""

    def __init__(self, debug_dir: Path | None = None) -> None:
        self.debug_dir = debug_dir
        self.step_number = 0
        if self.debug_dir:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            self.debug_dir.chmod(0o700)

    def step(self, message: str, **details: Any) -> None:
        self.step_number += 1
        suffix = ""
        if details:
            formatted = " ".join(f"{key}={value!r}" for key, value in details.items())
            suffix = f" ({formatted})"
        logger.info("Step %s: %s%s", self.step_number, message, suffix)

    def response(self, name: str, response: requests.Response) -> None:
        self.step(
            f"{name} response received",
            status_code=response.status_code,
            url=response.url,
            content_type=response.headers.get("content-type", ""),
            bytes=len(response.text),
        )
        if not self.debug_dir:
            return
        path = self.debug_dir / f"{self.step_number:02d}-{name}.txt"
        path.write_text(_redact_debug_text(response.text[:20000]))
        path.chmod(0o600)
        logger.info("Wrote sanitized %s response body to %s", name, path)


def _redact_debug_text(text: str) -> str:
    secret_keys = r"password|access[_-]?token|id[_-]?token|session_id"
    text = re.sub(
        rf"\b({secret_keys})([\"']?\s*[:=]\s*[\"'])([^\"']+)([\"'])",
        r"\1\2<redacted>\4",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b({secret_keys})([\"']?\s*[:=]\s*)([^&\s\"']+)",
        r"\1\2<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    return text


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


def _extract_session_id(text: str) -> str | None:
    json_session_id = _extract_json_session_id(text)
    if json_session_id:
        return json_session_id

    for input_match in re.finditer(r"<input\b[^>]*>", text, flags=re.IGNORECASE):
        element = input_match.group(0)
        if re.search(r"\bname\s*=\s*['\"]session_id['\"]", element, flags=re.IGNORECASE):
            value_match = re.search(
                r"\bvalue\s*=\s*['\"]([^'\"]+)['\"]", element, flags=re.IGNORECASE
            )
            if value_match:
                return value_match.group(1)
    return None


def _extract_json_session_id(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        value = payload.get("session_id") or payload.get("sessionId")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def login_entrez(
    session: requests.Session,
    username: str,
    password: str,
    debug: DebugRecorder | None = None,
) -> str:
    """Log in to Enphase Enlighten and return the session_id."""
    debug = debug or DebugRecorder()
    debug.step(
        "Submitting Enphase credentials",
        url=LOGIN_URL,
        username=username,
        password="<redacted>",
    )
    response = session.post(
        LOGIN_URL,
        data={"user[email]": username, "user[password]": password},
        timeout=15,
    )
    debug.response("login-post", response)
    response.raise_for_status()

    debug.step("Searching login response for session_id")
    session_id = _extract_session_id(response.text)
    if not session_id:
        raise RuntimeError(
            "session_id not found; Enphase login flow changed or credentials are invalid. "
            "Set ENPHASE_DEBUG_DIR to capture sanitized response bodies for troubleshooting."
        )
    debug.step("Found session_id in login response")
    return session_id


def fetch_token(
    session: requests.Session,
    session_id: str,
    envoy_serial: str,
    username: str,
    debug: DebugRecorder | None = None,
) -> str:
    """Fetch a JWT owner token for the configured Envoy serial number."""
    debug = debug or DebugRecorder()
    debug.step(
        "Requesting owner token", url=TOKEN_URL, serial_num=envoy_serial, session_id="<redacted>"
    )
    response = session.post(
        TOKEN_URL,
        json={"session_id": session_id, "serial_num": envoy_serial, "username": username},
        timeout=15,
    )
    debug.response("token-post", response)
    response.raise_for_status()
    token = response.text.strip()
    if not token or len(token) < 100:
        raise RuntimeError(
            f"Unexpected token response: {_redact_debug_text(token[:200])}. "
            "Set ENPHASE_DEBUG_DIR to capture sanitized response bodies for troubleshooting."
        )
    debug.step("Received token response", token_chars=len(token))
    return token


def write_token_file(token: str, token_file: Path) -> None:
    """Atomically create or replace the token file for the bridge service."""
    token_group = os.getenv("ENPHASE_TOKEN_GROUP")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = token_file.with_name(f".{token_file.name}.tmp")
    temp_file.write_text(f"{token}\n")
    if token_group:
        shutil.chown(temp_file, group=token_group)
        temp_file.chmod(0o640)
    else:
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
    debug_dir_value = os.getenv("ENPHASE_DEBUG_DIR")
    debug = DebugRecorder(Path(debug_dir_value) if debug_dir_value else None)

    debug.step(
        "Loaded configuration", env_file=env_file, token_file=token_file, service_name=service_name
    )
    session = requests.Session()
    session_id = login_entrez(session, username, password, debug)
    token = fetch_token(session, session_id, envoy_serial, username, debug)
    debug.step("Writing token file", token_file=token_file)
    write_token_file(token, token_file)
    debug.step("Restarting bridge service", service_name=service_name)
    restart_service(service_name)
    logger.info(
        "Token refreshed (%s chars), wrote %s, restarted %s", len(token), token_file, service_name
    )


if __name__ == "__main__":
    main()
