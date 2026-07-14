#!/usr/bin/env python3
"""Fail a public release when known launch blockers are still present."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRIVATE_PATHS = (
    "minyad-trade",
    "minyad-agent",
    "minyad/strategy/v3",
    "tests/strategy/v3",
    "strategy_v3.md",
)

PRIVATE_REFERENCES = (
    "ENTSOE",
    "ENTSO-E",
    "Anthropic",
    "ANTHROPIC",
    "minyad-trade",
    "minyad-agent",
    "strategy/v3",
    "strategy_v3",
    "Vesper",
    "Kairos",
    "Chronos",
)

SENSITIVE_HISTORY_PATH_RE = re.compile(
    r"(^|/)(\.env|\.env\.[^/]+|secrets?|secrets\.[^/]+|.*\.pem|.*\.key|.*\.p12|.*\.pfx|.*\.jks|\.token|.*\.token|.*private.*)$"
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
HOSTNAME_RE = re.compile(r"\bpknp[a-z0-9.-]*\b", re.IGNORECASE)
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
    )
)

ALLOWLIST_PATHS = {
    Path("scripts/public_release_gate.py"),
}

# Reviewed and explicitly accepted line-level exceptions to check_file_contents(). Every entry
# here is either real interop data the private services actually write/read (renaming it here
# would break that interop for no privacy benefit) or an unavoidable side effect of what a test
# is verifying. Keyed on exact line text rather than line number so an edit to the line drops
# the exemption and forces a fresh review instead of silently carrying it forward.
CONTENT_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "README.md",
        "- Trading, day-ahead pricing, and ENTSO-E integrations.",
    ): "This repo's own \"Not included\" list -- states ENTSO-E integration isn't here, doesn't leak anything.",
    (
        "api/dryad.py",
        "          and source in ('strategy_v3', 'strategy_v2', 'kairos', 'vesper')",
    ): "Real 'source' tags the private planner/agent write to setpoint_log; renaming breaks dispatch_hitrate.",
    (
        "api/main.py",
        '    elif source in {"strategy_v2", "strategy_v3", "goodwe_bridge"}:',
    ): "Real 'source' tag matching for sign-convention lookup; must match what the private planner writes.",
    (
        "tests/test_agent_dashboard.py",
        "def test_serialize_control_decision_labels_strategy_v3_signs() -> None:",
    ): "Test name for the case below; renaming the tag would test the wrong thing.",
    (
        "tests/test_agent_dashboard.py",
        '            "source": "strategy_v3",',
    ): "Test fixture exercising the real strategy_v3 source tag.",
    (
        "tests/test_api_settings_endpoints.py",
        '    row = {"setpoint_w": 0, "discharge_allowed": False, "source": "strategy_v3"}',
    ): "Test fixture exercising the real strategy_v3 source tag.",
    (
        "tests/test_api_settings_endpoints.py",
        '    row = {"setpoint_w": 0, "discharge_allowed": True, "source": "strategy_v3"}',
    ): "Test fixture exercising the real strategy_v3 source tag.",
    (
        "tests/test_api_settings_endpoints.py",
        '    row = {"setpoint_w": 500, "discharge_allowed": False, "source": "strategy_v3"}',
    ): "Test fixture exercising the real strategy_v3 source tag.",
    (
        "tests/test_api_pure_helpers.py",
        '@pytest.mark.parametrize("value", ["192.0.2", "203.0.113.256", "not.an.ip.addr", "1.2.3.4.5", ""])',
    ): "203.0.113.256 is deliberately invalid (octet 256) to test IPv4 rejection; any such value fails ipaddress parsing regardless of prefix.",
}


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def tracked_files() -> list[Path]:
    output = run_git(["ls-files"])
    return [Path(line) for line in output.splitlines() if line]


def all_history_paths() -> set[str]:
    output = run_git(["log", "--all", "--name-only", "--pretty=format:"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def is_allowed_ip_literal(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_unspecified or any(ip in network for network in DOCUMENTATION_NETWORKS):
        return True
    return not (
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def scan_text_file(path: Path) -> str | None:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def add_failure(failures: list[str], category: str, detail: str) -> None:
    failures.append(f"{category}: {detail}")


def check_private_paths(files: list[Path], failures: list[str]) -> None:
    file_names = {path.as_posix() for path in files}
    for private_path in PRIVATE_PATHS:
        if any(name == private_path or name.startswith(f"{private_path}/") for name in file_names):
            add_failure(failures, "private path still tracked", private_path)


def check_history_paths(failures: list[str]) -> None:
    for name in sorted(all_history_paths()):
        if any(name == path or name.startswith(f"{path}/") for path in PRIVATE_PATHS):
            add_failure(failures, "private path still in git history", name)
        if name.endswith(".env.example"):
            continue
        if SENSITIVE_HISTORY_PATH_RE.search(name):
            add_failure(failures, "sensitive path still in git history", name)


def check_file_contents(files: list[Path], failures: list[str]) -> None:
    for path in files:
        if path in ALLOWLIST_PATHS:
            continue
        text = scan_text_file(path)
        if text is None:
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            if (path.as_posix(), line) in CONTENT_ALLOWLIST:
                continue

            for reference in PRIVATE_REFERENCES:
                if reference in line:
                    add_failure(failures, "private reference", f"{path}:{line_no}: {reference}")

            for match in IPV4_RE.finditer(line):
                value = match.group(0)
                if not is_allowed_ip_literal(value):
                    add_failure(failures, "non-public IP literal", f"{path}:{line_no}: {value}")

            for match in MAC_RE.finditer(line):
                add_failure(failures, "MAC address literal", f"{path}:{line_no}: {match.group(0)}")

            if HOSTNAME_RE.search(line):
                add_failure(failures, "private hostname literal", f"{path}:{line_no}")


def check_daniel_approval(failures: list[str], require_approval: bool) -> None:
    if not require_approval:
        return
    approval = (ROOT / ".public-release-approved").read_text(encoding="utf-8").strip() if (ROOT / ".public-release-approved").exists() else ""
    if approval != "Daniel approved public file list":
        add_failure(
            failures,
            "missing human approval",
            "create .public-release-approved with exactly: Daniel approved public file list",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-daniel-approval",
        action="store_true",
        help="Require the explicit second-human approval marker for public release.",
    )
    args = parser.parse_args()

    failures: list[str] = []
    files = tracked_files()
    check_private_paths(files, failures)
    check_history_paths(failures)
    check_file_contents(files, failures)
    check_daniel_approval(failures, args.require_daniel_approval)

    if failures:
        print("Public release gate failed. Blockers:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Public release gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
