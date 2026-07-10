import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "trivy_to_sonar.py"
spec = importlib.util.spec_from_file_location("trivy_to_sonar", MODULE_PATH)
trivy_to_sonar = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["trivy_to_sonar"] = trivy_to_sonar
spec.loader.exec_module(trivy_to_sonar)


def write_report(path, vulnerabilities):
    path.write_text(
        json.dumps(
            {
                "ArtifactName": "image",
                "Results": [
                    {
                        "Target": "python-packages",
                        "Vulnerabilities": vulnerabilities,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_expand_reports_expands_globs_and_keeps_missing_paths(tmp_path):
    one = tmp_path / "trivy-report-api.json"
    two = tmp_path / "trivy-report-control.json"
    one.write_text("{}", encoding="utf-8")
    two.write_text("{}", encoding="utf-8")

    reports = trivy_to_sonar.expand_reports([str(tmp_path / "trivy-report-*.json"), str(tmp_path / "missing.json")])

    assert reports == sorted({one, two, tmp_path / "missing.json"})


def test_service_name_strips_known_prefixes():
    assert trivy_to_sonar.service_name(Path("trivy-report-api.json")) == "api"
    assert trivy_to_sonar.service_name(Path("trivy-control.json")) == "control"
    assert trivy_to_sonar.service_name(Path("custom.json")) == "custom"


def test_issue_for_maps_severity_and_message():
    vulnerability = {
        "VulnerabilityID": "CVE-1",
        "PkgName": "openssl",
        "InstalledVersion": "1.0",
        "FixedVersion": "1.1",
        "Severity": "HIGH",
        "Title": "bad thing",
    }

    issue = trivy_to_sonar.issue_for("api", "api/Dockerfile", "python-packages", vulnerability)

    assert issue["engineId"] == "trivy"
    assert issue["ruleId"] == "CVE-1:openssl"
    assert issue["severity"] == "CRITICAL"
    assert issue["type"] == "VULNERABILITY"
    assert issue["primaryLocation"]["filePath"] == "api/Dockerfile"
    assert "api image: CVE-1 in openssl 1.0" in issue["primaryLocation"]["message"]


def test_iter_issues_uses_dockerfile_mapping_and_ignore_unfixed(tmp_path):
    report = tmp_path / "trivy-report-api.json"
    write_report(
        report,
        [
            {"VulnerabilityID": "CVE-fixed", "PkgName": "pkg", "Severity": "LOW", "FixedVersion": "2"},
            {"VulnerabilityID": "CVE-open", "PkgName": "pkg", "Severity": "CRITICAL"},
        ],
    )

    issues = trivy_to_sonar.iter_issues(report, ignore_unfixed=True)

    assert len(issues) == 1
    assert issues[0]["primaryLocation"]["filePath"] == "api/Dockerfile"
    assert issues[0]["severity"] == "MINOR"


def test_main_writes_report_and_fails_on_requested_severity(monkeypatch, tmp_path, capsys):
    report = tmp_path / "trivy-report-api.json"
    output = tmp_path / "sonar.json"
    write_report(
        report,
        [{"VulnerabilityID": "CVE-1", "PkgName": "pkg", "Severity": "HIGH", "FixedVersion": "2"}],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["trivy_to_sonar.py", "--output", str(output), "--fail-on-severity", "HIGH", str(report)],
    )

    exit_code = trivy_to_sonar.main()

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["issues"]) == 1
    assert "matching HIGH" in capsys.readouterr().err


def test_main_returns_two_for_missing_reports(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(sys, "argv", ["trivy_to_sonar.py", str(missing)])

    assert trivy_to_sonar.main() == 2
