#!/usr/bin/env python3
"""Convert Trivy JSON image reports to SonarQube generic external issues."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

DOCKERFILES = {
    "migrate": "migrate/Dockerfile",
    "ingestion": "ingestion/Dockerfile",
    "control": "control/Dockerfile",
    "strategy": "minyad-strategy/Dockerfile",
    "deadman": "deadman/Dockerfile",
    "api": "api/Dockerfile",
    "frontend": "frontend/Dockerfile",
    "mobile-frontend": "mobile-frontend/Dockerfile",
    "forecast": "forecast/Dockerfile",
    "reporting": "reporting/Dockerfile",
    "monitoring": "monitoring/Dockerfile",
}

SEVERITY_MAP = {
    "UNKNOWN": "INFO",
    "LOW": "MINOR",
    "MEDIUM": "MAJOR",
    "HIGH": "CRITICAL",
    "CRITICAL": "BLOCKER",
}


def expand_reports(patterns: list[str]) -> list[Path]:
    reports: list[Path] = []
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        reports.extend(matches or [Path(pattern)])
    return sorted(set(reports))


def service_name(report_path: Path) -> str:
    name = report_path.stem
    for prefix in ("trivy-report-", "trivy-"):
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def vulnerability_message(service: str, target: str, vulnerability: dict[str, Any]) -> str:
    vuln_id = vulnerability.get("VulnerabilityID", "unknown vulnerability")
    package = vulnerability.get("PkgName", "unknown package")
    installed = vulnerability.get("InstalledVersion", "unknown version")
    fixed = vulnerability.get("FixedVersion") or "no fixed version"
    title = vulnerability.get("Title") or vulnerability.get("Description") or vuln_id
    return (
        f"{service} image: {vuln_id} in {package} {installed} "
        f"(fixed: {fixed}, target: {target}) - {title}"
    )


def issue_for(
    service: str,
    dockerfile: str,
    target: str,
    vulnerability: dict[str, Any],
) -> dict[str, Any]:
    severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()
    vuln_id = vulnerability.get("VulnerabilityID", "trivy-vulnerability")
    package = vulnerability.get("PkgName", "unknown-package")
    return {
        "engineId": "trivy",
        "ruleId": f"{vuln_id}:{package}",
        "severity": SEVERITY_MAP.get(severity, "MAJOR"),
        "type": "VULNERABILITY",
        "primaryLocation": {
            "message": vulnerability_message(service, target, vulnerability),
            "filePath": dockerfile,
        },
    }


def iter_issues(report_path: Path, ignore_unfixed: bool) -> list[dict[str, Any]]:
    service = service_name(report_path)
    dockerfile = DOCKERFILES.get(service, "docker-compose.yml")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    issues: list[dict[str, Any]] = []

    for result in report.get("Results", []):
        target = result.get("Target", report.get("ArtifactName", service))
        for vulnerability in result.get("Vulnerabilities") or []:
            if ignore_unfixed and not vulnerability.get("FixedVersion"):
                continue
            issues.append(issue_for(service, dockerfile, target, vulnerability))

    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", help="Trivy JSON report path or glob")
    parser.add_argument("--output", default="sonar-trivy-issues.json")
    parser.add_argument("--ignore-unfixed", action="store_true")
    parser.add_argument(
        "--fail-on-severity",
        action="append",
        default=[],
        help="Fail when an imported issue has this Trivy severity (repeatable).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = expand_reports(args.reports)
    missing = [str(path) for path in reports if not path.exists()]
    if missing:
        print(f"Missing Trivy report(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    issues: list[dict[str, Any]] = []
    for report in reports:
        issues.extend(iter_issues(report, args.ignore_unfixed))

    output = Path(args.output)
    output.write_text(json.dumps({"issues": issues}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(issues)} SonarQube external issue(s) to {output}")

    fail_severities = {severity.upper() for severity in args.fail_on_severity}
    if fail_severities:
        failing = [
            issue
            for issue in issues
            if issue["severity"] in {SEVERITY_MAP.get(sev, sev) for sev in fail_severities}
        ]
        if failing:
            print(
                f"Found {len(failing)} Trivy issue(s) matching "
                f"{', '.join(sorted(fail_severities))}.",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
