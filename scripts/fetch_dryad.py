#!/usr/bin/env python3
"""Fetch and validate the Dryad read-only aggregation endpoint."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EXPECTED_FIELDS = {
    "ts",
    "autarky",
    "trajectory_deviation",
    "dispatch_hitrate",
    "import_price_penalty",
    "soc",
    "sources",
}


def fetch_json(url: str, timeout: float, ca_file: str | None = None) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    context = ssl.create_default_context(cafile=ca_file) if ca_file and Path(ca_file).is_file() else None
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Timed out reaching {url}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {url}, got {type(payload).__name__}")
    return payload


def validate_snapshot(payload: dict[str, Any]) -> None:
    missing = sorted(EXPECTED_FIELDS - set(payload))
    if missing:
        raise RuntimeError(f"Dryad payload missing field(s): {', '.join(missing)}")
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        raise RuntimeError("Dryad payload field 'sources' is not an object")


def print_summary(payload: dict[str, Any]) -> None:
    print(f"Dryad snapshot @ {payload.get('ts')}")
    for key in ("autarky", "trajectory_deviation", "dispatch_hitrate", "import_price_penalty", "soc"):
        value = payload.get(key)
        source = (payload.get("sources") or {}).get(key) or {}
        stale = "stale" if source.get("stale") else "fresh"
        age = source.get("age_seconds")
        age_text = "unknown age" if age is None else f"{age}s old"
        print(f"  {key}: {value} ({stale}, {age_text})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MINYAD_API_URL", "https://localhost:8002"),
        help="Minyad API base URL, default: MINYAD_API_URL or https://localhost:8002",
    )
    parser.add_argument(
        "--ca-file",
        default=os.getenv("MINYAD_INTERNAL_CA_FILE", "/run/minyad/tls/internal.crt"),
        help="CA certificate for the self-signed internal API certificate",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    parser.add_argument("--history-days", type=int, default=0, help="Also fetch /api/v1/dryad/history?days=N")
    parser.add_argument("--raw", action="store_true", help="Print raw JSON instead of a compact summary")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    try:
        snapshot = fetch_json(f"{base_url}/api/v1/dryad", args.timeout, args.ca_file)
        validate_snapshot(snapshot)
        if args.raw:
            print(json.dumps(snapshot, indent=2, sort_keys=True))
        else:
            print_summary(snapshot)

        if args.history_days:
            query = urlencode({"days": max(1, min(400, args.history_days))})
            history = fetch_json(f"{base_url}/api/v1/dryad/history?{query}", args.timeout, args.ca_file)
            print()
            if args.raw:
                print(json.dumps({"history": history}, indent=2, sort_keys=True))
            else:
                series = history.get("series") if isinstance(history.get("series"), list) else []
                print(f"Dryad history: {len(series)} day(s), requested={history.get('days')}")
                if series:
                    print(f"  first: {series[0]}")
                    print(f"  last:  {series[-1]}")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
